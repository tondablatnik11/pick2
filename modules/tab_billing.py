import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@st.cache_data(show_spinner=False)
def cached_billing_logic(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, df_likp_tmp, df_sdshp_tmp, df_t031_tmp, txt_uncat):
    aus_category_map = {}
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
        
        for _, r in df_likp_tmp.iterrows():
            lief = str(r[c_lief]).strip().lstrip('0')
            vs = str(r[c_vs]).strip() if c_vs else "N"
            sped = str(r[c_sped]).strip().lstrip('0') if c_sped else ""
            o_type = order_type_map.get(vs, "N")
            is_kep = sped in kep_set
            aus_category_map[lief] = "OE" if o_type == "O" else "E" if is_kep else ("O" if o_type == "O" else "N")

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
    
    vekp_filtered['Clean_HU_Int'] = vekp_filtered[vekp_hu_col].astype(str).str.strip().str.lstrip('0')
    vekp_filtered['Clean_HU_Ext'] = vekp_filtered[vekp_ext_col].astype(str).str.strip().str.lstrip('0')
    
    if parent_col_vepo:
        vekp_filtered['Clean_Parent'] = vekp_filtered[parent_col_vepo].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
        vekp_filtered.loc[vekp_filtered['Clean_Parent'].str.lower().isin(['nan', 'none', '']), 'Clean_Parent'] = ""
    else:
        vekp_filtered['Clean_Parent'] = ""

    valid_base_hus = set()
    vepo_hus_strict = set()
    if df_vepo is not None and not df_vepo.empty:
        vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
        vepo_lower_col = next((c for c in df_vepo.columns if "Lower-level" in str(c) or "untergeordn" in str(c).lower()), None)
        valid_base_hus = set(df_vepo[vepo_hu_col].astype(str).str.strip().str.lstrip('0'))
        vepo_hus_strict = set(df_vepo[vepo_hu_col].astype(str).str.strip().str.lstrip('0'))
        if vepo_lower_col:
            valid_base_hus.update(set(df_vepo[vepo_lower_col].dropna().astype(str).str.strip().str.lstrip('0')))
    else:
        valid_base_hus = set(vekp_filtered['Clean_HU_Int'])

    del_to_valid_hus = {}
    for d, grp in vekp_filtered.groupby('Clean_Del'):
        v = set()
        for _, r in grp.iterrows():
            hi = r['Clean_HU_Int']
            he = r['Clean_HU_Ext']
            if not vepo_hus_strict or hi in vepo_hus_strict:
                v.add(hi); v.add(he)
        del_to_valid_hus[d] = v

    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_pick_billing.columns else ('Type' if 'Type' in df_pick_billing.columns else None)
    def is_klt(v):
        v = str(v).upper().strip()
        return v in ['K1','K2','K3','K4','KLT','KLT1','KLT2'] or (v.startswith('K') and len(v) <= 2)

    pick_hu_cols = ['Source storage unit', 'Source Storage Bin', 'Handling Unit']
    
    def detect_voll(row):
        if str(row.get('Removal of total SU', '')).upper() != 'X': return False
        if c_su and is_klt(row.get(c_su, '')): return False 
        valid_hus = del_to_valid_hus.get(row['Clean_Del'], set())
        for col in pick_hu_cols:
            if col in row.index and pd.notna(row[col]):
                val = str(row[col]).strip().lstrip('0')
                if val and val in valid_hus: return True
        return False

    df_pick_billing['Is_Vollpalette'] = df_pick_billing.apply(detect_voll, axis=1)

    auto_voll_hus_clean = set()
    for _, r in df_pick_billing[df_pick_billing['Is_Vollpalette']].iterrows():
        for c in pick_hu_cols:
            if c in r.index and pd.notna(r[c]):
                val = str(r[c]).strip().lstrip('0')
                if val: auto_voll_hus_clean.add(val)

    hu_agg_list = []
    for delivery, group in vekp_filtered.groupby("Clean_Del"):
        ext_to_int = dict(zip(group['Clean_HU_Ext'], group['Clean_HU_Int']))
        
        p_map = {}
        for _, r in group.iterrows():
            child = str(r['Clean_HU_Int'])
            parent = str(r['Clean_Parent'])
            if parent in ext_to_int: 
                parent = ext_to_int[parent]
            p_map[child] = parent 
            
        leaves = [h for h in group['Clean_HU_Int'] if h in valid_base_hus]
        roots = set()
        voll_count = 0
        
        for leaf in leaves:
            leaf_exts = group.loc[group['Clean_HU_Int'] == leaf, 'Clean_HU_Ext'].values
            leaf_ext = leaf_exts[0] if len(leaf_exts) > 0 else ""
            
            if leaf in auto_voll_hus_clean or leaf_ext in auto_voll_hus_clean:
                voll_count += 1
            else:
                curr = leaf
                visited = set()
                while curr in p_map and p_map[curr] != "" and curr not in visited:
                    visited.add(curr)
                    curr = p_map[curr]
                roots.add(curr)
                
        orig_del = group["Generated delivery"].iloc[0]
        hu_agg_list.append({"Generated delivery": orig_del, "hu_leaf": len(leaves), "hu_top_level": len(roots) + voll_count, "Clean_Del_Merge": delivery})
        
    hu_agg = pd.DataFrame(hu_agg_list)
    if hu_agg.empty:
        hu_agg = pd.DataFrame(columns=["Generated delivery", "hu_leaf", "hu_top_level", "Clean_Del_Merge"])

    pick_agg = df_pick_billing.groupby("Delivery").agg(
        pocet_to=(queue_count_col, "nunique"),
        pohyby_celkem=("Pohyby_Rukou", "sum"),
        pocet_lokaci=("Source Storage Bin", "nunique"),
        hlavni_fronta=("Queue", "first"),
        pocet_mat=("Material", "nunique"),
        has_voll=("Is_Vollpalette", "any"),
        Clean_Del_Merge=("Clean_Del", "first"),
        Month=("Month", "first")
    ).reset_index()

    billing_df = pd.merge(pick_agg, hu_agg, on="Clean_Del_Merge", how="left")

    if df_cats is not None and not df_cats.empty:
        billing_df = pd.merge(billing_df, df_cats[["Lieferung", "Category_Full"]], left_on="Delivery", right_on="Lieferung", how="left")
    else:
        billing_df["Category_Full"] = pd.NA

    def odvod_kategorii(row):
        cat_full = row.get('Category_Full')
        if pd.notna(cat_full) and str(cat_full).strip() not in ["", "nan", txt_uncat]: return cat_full
        
        deliv = str(row["Delivery"]).strip().lstrip('0')
        base = aus_category_map.get(deliv)
        if not base:
            q = str(row.get('hlavni_fronta', '')).upper()
            base = "OE" if 'PI_PA_OE' in q else "E" if 'PI_PA' in q else "O" if ('PI_PL_FUOE' in q or 'PI_PL_OE' in q) else "N" if 'PI_PL' in q else "N"
            
        if base in ['N', 'O'] and row['has_voll']:
            sub = "Vollpalette"
        else:
            sub = "Misch" if row['pocet_mat'] > 1 else "Sortenrein"
            
        return f"{base} {sub}"

    billing_df["Category_Full"] = billing_df.apply(odvod_kategorii, axis=1)

    def urci_konecnou_hu(row):
        return row.get('hu_top_level', 0)

    billing_df["pocet_hu"] = billing_df.apply(urci_konecnou_hu, axis=1).fillna(0).astype(int)
    billing_df["Bilance"] = (billing_df["pocet_to"] - billing_df["pocet_hu"]).astype(int)
    billing_df["TO_navic"] = billing_df["Bilance"].clip(lower=0)

    return billing_df

