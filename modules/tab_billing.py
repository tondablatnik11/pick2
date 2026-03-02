import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

# Kouzlo pro bleskové překreslování grafu bez načítání celé stránky
try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@fast_render
def render_interactive_chart(billing_df):
    cat_options = ["Všechny kategorie"] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
    selected_cat = st.selectbox("Vyberte kategorii pro graf:", options=cat_options, label_visibility="collapsed")
    
    if selected_cat == "Všechny kategorie":
        plot_df = billing_df.copy()
    else:
        plot_df = billing_df[billing_df["Category_Full"] == selected_cat].copy()
    
    tr_df = plot_df.groupby("Month").agg(to_sum=("pocet_to", "sum"), hu_sum=("pocet_hu", "sum"), poh=("pohyby_celkem", "sum"), lok=("pocet_lokaci", "sum")).reset_index()
    tr_df['prum_poh'] = np.where(tr_df['lok']>0, tr_df['poh']/tr_df['lok'], 0)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['to_sum'], name='Počet TO', marker_color='#38bdf8', text=tr_df['to_sum'], textposition='auto'))
    fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['hu_sum'], name='Počet HU', marker_color='#818cf8', text=tr_df['hu_sum'], textposition='auto'))
    fig.add_trace(go.Scatter(x=tr_df['Month'], y=tr_df['prum_poh'], name='Pohyby na lokaci', yaxis='y2', mode='lines+markers+text', text=tr_df['prum_poh'].round(1), textposition='top center', textfont=dict(color='#f43f5e'), line=dict(color='#f43f5e', width=3)))
    
    fig.update_layout(yaxis2=dict(title="Pohyby", side="right", overlaying="y", showgrid=False), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)


