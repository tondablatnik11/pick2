import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t, safe_hu, safe_del
from database import load_from_db

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

# Přejmenováno na v7 pro vynucení resetu cache a nasazení přesného HU-level mapování
@st.cache_data(show_spinner=False)
def cached_billing_logic_v7(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set):
    # ---------------------------------------------------------
    # 1. NAČTENÍ LIKP DAT A VYTVOŘENÍ MAPY ZÁKAZNÍKŮ (Export vs Normal)
    # ---------------------------------------------------------
    del_vs_map = {}
    df_likp = load_from_db('raw_likp')
    if df_likp is not None and not df_likp.empty:
        c_lief = next((c for c in df_likp.columns if "Delivery" in str(c) or "Lieferung" in str(c)), df_likp.columns[0])
        c_vs = next((c for c in df_likp.columns if "Shipping Point" in str(c) or "Versandstelle" in str(c) or "Receiving Pt" in str(c)), None)
        if c_vs:
            for _, r in df_likp.iterrows():
                lief = safe_del(r[c_lief])
                del_vs_map[lief] = str(r[c_vs]).strip().upper()

    billing_df = pd.DataFrame()
    if df_vekp is None or df_vekp.empty or df_pick is None or df_pick.empty: return billing_df

    # ---------------------------------------------------------
    # 2. PŘÍPRAVA DAT A ČIŠTĚNÍ ČÍSEL
    # ---------------------------------------------------------
    df_pick_billing = df_pick.copy()
    df_pick_billing['Clean_Del'] = df_pick_billing['Delivery'].apply(safe_del)

    vekp_clean = df_vekp.dropna(subset=["Handling Unit", "Generated delivery"]).copy()
    vekp_clean['Clean_Del'] = vekp_clean['Generated delivery'].apply(safe_del)
    valid_deliveries = df_pick_billing["Clean_Del"].dropna().unique()
    vekp_filtered = vekp_clean[vekp_clean["Clean_Del"].isin(valid_deliveries)].copy()
    if vekp_filtered.empty: return billing_df

    vekp_hu_col = next((c for c in vekp_filtered.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_filtered.columns[0])
    vekp_ext_col = vekp_filtered.columns[1]
    parent_col_vepo = next((c for c in vekp_filtered.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
    
    vekp_filtered['Clean_HU_Int'] = vekp_filtered[vekp_hu_col].apply(safe_hu)
    vekp_filtered['Clean_HU_Ext'] = vekp_filtered[vekp_ext_col].apply(safe_hu)
    vekp_filtered['Clean_Parent'] = vekp_filtered[parent_col_vepo].apply(safe_hu) if parent_col_vepo else ""

    # ---------------------------------------------------------
    # 3. OZNAČENÍ ŘÁDKŮ PICK REPORTU PODLE CENTRÁLNÍHO MOZKU
    # ---------------------------------------------------------
    def is_row_voll(row):
        d = row['Clean_Del']
        hu = safe_hu(row.get('Handling Unit', ''))
        if not hu: hu = safe_hu(row.get('Source storage unit', ''))
        return (d, hu) in voll_set

    df_pick_billing['Is_Vollpalette'] = df_pick_billing.apply(is_row_voll, axis=1)

    # ---------------------------------------------------------
    # 4. URČENÍ ZÁKLADNÍ KATEGORIE (N, O, E, OE) PŘES LIKP A FRONTY
    # ---------------------------------------------------------
    del_base_map = {}
    for d, grp in df_pick_billing.groupby('Clean_Del'):
        all_queues = " ".join(grp['Queue'].dropna().astype(str).str.upper().unique())
        vs = del_vs_map.get(d, "")
        
        if vs in ['FM22', 'FM23', 'FM24']: export = True
        elif vs in ['FM20', 'FM21']: export = False
        else: export = True if ('_O' in all_queues or 'FU_O' in all_queues or 'FUO' in all_queues) else False
                
        is_parcel = True if 'PI_PA' in all_queues else False
        del_base_map[d] = ("OE" if export else "E") if is_parcel else ("O" if export else "N")

    # ---------------------------------------------------------
    # 5. VEPO STROM A MAPOVÁNÍ MATERIÁLŮ PRO PŘESNÉ KATEGORIE HU
    # ---------------------------------------------------------
    vepo_mat_map = {}
    if df_vepo is not None and not df_vepo.empty:
        vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
        vepo_mat_col = next((c for c in df_vepo.columns if "Material" in str(c)), None)
        if vepo_mat_col:
            for _, r in df_vepo.dropna(subset=[vepo_hu_col, vepo_mat_col]).iterrows():
                h = safe_hu(r[vepo_hu_col])
                m = str(r[vepo_mat_col]).strip()
                if h not in vepo_mat_map:
                    vepo_mat_map[h] = set()
                vepo_mat_map[h].add(m)

    ext_to_int = dict(zip(vekp_filtered['Clean_HU_Ext'], vekp_filtered['Clean_HU_Int']))
    parent_map = {}
    for _, r in vekp_filtered.iterrows():
        child = r['Clean_HU_Int']
        parent = r['Clean_Parent']
        if parent in ext_to_int: 
            parent = ext_to_int[parent]
        parent_map[child] = parent

    children_map = {}
    for child, parent in parent_map.items():
        if parent:
            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append(child)

    def get_leaves(node):
        if node not in children_map: return [node]
        leaves = []
        for child in children_map[node]:
            leaves.extend(get_leaves(child))
        return leaves

    # ---------------------------------------------------------
    # 6. ROZŠTĚPENÍ VYFAKTUROVANÝCH HU DO KATEGORIÍ (Sortenrein vs Misch dle obsahu)
    # ---------------------------------------------------------
    del_hu_counts = []
    del_mat_cats = {} # Pomocná mapa (Zakázka, Materiál) -> Kategorie

    root_df = vekp_filtered[vekp_filtered['Clean_Parent'] == '']
    for d, grp in root_df.groupby('Clean_Del'):
        base = del_base_map.get(d, "N")

        for _, r in grp.iterrows():
            ext_hu = r['Clean_HU_Ext']
            int_hu = r['Clean_HU_Int']

            is_voll = (d, ext_hu) in voll_set or (d, int_hu) in voll_set

            if is_voll:
                cat = f"{base} Vollpalette"
                # Pojistka proti OE Vollpalette
                if base == "OE": cat = "O Vollpalette"
                if base == "E": cat = "N Vollpalette"
                
                del_hu_counts.append({'Clean_Del': d, 'Category_Full': cat, 'pocet_hu': 1})
                
                # Zaznamenání materiálů v této HU
                leaves = get_leaves(int_hu)
                for leaf in leaves:
                    for m in vepo_mat_map.get(leaf, set()):
                        if (d, m) not in del_mat_cats: del_mat_cats[(d, m)] = set()
                        del_mat_cats[(d, m)].add(cat)
            else:
                # Rozřazení na Sortenrein a Misch na základě fyzického obsahu
                leaves = get_leaves(int_hu)
                mats = set()
                for leaf in leaves:
                    if leaf in vepo_mat_map:
                        mats.update(vepo_mat_map[leaf])

                if len(mats) > 0: # Ignorujeme prázdné skořápky bez materiálů
                    cat = f"{base} Sortenrein" if len(mats) == 1 else f"{base} Misch"
                    
                    del_hu_counts.append({'Clean_Del': d, 'Category_Full': cat, 'pocet_hu': 1})

                    for m in mats:
                        if (d, m) not in del_mat_cats: del_mat_cats[(d, m)] = set()
                        del_mat_cats[(d, m)].add(cat)

    df_hu_counts = pd.DataFrame(del_hu_counts)
    if not df_hu_counts.empty:
        df_hu_counts = df_hu_counts.groupby(['Clean_Del', 'Category_Full']).size().reset_index(name='pocet_hu')
    else:
        df_hu_counts = pd.DataFrame(columns=['Clean_Del', 'Category_Full', 'pocet_hu'])

    # ---------------------------------------------------------
    # 7. KATEGORIZACE JEDNOTLIVÝCH TO (Mapování Picků na správné HU kategorie)
    # ---------------------------------------------------------
    non_voll_mats = df_pick_billing[~df_pick_billing['Is_Vollpalette']].groupby('Clean_Del')['Material'].nunique().to_dict()

    def get_full_category(row):
        d = row['Clean_Del']
        base = del_base_map.get(d, "N")

        if row['Is_Vollpalette']:
            if base == "OE": base = "O"
            if base == "E": base = "N"
            return f"{base} Vollpalette"
            
        mat = str(row.get('Material', '')).strip()
        cats = del_mat_cats.get((d, mat), set())
        
        # Očistíme od Vollpalette štítku, protože tento pick evidentně Vollpaleta není
        valid_cats = {c for c in cats if "Vollpalette" not in c}
        
        if len(valid_cats) == 1:
            return list(valid_cats)[0]
        elif len(valid_cats) > 1:
            return f"{base} Misch" # Pokud šel materiál do obojího, přiřazuje se do Misch
        else:
            # Záložní pravidlo, pokud se materiál nenapároval (např. smazán ve VEPO)
            mats_in_del = non_voll_mats.get(d, 1)
            return f"{base} Misch" if mats_in_del > 1 else f"{base} Sortenrein"

    df_pick_billing['Category_Full'] = df_pick_billing.apply(get_full_category, axis=1)

    # ---------------------------------------------------------
    # 8. AGREGACE DLE ZAKÁZKY A KATEGORIE
    # ---------------------------------------------------------
    pick_agg = df_pick_billing.groupby(['Clean_Del', 'Category_Full']).agg(
        pocet_to=(queue_count_col, "nunique"),
        pohyby_celkem=("Pohyby_Rukou", "sum"),
        pocet_lokaci=("Source Storage Bin", "nunique"),
        pocet_mat=("Material", "nunique") 
    ).reset_index()

    # Spojení fyzických picků s vyfakturovanými jednotkami pomocí OUTER JOIN
    billing_df = pd.merge(pick_agg, df_hu_counts, on=['Clean_Del', 'Category_Full'], how='outer')

    # Obnovení hlavičkových dat (Delivery, Měsíc) po outer joinu
    del_metadata = df_pick_billing.groupby('Clean_Del').agg(
        Delivery=('Delivery', 'first'),
        Month=('Month', 'first'),
        hlavni_fronta=("Queue", lambda x: x.mode()[0] if not x.empty else "")
    ).to_dict('index')

    billing_df['Delivery'] = billing_df.apply(lambda r: del_metadata.get(r['Clean_Del'], {}).get('Delivery', r['Clean_Del']) if pd.isna(r.get('Delivery')) else r['Delivery'], axis=1)
    billing_df['Month'] = billing_df.apply(lambda r: del_metadata.get(r['Clean_Del'], {}).get('Month', 'Neznámé') if pd.isna(r.get('Month')) else r['Month'], axis=1)
    billing_df['hlavni_fronta'] = billing_df.apply(lambda r: del_metadata.get(r['Clean_Del'], {}).get('hlavni_fronta', '') if pd.isna(r.get('hlavni_fronta')) else r['hlavni_fronta'], axis=1)

    # ---------------------------------------------------------
    # 9. FINÁLNÍ VÝPOČTY BILANCE
    # ---------------------------------------------------------
    for col in ['pocet_to', 'pohyby_celkem', 'pocet_lokaci', 'pocet_hu', 'pocet_mat']:
        billing_df[col] = billing_df[col].fillna(0).astype(int)

    billing_df['Clean_Del_Merge'] = billing_df['Clean_Del']
    billing_df["Bilance"] = (billing_df["pocet_to"] - billing_df["pocet_hu"]).astype(int)
    billing_df["TO_navic"] = billing_df["Bilance"].clip(lower=0)

    return billing_df


def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data=None):
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>💰 {_t('Korelace mezi Pickováním a Účtováním', 'Correlation Between Picking and Billing')}</h3><p>{_t('Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.', 'The customer pays based on the number of billed HUs. Here you can see the effort required to create these billed units across categories.')}</p></div>", unsafe_allow_html=True)

    # Natažení Centrálního Mozku z cache
    voll_set = st.session_state.get('voll_set', set())
    
    # Volání analýzy v7
    billing_df = cached_billing_logic_v7(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, voll_set)

    if load_from_db('raw_likp') is None:
        st.warning("⚠️ **Info:** Pro 100% přesné oddělení N a O zakázek doporučujeme v Admin Zóně nahrát LIKP report. Nyní systém pro určení exportu odhaduje data na základě Fronty (Queue).")

    if not billing_df.empty:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True): 
                st.metric(_t("Zakázek celkem", "Total Orders"), f"{billing_df['Delivery'].nunique():,}")
        with c2:
            with st.container(border=True): 
                st.metric(_t("Fakturované palety/krabice (HU)", "Billed Pallets/Boxes (HU)"), f"{int(billing_df['pocet_hu'].sum()):,}")
        with c3:
            with st.container(border=True): 
                st.metric(_t("Fyzických Pick TO", "Physical Pick TOs"), f"{int(billing_df['pocet_to'].sum()):,}")
        with c4:
            net_diff = int(billing_df['Bilance'].sum())
            loss_total = int(billing_df['TO_navic'].sum())
            profit_total = loss_total - net_diff
            with st.container(border=True): 
                st.metric(
                    _t("Celková čistá bilance (TO - HU)", "Total Net Balance (TO - HU)"), 
                    f"{net_diff:,}", 
                    help=_t(f"Kladné číslo = Prodělek. Ztráta z nevýhodných zakázek byla {loss_total:,} picků, ale efektivní zakázky vám uspořily {profit_total:,} picků.", f"Positive number = Loss. Loss from inefficient orders was {loss_total:,} picks, but efficient orders saved {profit_total:,} picks.")
                )

        st.divider()
        col_t1, col_t2 = st.columns([1.2, 1])
        with col_t1:
            st.markdown(f"**{_t('Souhrn podle kategorií zabalených HU (Zisky a Ztráty)', 'Summary by Packed HU Categories (Profit & Loss)')}**")
            
            cat_sum = billing_df.groupby("Category_Full").agg(
                pocet_casti=("Delivery", "count"), 
                pocet_to=("pocet_to", "sum"), 
                pocet_hu=("pocet_hu", "sum"), 
                pocet_lok=("pocet_lokaci", "sum"), 
                poh=("pohyby_celkem", "sum"), 
                bilance=("Bilance", "sum"), 
                to_navic=("TO_navic", "sum")
            ).reset_index()
            
            cat_sum["prum_poh"] = np.where(cat_sum["pocet_lok"] > 0, cat_sum["poh"] / cat_sum["pocet_lok"], 0)
            
            disp = cat_sum[["Category_Full", "pocet_casti", "pocet_to", "pocet_hu", "prum_poh", "bilance", "to_navic"]].copy()
            disp.columns = [
                _t("Kategorie HU", "HU Category"), 
                _t("Části zakázek", "Order Parts"), 
                _t("Počet TO", "Total TO"), 
                _t("Zúčtované HU", "Billed HU"), 
                _t("Prům. pohybů na lokaci", "Avg Moves/Location"), 
                _t("Čistá bilance (Zisk/Ztráta)", "Net Balance (Profit/Loss)"), 
                _t("Hrubá ztráta (TO navíc)", "Gross Loss (Extra TO)")
            ]
            
            st.dataframe(disp.style.format({_t("Prům. pohybů na lokaci", "Avg Moves/Location"): "{:.1f}"}), use_container_width=True, hide_index=True)
            
            st.markdown(f"<br>**🔍 {_t('Detailní seznam částí zakázek podle kategorie:', 'Detailed Order Parts List by Category:')}**", unsafe_allow_html=True)
            cat_opts = [_t("— Vyberte kategorii pro detail —", "— Select Category for Detail —")] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
            sel_detail_cat = st.selectbox("Vyberte", options=cat_opts, label_visibility="collapsed")
            
            if sel_detail_cat != _t("— Vyberte kategorii pro detail —", "— Select Category for Detail —"):
                det_df = billing_df[billing_df["Category_Full"] == sel_detail_cat].copy()
                det_df["prum_poh_lok"] = np.where(det_df["pocet_lokaci"] > 0, det_df["pohyby_celkem"] / det_df["pocet_lokaci"], 0)
                det_df = det_df.sort_values(by="Bilance", ascending=False)
                
                disp_det = det_df[["Delivery", "pocet_to", "pocet_hu", "prum_poh_lok", "Bilance"]].copy()
                disp_det.columns = [
                    _t("Zakázka (Delivery)", "Order (Delivery)"), 
                    _t("Počet TO", "Total TO"), 
                    _t("Zabalené HU", "Packed HU"), 
                    _t("Prům. pohybů na lok.", "Avg Moves/Loc"), 
                    _t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")
                ]
                
                def color_bilance_simple(val):
                    try:
                        if val > 0: return 'color: #ef4444; font-weight: bold'
                        elif val < 0: return 'color: #10b981; font-weight: bold'
                    except: pass
                    return ''

                try:
                    styled_det = disp_det.style.format({_t("Prům. pohybů na lok.", "Avg Moves/Loc"): "{:.1f}"}).map(color_bilance_simple, subset=[_t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")])
                except AttributeError:
                    styled_det = disp_det.style.format({_t("Prům. pohybů na lok.", "Avg Moves/Loc"): "{:.1f}"}).applymap(color_bilance_simple, subset=[_t("Čistá bilance (TO navíc)", "Net Balance (Extra TO)")])
                
                st.dataframe(styled_det, use_container_width=True, hide_index=True)

        with col_t2:
            st.markdown(f"**{_t('Trend v čase (Měsíce)', 'Trend over Time (Months)')}**")
            @fast_render
            def interactive_chart():
                cat_options = [_t("Všechny kategorie", "All Categories")] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
                selected_cat = st.selectbox(_t("Vyberte kategorii pro graf:", "Select category for chart:"), options=cat_options, label_visibility="collapsed", key="billing_chart_cat")
                
                if selected_cat == _t("Všechny kategorie", "All Categories"):
                    plot_df = billing_df.copy()
                else:
                    plot_df = billing_df[billing_df["Category_Full"] == selected_cat].copy()
                
                tr_df = plot_df.groupby("Month").agg(
                    to_sum=("pocet_to", "sum"), 
                    hu_sum=("pocet_hu", "sum"), 
                    poh=("pohyby_celkem", "sum"), 
                    lok=("pocet_lokaci", "sum")
                ).reset_index()
                
                tr_df['prum_poh'] = np.where(tr_df['lok']>0, tr_df['poh']/tr_df['lok'], 0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=tr_df['Month'], 
                    y=tr_df['to_sum'], 
                    name=_t('Počet TO', 'Total TOs'), 
                    marker_color='#38bdf8', 
                    text=tr_df['to_sum'], 
                    textposition='auto'
                ))
                fig.add_trace(go.Bar(
                    x=tr_df['Month'], 
                    y=tr_df['hu_sum'], 
                    name=_t('Počet HU', 'Total HUs'), 
                    marker_color='#818cf8', 
                    text=tr_df['hu_sum'], 
                    textposition='auto'
                ))
                fig.add_trace(go.Scatter(
                    x=tr_df['Month'], 
                    y=tr_df['prum_poh'], 
                    name=_t('Pohyby na lokaci', 'Moves per Loc'), 
                    yaxis='y2', 
                    mode='lines+markers+text', 
                    text=tr_df['prum_poh'].round(1), 
                    textposition='top center', 
                    textfont=dict(color='#f43f5e'), 
                    line=dict(color='#f43f5e', width=3)
                ))
                
                fig.update_layout(
                    yaxis2=dict(title=_t("Pohyby", "Moves"), side="right", overlaying="y", showgrid=False), 
                    plot_bgcolor="rgba(0,0,0,0)", 
                    paper_bgcolor="rgba(0,0,0,0)", 
                    margin=dict(l=0, r=0, t=30, b=0), 
                    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
                )
                st.plotly_chart(fig, use_container_width=True)
            
            interactive_chart()

        st.divider()
        st.markdown(f"### 💎 {_t('Analýza efektivity a ziskovosti (Master Data)', 'Efficiency & Profitability Analysis (Master Data)')}")
        st.markdown(_t("Tato tabulka odhaluje skutečnou hloubku finančních úniků z konsolidace a fyzickou náročnost na 1 fakturační jednotku.", "This table reveals the true depth of financial leaks from consolidation and the physical effort per 1 billed unit."))
        
        with st.expander(f"📖 {_t('Vysvětlení výpočtů ve sloupcích', 'Explanation of Column Calculations')}"):
            st.markdown(_t("""
            * **Index konsolidace (TO/HU):** Kolik pickovacích úkolů (TO) musí skladník průměrně udělat na vytvoření 1 vyfakturované jednotky (HU). Ideál je 1.0. Čím vyšší číslo, tím více TO se "slévá" a ztrácí.
            * **Fyzické pohyby na 1 Billed HU:** Kolik reálných pohybů rukou (přeložení kusů) stojí firmu vytvoření 1 vyfakturované jednotky.
            * **1:1 (Ideál):** Počet zakázek, kde se 1 vychystané TO rovná přesně 1 vyfakturované HU (žádná ztráta z konsolidace).
            * **Více TO (Prodělaly) / Ztráta (ks TO):** Zakázky, u kterých se více picků spojilo do menšího počtu palet/krabic. Sloupec Ztráta ukazuje *přesný počet TO*, které jste fyzicky odchodili, ale zákazník je nezaplatil.
            * **Více HU (Vydělaly) / Zisk (ks HU):** Zakázky, u kterých se 1 pick rozpadl do více menších balení. Sloupec Zisk ukazuje, kolik HU jste vyfakturovali *navíc*.
            * **Čistá bilance (HU - TO):** Celkový výsledek kategorie v kusech. Zelená = zisk. Červená = ztráta.
            """, """
            * **Consolidation Index (TO/HU):** How many pick tasks (TO) a worker averages to create 1 billed unit (HU). Ideal is 1.0. Higher = more TOs are consolidated and "lost".
            * **Physical Moves per Billed HU:** How many real hand moves it costs to create 1 billed unit.
            * **1:1 (Ideal):** Orders where 1 picked TO equals exactly 1 billed HU (no consolidation loss).
            * **More TO (Loss) / Loss (pcs TO):** Orders where multiple picks merged into fewer units. The Loss column shows *exact TO count* physically walked but unpaid.
            * **More HU (Profit) / Profit (pcs HU):** Orders where 1 pick split into multiple billed units. The Profit column shows *extra* billed HUs.
            * **Net Balance (HU - TO):** Total category result. Green = profit. Red = loss.
            """))
        
        billing_df['is_1_to_1'] = (billing_df['pocet_to'] == billing_df['pocet_hu']).astype(int)
        billing_df['is_more_to'] = (billing_df['pocet_to'] > billing_df['pocet_hu']).astype(int)
        billing_df['is_more_hu'] = (billing_df['pocet_to'] < billing_df['pocet_hu']).astype(int)
        
        billing_df['ztrata_to'] = np.where(billing_df['is_more_to'], billing_df['pocet_to'] - billing_df['pocet_hu'], 0)
        billing_df['zisk_hu'] = np.where(billing_df['is_more_hu'], billing_df['pocet_hu'] - billing_df['pocet_to'], 0)
        
        ratio_table = billing_df.groupby('Category_Full').agg(
            celkem=('Delivery', 'count'), 
            to_celkem=('pocet_to', 'sum'), 
            hu_celkem=('pocet_hu', 'sum'), 
            pohyby_celkem=('pohyby_celkem', 'sum'), 
            count_1_1=('is_1_to_1', 'sum'), 
            count_more_to=('is_more_to', 'sum'), 
            ztrata_to=('ztrata_to', 'sum'), 
            count_more_hu=('is_more_hu', 'sum'), 
            zisk_hu=('zisk_hu', 'sum')
        ).reset_index()
        
        def format_pct(count, total):
            if total == 0: return "0 (0.0%)"
            return f"{int(count)} ({(count/total*100):.1f}%)"
        
        ratio_table['1:1 (Ideál)'] = ratio_table.apply(lambda r: format_pct(r['count_1_1'], r['celkem']), axis=1)
        ratio_table['Více TO (Počet)'] = ratio_table.apply(lambda r: format_pct(r['count_more_to'], r['celkem']), axis=1)
        ratio_table['Více HU (Počet)'] = ratio_table.apply(lambda r: format_pct(r['count_more_hu'], r['celkem']), axis=1)
        
        ratio_table['Index (TO na 1 HU)'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['to_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Pohyby na 1 HU'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['pohyby_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Čistá bilance'] = ratio_table['hu_celkem'] - ratio_table['to_celkem'] 
        
        disp_ratio = ratio_table[[
            'Category_Full', 'celkem', 'to_celkem', 'hu_celkem', 
            'Index (TO na 1 HU)', 'Pohyby na 1 HU', 
            '1:1 (Ideál)', 'Více TO (Počet)', 'ztrata_to', 
            'Více HU (Počet)', 'zisk_hu', 'Čistá bilance'
        ]].copy()
        
        disp_ratio.columns = [
            _t("Kategorie HU", "HU Category"), 
            _t("Částí zakázek", "Order Parts"), 
            _t("TO Celkem", "Total TO"), 
            _t("HU Celkem", "Total HU"), 
            _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"), 
            _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"), 
            _t("1:1 (Ideál)", "1:1 (Ideal)"), 
            _t("Více TO (Prodělaly)", "More TO (Loss)"), 
            _t("Ztráta (ks TO)", "Loss (pcs TO)"), 
            _t("Více HU (Vydělaly)", "More HU (Profit)"), 
            _t("Zisk (ks HU)", "Profit (pcs HU)"), 
            _t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")
        ]
        
        def style_master_table(val):
            try:
                if isinstance(val, (int, float)) and val > 0 and 'Ztráta' not in str(val) and 'Loss' not in str(val):
                    return 'color: #10b981; font-weight: bold'
                elif isinstance(val, (int, float)) and val < 0:
                    return 'color: #ef4444; font-weight: bold'
            except: pass
            return ''
            
        try:
            styled_master = disp_ratio.style.format({
                _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO", 
                _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"): "{:.1f} " + _t("pohybů", "moves"),
                _t("Ztráta (ks TO)", "Loss (pcs TO)"): "- {}",
                _t("Zisk (ks HU)", "Profit (pcs HU)"): "+ {}"
            }).map(style_master_table, subset=[_t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])
        except AttributeError:
            styled_master = disp_ratio.style.format({
                _t("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO", 
                _t("Fyzické pohyby na 1 Billed HU", "Physical Moves / Billed HU"): "{:.1f} " + _t("pohybů", "moves"),
                _t("Ztráta (ks TO)", "Loss (pcs TO)"): "- {}",
                _t("Zisk (ks HU)", "Profit (pcs HU)"): "+ {}"
            }).applymap(style_master_table, subset=[_t("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])
        
        st.dataframe(styled_master, use_container_width=True, hide_index=True)
            
        st.markdown(f"<br>**{_t('Trend typů zakázek (Měsíce)', 'Trend of Order Types (Months)')}**", unsafe_allow_html=True)
        
        all_trend_cats = sorted(billing_df['Category_Full'].dropna().unique().tolist())
        sel_trend_cats = st.multiselect(
            _t("Vyberte kategorie pro zobrazení trendu:", "Select categories for trend chart:"), 
            options=all_trend_cats, 
            default=all_trend_cats, 
            key="trend_ratio_cats"
        )
        
        if sel_trend_cats:
            trend_df_filtered = billing_df[billing_df['Category_Full'].isin(sel_trend_cats)].copy()
            trend_ratio = trend_df_filtered.groupby('Month').agg(
                count_1_1=('is_1_to_1', 'sum'), 
                count_more_to=('is_more_to', 'sum'), 
                count_more_hu=('is_more_hu', 'sum')
            ).reset_index()
            
            trend_ratio['total'] = trend_ratio['count_1_1'] + trend_ratio['count_more_to'] + trend_ratio['count_more_hu']
            trend_ratio['pct_1_1'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_1_1'] / trend_ratio['total'] * 100, 0)
            trend_ratio['pct_more_to'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_to'] / trend_ratio['total'] * 100, 0)
            trend_ratio['pct_more_hu'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_hu'] / trend_ratio['total'] * 100, 0)
            
            fig_r = go.Figure()
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_1_1'], 
                name=_t('1:1 (Kusy)', '1:1 (Pcs)'), 
                marker_color='rgba(16, 185, 129, 0.5)', 
                text=trend_ratio['count_1_1'], 
                textposition='inside', 
                yaxis='y'
            ))
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_more_hu'], 
                name=_t('Více HU (Kusy)', 'More HU (Pcs)'), 
                marker_color='rgba(59, 130, 246, 0.5)', 
                text=trend_ratio['count_more_hu'], 
                textposition='inside', 
                yaxis='y'
            ))
            fig_r.add_trace(go.Bar(
                x=trend_ratio['Month'], 
                y=trend_ratio['count_more_to'], 
                name=_t('Více TO (Kusy)', 'More TO (Pcs)'), 
                marker_color='rgba(239, 68, 68, 0.5)', 
                text=trend_ratio['count_more_to'], 
                textposition='inside', 
                yaxis='y'
            ))
            
            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_1_1'], 
                name=_t('1:1 (%)', '1:1 (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_1_1'].round(1).astype(str) + '%', 
                textposition='top center', 
                marker_color='#10b981', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_more_hu'], 
                name=_t('Více HU (%)', 'More HU (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_more_hu'].round(1).astype(str) + '%', 
                textposition='top center', 
                marker_color='#3b82f6', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            fig_r.add_trace(go.Scatter(
                x=trend_ratio['Month'], 
                y=trend_ratio['pct_more_to'], 
                name=_t('Více TO (%)', 'More TO (%)'), 
                mode='lines+markers+text', 
                text=trend_ratio['pct_more_to'].round(1).astype(str) + '%', 
                textposition='bottom center', 
                marker_color='#ef4444', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            
            fig_r.update_layout(
                barmode='stack', 
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)", 
                margin=dict(l=0, r=0, t=30, b=0), 
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
                yaxis=dict(title=_t("Celkem částí zakázek", "Total Order Parts")),
                yaxis2=dict(title=_t("Podíl zakázek (%)", "Order Share (%)"), side="right", overlaying="y", showgrid=False, range=[0, 110])
            )
            st.plotly_chart(fig_r, use_container_width=True)
        else: 
            st.info(_t("Zvolte alespoň jednu kategorii pro zobrazení grafu.", "Select at least one category to display the chart."))

        st.divider()
        st.markdown(f"### ⚠️ {_t('Žebříček neefektivity z konsolidace (Práce zdarma)', 'Inefficiency Ranking from Consolidation (Free Labor)')}")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
        
        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
            imb_disp.columns = [
                _t("Delivery", "Delivery"), 
                _t("Kategorie", "Category"), 
                _t("Pick TO celkem", "Total Pick TOs"), 
                _t("Pohyby rukou", "Hand Moves"), 
                _t("Účtované HU", "Billed HU"), 
                _t("Prodělek (Rozdíl)", "Loss (Difference)")
            ]
            st.dataframe(imb_disp, use_container_width=True, hide_index=True)
        else: 
            st.success(_t("Žádné zakázky s prodělkem nenalezeny!", "No loss-making orders found!"))

    return billing_df