def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data):
    st.markdown(f"<div class='section-header'><h3>💰 Korelace mezi Pickováním a Účtováním</h3><p>Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.</p></div>", unsafe_allow_html=True)

    df_likp_tmp = aus_data.get("LIKP", pd.DataFrame()) if aus_data else pd.DataFrame()
    df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame()) if aus_data else pd.DataFrame()
    df_t031_tmp = aus_data.get("T031", pd.DataFrame()) if aus_data else pd.DataFrame()
    txt_uncat = t("uncategorized")

    billing_df = cached_billing_logic(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, df_likp_tmp, df_sdshp_tmp, df_t031_tmp, txt_uncat)

    if not billing_df.empty:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            with st.container(border=True): st.metric("Zakázek celkem", f"{len(billing_df):,}")
        with c2:
            with st.container(border=True): st.metric("Fakturované palety/krabice (HU)", f"{int(billing_df['pocet_hu'].sum()):,}")
        with c3:
            with st.container(border=True): st.metric("Fyzických Pick TO", f"{int(billing_df['pocet_to'].sum()):,}")
        with c4:
            net_diff = int(billing_df['Bilance'].sum())
            loss_total = int(billing_df['TO_navic'].sum())
            profit_total = loss_total - net_diff
            with st.container(border=True): 
                st.metric("Celková čistá bilance (TO - HU)", f"{net_diff:,}", help=f"Kladné číslo = Prodělek. Ztráta z nevýhodných zakázek byla {loss_total:,} picků, ale efektivní zakázky vám uspořily {profit_total:,} picků.")

        st.divider()
        col_t1, col_t2 = st.columns([1.2, 1])
        with col_t1:
            st.markdown("**Souhrn podle kategorií (Zisky a Ztráty)**")
            cat_sum = billing_df.groupby("Category_Full").agg(
                pocet_zakazek=("Delivery", "nunique"), pocet_to=("pocet_to", "sum"), pocet_hu=("pocet_hu", "sum"), pocet_lok=("pocet_lokaci", "sum"), poh=("pohyby_celkem", "sum"), bilance=("Bilance", "sum"), to_navic=("TO_navic", "sum")
            ).reset_index()
            cat_sum["prum_poh"] = np.where(cat_sum["pocet_lok"] > 0, cat_sum["poh"] / cat_sum["pocet_lok"], 0)
            disp = cat_sum[["Category_Full", "pocet_zakazek", "pocet_to", "pocet_hu", "prum_poh", "bilance", "to_navic"]].copy()
            disp.columns = ["Kategorie", "Počet zakázek", "Počet TO", "Zúčtované HU", "Prům. pohybů na lokaci", "Čistá bilance (Zisk/Ztráta)", "Hrubá ztráta (TO navíc)"]
            st.dataframe(disp.style.format({"Prům. pohybů na lokaci": "{:.1f}"}), use_container_width=True, hide_index=True)
            
            st.markdown("<br>**🔍 Detailní seznam zakázek podle kategorie:**", unsafe_allow_html=True)
            cat_opts = ["— Vyberte kategorii pro detail —"] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
            sel_detail_cat = st.selectbox("Vyberte", options=cat_opts, label_visibility="collapsed")
            
            if sel_detail_cat != "— Vyberte kategorii pro detail —":
                det_df = billing_df[billing_df["Category_Full"] == sel_detail_cat].copy()
                det_df["prum_poh_lok"] = np.where(det_df["pocet_lokaci"] > 0, det_df["pohyby_celkem"] / det_df["pocet_lokaci"], 0)
                det_df = det_df.sort_values(by="Bilance", ascending=False)
                
                disp_det = det_df[["Delivery", "pocet_to", "pocet_hu", "prum_poh_lok", "Bilance"]].copy()
                disp_det.columns = ["Zakázka (Delivery)", "Počet TO", "Zabalené HU", "Prům. pohybů na lok.", "Čistá bilance (TO navíc)"]
                
                def color_bilance_simple(val):
                    try:
                        if val > 0: return 'color: #ef4444; font-weight: bold'
                        elif val < 0: return 'color: #10b981; font-weight: bold'
                    except: pass
                    return ''

                try:
                    styled_det = disp_det.style.format({"Prům. pohybů na lok.": "{:.1f}"}).map(color_bilance_simple, subset=["Čistá bilance (TO navíc)"])
                except AttributeError:
                    styled_det = disp_det.style.format({"Prům. pohybů na lok.": "{:.1f}"}).applymap(color_bilance_simple, subset=["Čistá bilance (TO navíc)"])
                
                st.dataframe(styled_det, use_container_width=True, hide_index=True)

        with col_t2:
            st.markdown("**Trend v čase (Měsíce)**")
            @fast_render
            def interactive_chart():
                cat_options = ["Všechny kategorie"] + sorted(billing_df["Category_Full"].dropna().unique().tolist())
                selected_cat = st.selectbox("Vyberte kategorii pro graf:", options=cat_options, label_visibility="collapsed", key="billing_chart_cat")
                
                plot_df = billing_df.copy() if selected_cat == "Všechny kategorie" else billing_df[billing_df["Category_Full"] == selected_cat].copy()
                
                tr_df = plot_df.groupby("Month").agg(to_sum=("pocet_to", "sum"), hu_sum=("pocet_hu", "sum"), poh=("pohyby_celkem", "sum"), lok=("pocet_lokaci", "sum")).reset_index()
                tr_df['prum_poh'] = np.where(tr_df['lok']>0, tr_df['poh']/tr_df['lok'], 0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['to_sum'], name='Počet TO', marker_color='#38bdf8', text=tr_df['to_sum'], textposition='auto'))
                fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['hu_sum'], name='Počet HU', marker_color='#818cf8', text=tr_df['hu_sum'], textposition='auto'))
                fig.add_trace(go.Scatter(x=tr_df['Month'], y=tr_df['prum_poh'], name='Pohyby na lokaci', yaxis='y2', mode='lines+markers+text', text=tr_df['prum_poh'].round(1), textposition='top center', textfont=dict(color='#f43f5e'), line=dict(color='#f43f5e', width=3)))
                
                fig.update_layout(
                    yaxis2=dict(title="Pohyby", side="right", overlaying="y", showgrid=False), 
                    plot_bgcolor="rgba(0,0,0,0)", 
                    paper_bgcolor="rgba(0,0,0,0)", 
                    margin=dict(l=0, r=0, t=30, b=0), 
                    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
                )
                st.plotly_chart(fig, use_container_width=True)
            
            interactive_chart()

        # --- NOVÁ MASTER ANALÝZA POMĚRU PICK VS PACK ---
        st.divider()
        st.markdown("### 💎 Analýza efektivity a ziskovosti (Master Data)")
        st.markdown("Tato tabulka odhaluje skutečnou hloubku finančních úniků z konsolidace a fyzickou náročnost na 1 fakturační jednotku.")
        
        # Příprava dat pro poměry a absolutní zisky/ztráty
        billing_df['is_1_to_1'] = (billing_df['pocet_to'] == billing_df['pocet_hu']).astype(int)
        billing_df['is_more_to'] = (billing_df['pocet_to'] > billing_df['pocet_hu']).astype(int)
        billing_df['is_more_hu'] = (billing_df['pocet_to'] < billing_df['pocet_hu']).astype(int)
        
        billing_df['ztrata_to'] = np.where(billing_df['is_more_to'], billing_df['pocet_to'] - billing_df['pocet_hu'], 0)
        billing_df['zisk_hu'] = np.where(billing_df['is_more_hu'], billing_df['pocet_hu'] - billing_df['pocet_to'], 0)
        
        ratio_table = billing_df.groupby('Category_Full').agg(
            celkem=('Delivery', 'nunique'),
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
        
        # Nové byznysové metriky
        ratio_table['Index (TO na 1 HU)'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['to_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Pohyby na 1 HU'] = np.where(ratio_table['hu_celkem'] > 0, ratio_table['pohyby_celkem'] / ratio_table['hu_celkem'], 0)
        ratio_table['Čistá bilance'] = ratio_table['hu_celkem'] - ratio_table['to_celkem'] # Kladné číslo znamená, že jsme vyfakturovali více, než jsme pickovali
        
        # Výběr a přejmenování sloupců pro zobrazení
        disp_ratio = ratio_table[[
            'Category_Full', 'celkem', 'to_celkem', 'hu_celkem', 
            'Index (TO na 1 HU)', 'Pohyby na 1 HU', 
            '1:1 (Ideál)', 'Více TO (Počet)', 'ztrata_to', 
            'Více HU (Počet)', 'zisk_hu', 'Čistá bilance'
        ]].copy()
        
        disp_ratio.columns = [
            "Kategorie", "Zakázek", "TO Celkem", "HU Celkem", 
            "Index konsolidace (TO/HU)", "Fyzické pohyby na 1 Billed HU", 
            "1:1 (Ideál)", "Více TO (Prodělaly)", "Ztráta (ks TO)", 
            "Více HU (Vydělaly)", "Zisk (ks HU)", "Čistá bilance (HU - TO)"
        ]
        
        def style_master_table(val):
            try:
                # Barvy pro čistou bilanci (Zelená = plus, Červená = minus)
                if isinstance(val, (int, float)) and val > 0 and 'Ztráta' not in str(val):
                    return 'color: #10b981; font-weight: bold'
                elif isinstance(val, (int, float)) and val < 0:
                    return 'color: #ef4444; font-weight: bold'
            except: pass
            return ''
            
        try:
            styled_master = disp_ratio.style.format({
                "Index konsolidace (TO/HU)": "{:.2f} TO", 
                "Fyzické pohyby na 1 Billed HU": "{:.1f} pohybů",
                "Ztráta (ks TO)": "- {}",
                "Zisk (ks HU)": "+ {}"
            }).map(style_master_table, subset=["Čistá bilance (HU - TO)"])
        except AttributeError:
            styled_master = disp_ratio.style.format({
                "Index konsolidace (TO/HU)": "{:.2f} TO", 
                "Fyzické pohyby na 1 Billed HU": "{:.1f} pohybů",
                "Ztráta (ks TO)": "- {}",
                "Zisk (ks HU)": "+ {}"
            }).applymap(style_master_table, subset=["Čistá bilance (HU - TO)"])
        
        # Tabulka přes celou šířku
        st.dataframe(styled_master, use_container_width=True, hide_index=True)
            
        # Graf pod tabulkou (Na plnou šířku)
        st.markdown("**Trend typů zakázek (Měsíce)**")
        trend_ratio = billing_df.groupby('Month').agg(
            count_1_1=('is_1_to_1', 'sum'),
            count_more_to=('is_more_to', 'sum'),
            count_more_hu=('is_more_hu', 'sum')
        ).reset_index()
        
        trend_ratio['total'] = trend_ratio['count_1_1'] + trend_ratio['count_more_to'] + trend_ratio['count_more_hu']
        trend_ratio['pct_1_1'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_1_1'] / trend_ratio['total'] * 100, 0)
        trend_ratio['pct_more_to'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_to'] / trend_ratio['total'] * 100, 0)
        trend_ratio['pct_more_hu'] = np.where(trend_ratio['total'] > 0, trend_ratio['count_more_hu'] / trend_ratio['total'] * 100, 0)
        
        fig_r = go.Figure()
        fig_r.add_trace(go.Bar(x=trend_ratio['Month'], y=trend_ratio['count_1_1'], name='1:1 (Kusy)', marker_color='rgba(16, 185, 129, 0.5)', text=trend_ratio['count_1_1'], textposition='inside', yaxis='y'))
        fig_r.add_trace(go.Bar(x=trend_ratio['Month'], y=trend_ratio['count_more_hu'], name='Více HU (Kusy)', marker_color='rgba(59, 130, 246, 0.5)', text=trend_ratio['count_more_hu'], textposition='inside', yaxis='y'))
        fig_r.add_trace(go.Bar(x=trend_ratio['Month'], y=trend_ratio['count_more_to'], name='Více TO (Kusy)', marker_color='rgba(239, 68, 68, 0.5)', text=trend_ratio['count_more_to'], textposition='inside', yaxis='y'))
        
        fig_r.add_trace(go.Scatter(x=trend_ratio['Month'], y=trend_ratio['pct_1_1'], name='1:1 (%)', mode='lines+markers+text', text=trend_ratio['pct_1_1'].round(1).astype(str) + '%', textposition='top center', marker_color='#10b981', line=dict(width=3), yaxis='y2'))
        fig_r.add_trace(go.Scatter(x=trend_ratio['Month'], y=trend_ratio['pct_more_hu'], name='Více HU (%)', mode='lines+markers+text', text=trend_ratio['pct_more_hu'].round(1).astype(str) + '%', textposition='top center', marker_color='#3b82f6', line=dict(width=3), yaxis='y2'))
        fig_r.add_trace(go.Scatter(x=trend_ratio['Month'], y=trend_ratio['pct_more_to'], name='Více TO (%)', mode='lines+markers+text', text=trend_ratio['pct_more_to'].round(1).astype(str) + '%', textposition='bottom center', marker_color='#ef4444', line=dict(width=3), yaxis='y2'))
        
        fig_r.update_layout(
            barmode='stack', 
            plot_bgcolor="rgba(0,0,0,0)", 
            paper_bgcolor="rgba(0,0,0,0)", 
            margin=dict(l=0, r=0, t=30, b=0), 
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
            yaxis=dict(title="Celkem zakázek"),
            yaxis2=dict(title="Podíl zakázek (%)", side="right", overlaying="y", showgrid=False, range=[0, 110])
        )
        st.plotly_chart(fig_r, use_container_width=True)

        # -------------------------------------------------------------
        st.divider()
        st.markdown(f"### ⚠️ Žebříček neefektivity z konsolidace (Práce zdarma)")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
            imb_disp.columns = ["Delivery", "Kategorie", "Pick TO celkem", "Pohyby rukou", "Účtované HU", "Prodělek (Rozdíl)"]
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

            kep_set = set()
            if not df_sdshp.empty:
                col_k = next((c for c in df_sdshp.columns if "KEP" in str(c).upper()), None)
                if col_k: kep_set = set(df_sdshp.loc[df_sdshp[col_k].astype(str).str.strip() == "X", df_sdshp.columns[0]].astype(str).str.strip().str.lstrip('0'))
            
            df_lf = pd.DataFrame()
            if not df_likp.empty:
                c_lief = df_likp.columns[0]
                c_vs = next((c for c in df_likp.columns if "Versandstelle" in str(c)), None)
                c_sped = next((c for c in df_likp.columns if "pediteur" in str(c)), None)
                df_lf = df_likp[[c_lief]].copy()
                df_lf.columns = ["Lieferung"]
                df_lf["Lieferung"] = df_lf["Lieferung"].astype(str).str.strip().str.lstrip('0')
                df_lf["is_KEP"] = df_likp[c_sped].astype(str).str.strip().str.lstrip('0').isin(kep_set) if c_sped else False
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
                if not df_lf.empty and "Lieferung" in df_vk.columns:
                    df_vk["Lieferung"] = df_vk["Lieferung"].astype(str).str.strip().str.lstrip('0')
                    df_vk["Kategorie"] = df_vk["Lieferung"].map(df_lf.set_index("Lieferung")["Kategorie"]).fillna("N")

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