def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data):
    st.markdown(f"<div class='section-header'><h3>💰 Korelace mezi Pickováním a Účtováním</h3><p>Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.</p></div>", unsafe_allow_html=True)
    
    # 1. Agresivní čištění čísel zakázek (odstranění předních nul napříč aplikací)
    df_pick['Clean_Del'] = df_pick['Delivery'].astype(str).str.strip().str.lstrip('0')
    
    # 2. Vytvoření spolehlivé mapy Kategorií
    del_to_cat_map = {}
    if aus_data and "LIKP" in aus_data and not aus_data["LIKP"].empty:
        df_likp_tmp = aus_data["LIKP"]
        df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame())
        df_t031_tmp = aus_data.get("T031", pd.DataFrame())
        
        kep_set = set()
        if not df_sdshp_tmp.empty:
            col_s = df_sdshp_tmp.columns[0]
            col_k = next((c for c in df_sdshp_tmp.columns if "KEP" in str(c).upper() or "FÄHIG" in str(c).upper()), None)
            if col_k: 
                kep_set = set(df_sdshp_tmp.loc[df_sdshp_tmp[col_k].astype(str).str.strip() == "X", col_s].astype(str).str.strip().str.lstrip('0'))
        
        order_type_map = {}
        if not df_t031_tmp.empty: 
            order_type_map = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))
        
        c_lief = df_likp_tmp.columns[0]
        c_vs = next((c for c in df_likp_tmp.columns if "Versandstelle" in str(c) or "Shipping" in str(c)), None)
        c_sped = next((c for c in df_likp_tmp.columns if "pediteur" in str(c) or "Transp" in str(c)), None)
        
        for _, r in df_likp_tmp.iterrows():
            dlv = str(r[c_lief]).strip().lstrip('0')
            vs = str(r[c_vs]).strip() if c_vs else "N"
            sped = str(r[c_sped]).strip().lstrip('0') if c_sped else ""
            
            o_type = order_type_map.get(vs, "N")
            is_kep = sped in kep_set
            kat = "OE" if o_type == "O" else "E" if is_kep else ("O" if o_type == "O" else "N")
            del_to_cat_map[dlv] = kat
            
    elif df_cats is not None and not df_cats.empty:
        c_lief = df_cats.columns[0]
        c_cat = "Category_Full" if "Category_Full" in df_cats.columns else df_cats.columns[1]
        for _, r in df_cats.iterrows():
            dlv = str(r[c_lief]).strip().lstrip('0')
            del_to_cat_map[dlv] = str(r[c_cat]).strip()

    billing_df = pd.DataFrame()
    actual_vekp = aus_data.get("VEKP") if aus_data and not aus_data.get("VEKP", pd.DataFrame()).empty else df_vekp
    actual_vepo = aus_data.get("VEPO") if aus_data and not aus_data.get("VEPO", pd.DataFrame()).empty else df_vepo

    # 3. Zpracování VEKP obalů a přímé ověření přes VEPO
    if actual_vekp is not None and not actual_vekp.empty:
        vk = actual_vekp.dropna(subset=[actual_vekp.columns[0]]).copy()
        c_hu_int = vk.columns[0]
        c_hu_ext = vk.columns[1]
        c_gen = next((c for c in vk.columns if "generierte" in str(c).lower() or "generated delivery" in str(c).lower()), None)
        c_parent = next((c for c in vk.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
        
        vk['Clean_HU_Int'] = vk[c_hu_int].astype(str).str.strip().str.lstrip('0')
        vk['Clean_HU_Ext'] = vk[c_hu_ext].astype(str).str.strip().str.lstrip('0')
        vk['Clean_Del'] = vk[c_gen].astype(str).str.strip().str.lstrip('0') if c_gen else ""
        vk['Clean_Parent'] = vk[c_parent].astype(str).str.strip().str.lstrip('0').replace({'nan':'', 'none':''}) if c_parent else ""

        # --- VEPO OVĚŘOVACÍ BLOK ---
        valid_vepo_hus = set()
        vepo_nested = set()
        vepo_parents = set()

        if actual_vepo is not None and not actual_vepo.empty:
            hu_cols = [c for c in actual_vepo.columns if "HU" in str(c).upper() or "HANDLING UNIT" in str(c).upper()]
            for c in hu_cols:
                valid_vepo_hus.update(actual_vepo[c].dropna().astype(str).str.strip().str.lstrip('0'))
            
            v_hu = next((c for c in actual_vepo.columns if "internal hu" in str(c).lower() or "hu-nummer intern" in str(c).lower()), actual_vepo.columns[0])
            v_low = next((c for c in actual_vepo.columns if "lower-level" in str(c).lower() or "untergeordn" in str(c).lower()), None)
            
            if v_low:
                vepo_nested = set(actual_vepo[v_low].dropna().astype(str).str.strip().str.lstrip('0'))
                vepo_nested = {h for h in vepo_nested if h not in ["", "nan", "none"]}
                vepo_parents = set(actual_vepo.loc[
                    actual_vepo[v_low].notna() & (actual_vepo[v_low].astype(str).str.strip() != ""),
                    v_hu
                ].astype(str).str.strip().str.lstrip('0'))

        # Než něco začneme počítat, vyřadíme HU, které nejsou uvedené ve VEPO jako reálně nabalené
        if valid_vepo_hus:
            vk = vk[vk['Clean_HU_Int'].isin(valid_vepo_hus) | vk['Clean_HU_Ext'].isin(valid_vepo_hus)].copy()

        if vepo_nested or vepo_parents:
            vk['is_top_level'] = ~vk['Clean_HU_Int'].isin(vepo_nested) & ~vk['Clean_HU_Ext'].isin(vepo_nested)
            vk['is_leaf'] = ~vk['Clean_HU_Int'].isin(vepo_parents) & ~vk['Clean_HU_Ext'].isin(vepo_parents)
        else:
            # Fallback pokud VEPO nemá stromovou strukturu
            id_map = {str(r['Clean_HU_Ext']): str(r['Clean_HU_Int']) for _, r in vk.iterrows() if str(r['Clean_HU_Ext']) != 'nan'}
            for _, r in vk.iterrows(): id_map[str(r['Clean_HU_Int'])] = str(r['Clean_HU_Int'])
            vk['Norm_Parent'] = vk['Clean_Parent'].apply(lambda x: id_map.get(x, x))
            parents = set(vk['Norm_Parent'].dropna())
            parents.discard("")
            vk['is_top_level'] = vk['Norm_Parent'] == ""
            vk['is_leaf'] = ~vk['Clean_HU_Int'].isin(parents)

        vk['Category_Full'] = vk['Clean_Del'].map(del_to_cat_map).fillna("N")
        
        # Podle Kategorie (N/E) přesně identifikujeme, které HU se fakturují
        def is_billable(row):
            kat = str(row['Category_Full']).upper()
            if kat.startswith('E') or kat.startswith('OE'): return row['is_leaf']
            return row['is_top_level']
            
        vk['is_billable'] = vk.apply(is_billable, axis=1)
        hu_counts = vk[vk['is_billable']].groupby('Clean_Del')['Clean_HU_Int'].nunique().reset_index()
        hu_counts.columns = ['Clean_Del', 'pocet_hu']

        # 4. Finální spojení ořezaných a ověřených dat
        pick_agg = df_pick.groupby("Clean_Del").agg(
            pocet_to=(queue_count_col, "nunique"),
            pohyby_celkem=("Pohyby_Rukou", "sum"),
            pocet_lokaci=("Source Storage Bin", "nunique"),
            hlavni_fronta=("Queue", "first"),
            pocet_mat=("Material", "nunique"),
            Month=("Month", "first"),
            Delivery=("Delivery", "first")
        ).reset_index()

        billing_df = pd.merge(pick_agg, hu_counts, on="Clean_Del", how="left")
        
        def fallback_category(row):
            kat = del_to_cat_map.get(row['Clean_Del'])
            if kat and " " in kat: return kat
            if not kat:
                q = str(row['hlavni_fronta']).upper()
                kat = "N"
                if 'PI_PA_OE' in q: kat = "OE"
                elif 'PI_PA' in q: kat = "E"
                elif 'PI_PL_FUOE' in q or 'PI_PL_OE' in q: kat = "O"
                elif 'PI_PL' in q: kat = "N"
            art = "Sortenrein" if row['pocet_mat'] <= 1 else "Misch"
            return f"{kat} {art}"
            
        billing_df['Category_Full'] = billing_df.apply(fallback_category, axis=1)
        billing_df['pocet_hu'] = billing_df['pocet_hu'].fillna(0).astype(int)
        billing_df['TO_navic'] = (billing_df['pocet_to'] - billing_df['pocet_hu']).clip(lower=0).astype(int)

    # VYKRESLENÍ METRIK A GRAFŮ (KORELACE)
    if not billing_df.empty:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True): st.metric("Zakázek celkem", f"{len(billing_df):,}")
        with c2:
            with st.container(border=True): st.metric("Fakturované palety/krabice (HU)", f"{int(billing_df['pocet_hu'].sum()):,}")
        with c3:
            with st.container(border=True): st.metric("Fyzických Pick TO", f"{int(billing_df['pocet_to'].sum()):,}")
        with c4:
            with st.container(border=True): st.metric("Nefakturované Picky (TO navíc)", f"{int(billing_df['TO_navic'].sum()):,}", delta_color="inverse")

        st.divider()
        col_t1, col_t2 = st.columns([1.2, 1])
        with col_t1:
            st.markdown("**Souhrn podle kategorií**")
            cat_sum = billing_df.groupby("Category_Full").agg(pocet_zakazek=("Delivery", "nunique"), pocet_to=("pocet_to", "sum"), pocet_hu=("pocet_hu", "sum"), pocet_lok=("pocet_lokaci", "sum"), poh=("pohyby_celkem", "sum"), to_navic=("TO_navic", "sum")).reset_index()
            cat_sum["prum_poh"] = np.where(cat_sum["pocet_lok"] > 0, cat_sum["poh"] / cat_sum["pocet_lok"], 0)
            disp = cat_sum[["Category_Full", "pocet_zakazek", "pocet_to", "pocet_hu", "prum_poh", "to_navic"]].copy()
            disp.columns = ["Kategorie", "Počet zakázek", "Počet TO", "Zúčtované HU", "Prům. pohybů na lokaci", "TO navíc (Ztráta)"]
            st.dataframe(disp.style.format({"Prům. pohybů na lokaci": "{:.1f}"}), use_container_width=True, hide_index=True)
            
        with col_t2:
            st.markdown("**Trend v čase (Měsíce)**")
            render_interactive_chart(billing_df)

        st.markdown(f"### ⚠️ Ztráta z konsolidace (Práce zdarma / Prodělek)")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
            imb_disp.columns = ["Delivery", "Kategorie", "Pick TO celkem", "Pohyby rukou", "Účtované HU", "TO navíc (Rozdíl)"]
            st.dataframe(imb_disp, use_container_width=True, hide_index=True)
        else: st.success("Žádné zakázky s prodělkem nenalezeny!")
        
        # --- ZCELA KOMPLETNÍ AUSWERTUNG SEKCE (Zůstává nezměněná) ---
        st.divider()
        st.subheader("📊 Analýza zásilkových dat (Auswertung)")
        if not aus_data: st.info("Pro tuto sekci nahrajte zákazníkův soubor Auswertung_Outbound_HWL.xlsx")
        else:
            df_likp = aus_data.get("LIKP", pd.DataFrame())
            df_vekp2 = aus_data.get("VEKP", pd.DataFrame())
            df_vepo = aus_data.get("VEPO", pd.DataFrame())
            df_sdshp = aus_data.get("SDSHP_AM2", pd.DataFrame())
            df_t031 = aus_data.get("T031", pd.DataFrame())
            df_t023 = aus_data.get("T023", pd.DataFrame())
            df_lips2 = aus_data.get("LIPS", pd.DataFrame())

            kep_set = set()
            if not df_sdshp.empty:
                col_k = next((c for c in df_sdshp.columns if "KEP" in str(c).upper()), None)
                if col_k: kep_set = set(df_sdshp.loc[df_sdshp[col_k].astype(str).str.strip() == "X", df_sdshp.columns[0]].astype(str).str.strip())
            
            df_lf = pd.DataFrame()
            if not df_likp.empty:
                c_lief = df_likp.columns[0]
                c_vs = next((c for c in df_likp.columns if "Versandstelle" in str(c)), None)
                c_sped = next((c for c in df_likp.columns if "pediteur" in str(c)), None)
                df_lf = df_likp[[c_lief]].copy()
                df_lf.columns = ["Lieferung"]
                df_lf["Lieferung"] = df_lf["Lieferung"].astype(str).str.strip()
                df_lf["is_KEP"] = df_likp[c_sped].astype(str).str.strip().isin(kep_set) if c_sped else False
                df_lf["Order_Type"] = "O" if c_vs else "N"
                df_lf["Kategorie"] = np.where(df_lf["is_KEP"], np.where(df_lf["Order_Type"] == "O", "OE", "E"), np.where(df_lf["Order_Type"] == "O", "O", "N"))

            df_vk = pd.DataFrame()
            if not df_vekp2.empty:
                col_map = {df_vekp2.columns[0]: "HU_intern", df_vekp2.columns[1]: "Handling_Unit_Ext"}
                c_gen = next((c for c in df_vekp2.columns if "generierte" in str(c) or "Generated" in str(c)), None)
                c_pm = next((c for c in df_vekp2.columns if str(c).strip() == "Packmittel"), None)
                c_gew = next((c for c in df_vekp2.columns if str(c).strip() == "Gesamtgewicht"), None)
                c_art = next((c for c in df_vekp2.columns if str(c).strip() == "Art"), None)
                if c_gen: col_map[c_gen] = "Lieferung"
                if c_pm: col_map[c_pm] = "Packmittel"
                if c_gew: col_map[c_gew] = "Gesamtgewicht"
                if c_art: col_map[c_art] = "Art_HU"
                
                df_vk = df_vekp2[list(col_map.keys())].rename(columns=col_map)
                df_vk["HU_intern"] = df_vk["HU_intern"].astype(str).str.strip()
                if "Gesamtgewicht" in df_vk.columns: df_vk["Gesamtgewicht"] = pd.to_numeric(df_vk["Gesamtgewicht"], errors="coerce").fillna(0)
                if not df_lf.empty and "Lieferung" in df_vk.columns: df_vk["Kategorie"] = df_vk["Lieferung"].map(df_lf.set_index("Lieferung")["Kategorie"]).fillna("N")

            st.markdown("### Kategorie zásilek (E / N / O / OE)")
            if not df_vk.empty and "Kategorie" in df_vk.columns:
                kat_grp = df_vk.groupby("Kategorie").agg(pocet_lief=("Lieferung", "nunique") if "Lieferung" in df_vk.columns else ("HU_intern", "nunique"), celk_hu=("HU_intern", "nunique")).reset_index()
                kat_grp["prumer_hu"] = kat_grp["celk_hu"] / kat_grp["pocet_lief"]
                st.dataframe(kat_grp.style.format({"prumer_hu": "{:.2f}"}), use_container_width=True, hide_index=True)

            st.markdown("### Typy krabic (Packmittel) — váhy")
            if not df_vk.empty and "Packmittel" in df_vk.columns:
                carton_agg = df_vk.groupby("Packmittel").agg(pocet=("HU_intern", "nunique"), avg_gew=("Gesamtgewicht", "mean") if "Gesamtgewicht" in df_vk.columns else ("HU_intern", "count")).reset_index().sort_values("pocet", ascending=False)
                st.dataframe(carton_agg.style.format({"avg_gew": "{:.2f} kg"}), use_container_width=True, hide_index=True)
                
            st.markdown("### Typy HU (Sortenrein / Misch / Vollpalette)")
            if not df_vk.empty and "Art_HU" in df_vk.columns:
                art_celk = df_vk["Art_HU"].value_counts()
                ca1, ca2, ca3 = st.columns(3)
                with ca1:
                    with st.container(border=True): st.metric("📦 Sortenrein", f"{art_celk.get('Sortenrein', 0):,}")
                with ca2:
                    with st.container(border=True): st.metric("🔀 Misch", f"{art_celk.get('Misch', 0):,}")
                with ca3:
                    with st.container(border=True): st.metric("🏭 Vollpalette", f"{art_celk.get('Vollpalette', 0):,}")

    else:
        st.warning("⚠️ Pro zobrazení těchto dat nahrajte soubor VEKP a VEPO.")

    return billing_df
