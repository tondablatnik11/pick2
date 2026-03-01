import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# Kouzlo pro bleskové překreslování - "Fragment"
# Izoluje graf od zbytku aplikace, takže se při změně filtru nenačítá celá záložka
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
    
    aus_category_map = {}
    if aus_data:
        df_likp_tmp = aus_data.get("LIKP", pd.DataFrame())
        df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame())
        df_t031_tmp = aus_data.get("T031", pd.DataFrame())
        kep_set = set()
        if not df_sdshp_tmp.empty:
            col_s = df_sdshp_tmp.columns[0]
            col_k = next((c for c in df_sdshp_tmp.columns if "KEP" in str(c).upper() or "FÄHIG" in str(c).upper()), None)
            if col_k: kep_set = set(df_sdshp_tmp.loc[df_sdshp_tmp[col_k].astype(str).str.strip() == "X", col_s].astype(str).str.strip())
        order_type_map = {}
        if not df_t031_tmp.empty: order_type_map = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))
        if not df_likp_tmp.empty:
            c_lief = df_likp_tmp.columns[0]
            c_vs = next((c for c in df_likp_tmp.columns if "Versandstelle" in str(c) or "Shipping" in str(c)), None)
            c_sped = next((c for c in df_likp_tmp.columns if "pediteur" in str(c) or "Transp" in str(c)), None)
            tmp_lf = df_likp_tmp[[c_lief]].copy()
            tmp_lf.columns = ["Lieferung"]
            tmp_lf["Lieferung"] = tmp_lf["Lieferung"].astype(str).str.strip()
            tmp_lf["Order_Type"] = df_likp_tmp[c_vs].astype(str).str.strip().map(order_type_map).fillna("N") if c_vs else "N"
            tmp_lf["is_KEP"] = df_likp_tmp[c_sped].astype(str).str.strip().isin(kep_set) if c_sped else False
            tmp_lf["Kategorie"] = np.where(tmp_lf["is_KEP"], np.where(tmp_lf["Order_Type"] == "O", "OE", "E"), np.where(tmp_lf["Order_Type"] == "O", "O", "N"))
            aus_category_map = tmp_lf.set_index("Lieferung")["Kategorie"].to_dict()

    billing_df = pd.DataFrame()
    if df_vekp is not None and not df_vekp.empty:
        vekp_c = df_vekp.dropna(subset=["Handling Unit", "Generated delivery"]).copy()
        vekp_filtered = vekp_c[vekp_c["Generated delivery"].isin(df_pick["Delivery"].dropna().unique())].copy()
        c_hu_int = next((c for c in vekp_filtered.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_filtered.columns[0])
        c_hu_ext = vekp_filtered.columns[1]
        c_parent = next((c for c in vekp_filtered.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower()), None)
        
        vekp_filtered['Clean_HU_Int'] = vekp_filtered[c_hu_int].astype(str).str.strip().str.lstrip('0')
        vekp_filtered['Clean_HU_Ext'] = vekp_filtered[c_hu_ext].astype(str).str.strip().str.lstrip('0')
        if c_parent: vekp_filtered['Clean_Parent'] = vekp_filtered[c_parent].astype(str).str.strip().str.lstrip('0').replace({'nan': '', 'none': ''})
        else: vekp_filtered['Clean_Parent'] = ""

        valid_base_hus = set()
        if df_vepo is not None and not df_vepo.empty:
            v_hu = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
            v_low = next((c for c in df_vepo.columns if "Lower-level" in str(c) or "untergeordn" in str(c).lower()), None)
            valid_base_hus = set(df_vepo[v_hu].astype(str).str.strip().str.lstrip('0'))
            if v_low: valid_base_hus.update(set(df_vepo[v_low].dropna().astype(str).str.strip().str.lstrip('0')))
        else:
            valid_base_hus = set(vekp_filtered['Clean_HU_Int'])

        hu_agg_list = []
        for delivery, group in vekp_filtered.groupby("Generated delivery"):
            ext_to_int = dict(zip(group['Clean_HU_Ext'], group['Clean_HU_Int']))
            p_map = {}
            for _, r in group.iterrows():
                child = str(r['Clean_HU_Int'])
                parent = str(r['Clean_Parent'])
                if parent in ext_to_int: parent = ext_to_int[parent]
                p_map[child] = parent
            
            leaves = [h for h in group['Clean_HU_Int'] if h in valid_base_hus]
            roots = set()
            for leaf in leaves:
                curr = leaf
                visited = set()
                while curr in p_map and p_map[curr] != "" and curr not in visited:
                    visited.add(curr)
                    curr = p_map[curr]
                roots.add(curr)
            hu_agg_list.append({"Delivery": delivery, "hu_leaf": len(leaves), "hu_top_level": len(roots)})
        
        hu_agg = pd.DataFrame(hu_agg_list)
        pick_agg = df_pick.groupby("Delivery").agg(
            pocet_to=(queue_count_col, "nunique"), pohyby_celkem=("Pohyby_Rukou", "sum"), pocet_lokaci=("Source Storage Bin", "nunique"), hlavni_fronta=("Queue", "first"), pocet_mat=("Material", "nunique"), Month=("Month", "first")
        ).reset_index()

        billing_df = pd.merge(pick_agg, hu_agg, on="Delivery", how="left")

        def odvod_kategorii(row):
            kat = aus_category_map.get(row["Delivery"])
            if not kat:
                q = str(row.get('hlavni_fronta', '')).upper()
                if 'PI_PA_OE' in q: kat = "OE"
                elif 'PI_PA' in q: kat = "E"
                elif 'PI_PL_FUOE' in q or 'PI_PL_OE' in q: kat = "O"
                elif 'PI_PL' in q: kat = "N"
            art = "Sortenrein" if row.get('pocet_mat', 1) <= 1 else "Misch"
            return f"{kat} {art}" if kat else "Bez kategorie"

        billing_df["Category_Full"] = billing_df.apply(odvod_kategorii, axis=1)

        def urci_konecnou_hu(row):
            kat = str(row.get('Category_Full', '')).upper()
            if kat.startswith('E') or kat.startswith('OE'): return row.get('hu_leaf', 0)
            else: return row.get('hu_top_level', 0)

        billing_df['pocet_hu'] = billing_df.apply(urci_konecnou_hu, axis=1).fillna(0).astype(int)
        billing_df['TO_navic'] = (billing_df['pocet_to'] - billing_df['pocet_hu']).clip(lower=0).astype(int)
        
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
            # Volání izolovaného grafu
            render_interactive_chart(billing_df)

        st.markdown(f"### ⚠️ Ztráta z konsolidace (Práce zdarma / Prodělek)")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
            imb_disp.columns = ["Delivery", "Kategorie", "Pick TO celkem", "Pohyby rukou", "Účtované HU", "TO navíc (Rozdíl)"]
            st.dataframe(imb_disp, use_container_width=True, hide_index=True)
        else: st.success("Žádné zakázky s prodělkem nenalezeny!")
        
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
