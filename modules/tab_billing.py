import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import re
from modules.utils import t

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

# Normalizační funkce pro spolehlivé párování HU čísel
def normalize_hu(val):
    v = str(val).strip()
    if v.lower() in ['nan', 'none', '']: return ''
    v = re.sub(r'\.0$', '', v)  
    v = v.lstrip('0')           
    return v

@st.cache_data(show_spinner=False)
def cached_billing_logic(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, df_likp_tmp, df_sdshp_tmp, df_t031_tmp, txt_uncat):
    aus_category_map = {}
    kep_set = set()
    
    # 1. NAČTENÍ PŘEPRAVCŮ (KEP)
    if not df_sdshp_tmp.empty:
        col_s = df_sdshp_tmp.columns[0]
        col_k = next((c for c in df_sdshp_tmp.columns if "KEP" in str(c).upper() or "FÄHIG" in str(c).upper()), None)
        if col_k: 
            kep_set = set(df_sdshp_tmp.loc[df_sdshp_tmp[col_k].astype(str).str.strip().str.upper() == "X", col_s].astype(str).str.strip().str.lstrip('0'))
    
    order_type_map = {}
    if not df_t031_tmp.empty: 
        order_type_map = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))
    
    # 2. SESTAVENÍ MAPY ZÁKAZNICKÝCH KATEGORIÍ (Pokud je LIKP k dispozici)
    if not df_likp_tmp.empty:
        c_lief = df_likp_tmp.columns[0]
        c_vs = next((c for c in df_likp_tmp.columns if "Versandstelle" in str(c) or "Shipping" in str(c)), None)
        c_sped = next((c for c in df_likp_tmp.columns if "pediteur" in str(c).lower() or "transp" in str(c).lower()), None)
        
        for _, r in df_likp_tmp.iterrows():
            lief = str(r[c_lief]).strip().lstrip('0')
            vs = str(r[c_vs]).strip() if c_vs else "N"
            sped = str(r[c_sped]).strip().lstrip('0') if c_sped else ""
            o_type = order_type_map.get(vs, "N")
            
            is_kep = sped in kep_set
            
            # STRIKTNÍ ROZDĚLENÍ O a OE na základě přepravce
            if is_kep:
                aus_category_map[lief] = "OE" if o_type == "O" else "E"
            else:
                aus_category_map[lief] = "O" if o_type == "O" else "N"

    aus_full_cat_map = {}
    if df_cats is not None and not df_cats.empty:
        if "Lieferung" in df_cats.columns and "Category_Full" in df_cats.columns:
            aus_full_cat_map = dict(zip(df_cats["Lieferung"].astype(str).str.strip().str.lstrip('0'), df_cats["Category_Full"]))

    billing_df = pd.DataFrame()

    if df_vekp is None or df_vekp.empty:
        return billing_df

    df_pick_billing = df_pick.copy()
    df_pick_billing['Clean_Del'] = df_pick_billing['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')

    vekp_clean = df_vekp.dropna(subset=["Handling Unit", "Generated delivery"]).copy()
    vekp_clean['Clean_Del'] = vekp_clean['Generated delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    valid_deliveries = df_pick_billing["Clean_Del"].dropna().unique()
    vekp_filtered = vekp_clean[vekp_clean["Clean_Del"].isin(valid_deliveries)].copy()
    
    if vekp_filtered.empty:
        return billing_df

    vekp_hu_col = next((c for c in vekp_filtered.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_filtered.columns[0])
    vekp_ext_col = vekp_filtered.columns[1]
    parent_col_vepo = next((c for c in vekp_filtered.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
    
    vekp_filtered['Clean_HU_Int'] = vekp_filtered[vekp_hu_col].apply(normalize_hu)
    vekp_filtered['Clean_HU_Ext'] = vekp_filtered[vekp_ext_col].apply(normalize_hu)
    
    if parent_col_vepo:
        vekp_filtered['Clean_Parent'] = vekp_filtered[parent_col_vepo].apply(normalize_hu)
    else:
        vekp_filtered['Clean_Parent'] = ""

    # 3. MAPOVÁNÍ ROOT HUs Z VEKP (Všechny výsledné krabice a palety bez rodiče)
    root_df = vekp_filtered[vekp_filtered['Clean_Parent'] == '']
    
    del_to_roots = {}
    for d, grp in root_df.groupby('Clean_Del'):
        roots = []
        for _, r in grp.iterrows():
            roots.append({'int': r['Clean_HU_Int'], 'ext': r['Clean_HU_Ext']})
        del_to_roots[d] = roots

    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_pick_billing.columns else ('Type' if 'Type' in df_pick_billing.columns else None)
    
    def is_klt(v):
        v = str(v).upper().strip()
        return v in ['K1','K2','K3','K4','KLT','KLT1','KLT2'] or (v.startswith('K') and len(v) <= 2)

    pick_hu_cols = ['Handling Unit', 'Source storage unit', 'Source Storage Bin']
    
    # 4. IDENTIFIKACE VOLLPALET: Najdeme přesnou shodu Pick HU -> VEKP Root HU
    matched_root_hus_global = set()
    
    for _, pick_row in df_pick_billing.iterrows():
        if str(pick_row.get('Removal of total SU', '')).strip().upper() != 'X': continue
        if c_su and is_klt(pick_row.get(c_su, '')): continue

        d = str(pick_row['Clean_Del'])
        roots = del_to_roots.get(d, [])
        if not roots: continue

        for col in pick_hu_cols:
            if col in pick_row.index and pd.notna(pick_row[col]):
                val = normalize_hu(pick_row[col])
                if val:
                    for r in roots:
                        if val == r['int'] or val == r['ext']:
                            if r['int']: matched_root_hus_global.add(r['int'])
                            if r['ext']: matched_root_hus_global.add(r['ext'])

    # 5. OZNAČENÍ ŘÁDKŮ VE SKLADU (Rozštěpení zakázky na palety a zbytek)
    def assign_voll(pick_row):
        if str(pick_row.get('Removal of total SU', '')).strip().upper() != 'X': return False
        if c_su and is_klt(pick_row.get(c_su, '')): return False
        for col in pick_hu_cols:
            if col in pick_row.index and pd.notna(pick_row[col]):
                val = normalize_hu(pick_row[col])
                if val and val in matched_root_hus_global:
                    return True
        return False

    df_pick_billing['Is_Vollpalette'] = df_pick_billing.apply(assign_voll, axis=1)

    # Vypočteme "Base" (O/OE/N/E) pro každou zakázku hromadně
    del_base_map = {}
    for d, grp in df_pick_billing.groupby('Clean_Del'):
        base = aus_category_map.get(d)
        if not base:
            # ZÁCHRANNÁ BRZDA PODLE FRONTY (Pro měsíce bez LIKP)
            top_q = str(grp['Queue'].mode()[0]).upper() if not grp['Queue'].empty else ''
            if 'PI_PA_OE' in top_q: base = 'OE'
            elif 'PI_PA' in top_q: base = 'E'
            elif 'FUOE' in top_q or 'PI_PL_OE' in top_q: base = 'OE' # Pokud je queue OE, musíme věřit, že je to OE
            elif '_O' in top_q or 'FU_O' in top_q or 'FUO' in top_q: base = 'O'
            else: base = 'N'
        del_base_map[d] = base

    # Počet materiálů ve ZBYTKU zakázky (pro určení Misch vs Sortenrein u krabic)
    non_voll_mats = df_pick_billing[~df_pick_billing['Is_Vollpalette']].groupby('Clean_Del')['Material'].nunique().to_dict()

    # 6. KATEGORIZACE KAŽDÉHO ŘÁDKU ZVLÁŠŤ
    def get_full_category(row):
        d = str(row['Clean_Del'])
        base = del_base_map.get(d, "N")

        if row['Is_Vollpalette']:
            return f"{base} Vollpalette"
            
        mats = non_voll_mats.get(d, 1)
        return f"{base} Misch" if mats > 1 else f"{base} Sortenrein"

    df_pick_billing['Category_Full'] = df_pick_billing.apply(get_full_category, axis=1)

    # 7. ROZDĚLENÍ VYFAKTUROVANÝCH HU DO SPRÁVNÝCH KATEGORIÍ
    del_hu_counts = []
    for d, grp in root_df.groupby('Clean_Del'):
        voll_count = 0
        non_voll_count = 0
        for _, r in grp.iterrows():
            if (r['Clean_HU_Int'] in matched_root_hus_global) or (r['Clean_HU_Ext'] in matched_root_hus_global):
                voll_count += 1
            else:
                non_voll_count += 1
        
        if voll_count > 0:
            del_hu_counts.append({'Clean_Del': d, 'Is_Vollpalette': True, 'pocet_hu': voll_count})
        if non_voll_count > 0:
            del_hu_counts.append({'Clean_Del': d, 'Is_Vollpalette': False, 'pocet_hu': non_voll_count})

    df_hu_counts = pd.DataFrame(del_hu_counts)

    # 8. AGREGACE DLE ZAKÁZKY A JEJÍCH ČÁSTÍ
    pick_agg = df_pick_billing.groupby(['Delivery', 'Clean_Del', 'Category_Full', 'Is_Vollpalette']).agg(
        pocet_to=(queue_count_col, "nunique"),
        pohyby_celkem=("Pohyby_Rukou", "sum"),
        pocet_lokaci=("Source Storage Bin", "nunique"),
        Month=("Month", "first"),
        hlavni_fronta=("Queue", lambda x: x.mode()[0] if not x.empty else ""), # Přidáno pro Audit!
        pocet_mat=("Material", "nunique") # Přidáno pro Audit!
    ).reset_index()

    # Přiřazení vyfakturovaných HU
    def assign_hu_counts(row):
        d = row['Clean_Del']
        is_voll = row['Is_Vollpalette']
        if df_hu_counts.empty: return 0
        match = df_hu_counts[(df_hu_counts['Clean_Del'] == d) & (df_hu_counts['Is_Vollpalette'] == is_voll)]
        if not match.empty:
            return match.iloc[0]['pocet_hu']
        return 0

    pick_agg['pocet_hu'] = pick_agg.apply(assign_hu_counts, axis=1)

    # 9. FINÁLNÍ VÝPOČTY (A OPRAVA AUDITU)
    billing_df = pick_agg.copy()
    billing_df['Clean_Del_Merge'] = billing_df['Clean_Del'] # <-- OPRAVA PRO KEYERROR V AUDITU!
    
    billing_df['pocet_hu'] = billing_df['pocet_hu'].fillna(0).astype(int)
    billing_df["Bilance"] = (billing_df["pocet_to"] - billing_df["pocet_hu"]).astype(int)
    billing_df["TO_navic"] = billing_df["Bilance"].clip(lower=0)

    billing_df = billing_df.drop(columns=['Is_Vollpalette'])

    return billing_df

def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data):
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>💰 {_t('Korelace mezi Pickováním a Účtováním', 'Correlation Between Picking and Billing')}</h3><p>{_t('Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.', 'The customer pays based on the number of billed HUs. Here you can see the effort required to create these billed units across categories.')}</p></div>", unsafe_allow_html=True)

    df_likp_tmp = aus_data.get("LIKP", pd.DataFrame()) if aus_data else pd.DataFrame()
    df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame()) if aus_data else pd.DataFrame()
    df_t031_tmp = aus_data.get("T031", pd.DataFrame()) if aus_data else pd.DataFrame()
    txt_uncat = t("uncategorized")

    billing_df = cached_billing_logic(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, df_likp_tmp, df_sdshp_tmp, df_t031_tmp, txt_uncat)

    if not billing_df.empty:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True): 
                # Zobrazení SKUTEČNÉHO počtu unikátních zakázek, i když jsou teď rozdělené na více řádků
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
        
        st.divider()
        st.subheader(f"📊 {_t('Analýza zásilkových dat (Auswertung)', 'Shipment Data Analysis (Auswertung)')}")
        
        if not aus_data: 
            st.info(_t("Pro tuto sekci nahrajte zákazníkův soubor Auswertung_Outbound_HWL.xlsx", "Upload customer's file Auswertung_Outbound_HWL.xlsx for this section."))
        else:
            df_likp = aus_data.get("LIKP", pd.DataFrame())
            df_vekp2 = aus_data.get("VEKP", pd.DataFrame())
            df_vepo = aus_data.get("VEPO", pd.DataFrame())
            df_sdshp = aus_data.get("SDSHP_AM2", pd.DataFrame())
            
            kep_set = set()
            if not df_sdshp.empty:
                col_k = next((c for c in df_sdshp.columns if "KEP" in str(c).upper()), None)
                if col_k: 
                    kep_set = set(df_sdshp.loc[df_sdshp[col_k].astype(str).str.strip() == "X", df_sdshp.columns[0]].astype(str).str.strip().str.lstrip('0'))
            
            df_lf = pd.DataFrame()
            if not df_likp.empty:
                c_lief = df_likp.columns[0]
                c_vs = next((c for c in df_likp.columns if "Versandstelle" in str(c)), None)
                c_sped = next((c for c in df_likp.columns if "pediteur" in str(c).lower() or "transp" in str(c).lower()), None)
                
                df_lf = df_likp[[c_lief]].copy()
                df_lf.columns = ["Lieferung"]
                df_lf["Lieferung"] = df_lf["Lieferung"].astype(str).str.strip().str.lstrip('0')
                
                if c_sped:
                    sped_col = df_likp[c_sped].astype(str).str.strip().str.lstrip('0')
                    df_lf["is_KEP"] = sped_col.isin(kep_set)
                else:
                    df_lf["is_KEP"] = False
                
                if c_vs and not df_t031_tmp.empty:
                    order_type_map_aus = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))
                    df_lf["Order_Type"] = df_likp[c_vs].astype(str).str.strip().map(order_type_map_aus).fillna("N")
                else:
                    df_lf["Order_Type"] = "N"
                    
                df_lf["Kategorie"] = np.where(
                    df_lf["is_KEP"], 
                    np.where(df_lf["Order_Type"] == "O", "OE", "E"), 
                    np.where(df_lf["Order_Type"] == "O", "O", "N")
                )

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
                if "Gesamtgewicht" in df_vk.columns: 
                    df_vk["Gesamtgewicht"] = pd.to_numeric(df_vk["Gesamtgewicht"], errors="coerce").fillna(0)
                if not df_lf.empty and "Lieferung" in df_vk.columns:
                    df_vk["Lieferung"] = df_vk["Lieferung"].astype(str).str.strip().str.lstrip('0')
                    df_vk["Kategorie"] = df_vk["Lieferung"].map(df_lf.set_index("Lieferung")["Kategorie"]).fillna("N")

            st.markdown(f"### {_t('Kategorie zásilek', 'Shipment Categories')} (E / N / O / OE)")
            if not df_vk.empty and "Kategorie" in df_vk.columns:
                kat_grp = df_vk.groupby("Kategorie").agg(
                    pocet_lief=("Lieferung", "nunique") if "Lieferung" in df_vk.columns else ("HU_intern", "nunique"), 
                    celk_hu=("HU_intern", "nunique")
                ).reset_index()
                
                kat_grp["prumer_hu"] = kat_grp["celk_hu"] / kat_grp["pocet_lief"]
                kat_grp.columns = [
                    _t("Kategorie", "Category"), 
                    _t("Počet zakázek", "Orders"), 
                    _t("Celkem HU", "Total HU"), 
                    _t("Průměr HU/zak.", "Avg HU/Order")
                ]
                
                st.dataframe(kat_grp.style.format({_t("Průměr HU/zak.", "Avg HU/Order"): "{:.2f}"}), use_container_width=True, hide_index=True)

            st.markdown(f"### {_t('Typy krabic (Packmittel) — váhy', 'Box Types (Packmittel) — Weights')}")
            if not df_vk.empty and "Packmittel" in df_vk.columns:
                carton_agg = df_vk.groupby("Packmittel").agg(
                    pocet=("HU_intern", "nunique"), 
                    avg_gew=("Gesamtgewicht", "mean") if "Gesamtgewicht" in df_vk.columns else ("HU_intern", "count")
                ).reset_index().sort_values("pocet", ascending=False)
                
                carton_agg.columns = [
                    _t("Obal (Packmittel)", "Packaging"), 
                    _t("Počet HU", "HU Count"), 
                    _t("Průměrná váha", "Avg Weight")
                ]
                
                st.dataframe(carton_agg.style.format({_t("Průměrná váha", "Avg Weight"): "{:.2f} kg"}), use_container_width=True, hide_index=True)
                
            st.markdown(f"### {_t('Typy HU', 'HU Types')} (Sortenrein / Misch / Vollpalette)")
            if not df_vk.empty and "Art_HU" in df_vk.columns:
                art_celk = df_vk["Art_HU"].value_counts()
                ca1, ca2, ca3 = st.columns(3)
                with ca1:
                    with st.container(border=True): 
                        st.metric("📦 Sortenrein", f"{art_celk.get('Sortenrein', 0):,}")
                with ca2:
                    with st.container(border=True): 
                        st.metric("🔀 Misch", f"{art_celk.get('Misch', 0):,}")
                with ca3:
                    with st.container(border=True): 
                        st.metric("🏭 Vollpalette", f"{art_celk.get('Vollpalette', 0):,}")

    return billing_df
