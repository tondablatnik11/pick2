import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from database import load_from_db
from modules.utils import t

def render_fu(df_pick, queue_count_col):
    st.markdown(f"<div class='section-header'><h3>🏭 {t('fu_title')}</h3><p>{t('fu_desc')}</p></div>", unsafe_allow_html=True)
    
    # 1. Filtrace pouze na paletové fronty (FU / FUOE)
    fu_df = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()
    
    if fu_df.empty:
        st.info("V datech chybí záznamy pro fronty PI_PL_FU nebo PI_PL_FUOE.")
        return
        
    # --- 2. Základní přehled (Storage Unit Type - KLT vs Palety) ---
    c_su = 'Storage Unit Type' if 'Storage Unit Type' in fu_df.columns else ('Type' if 'Type' in fu_df.columns else None)
    
    if c_su:
        st.markdown("### 🏷️ Poměr typů balení (KLT vs Palety)")
        su_agg = fu_df.groupby(c_su).agg(
            lines=('Material', 'count'),
            tos=(queue_count_col, 'nunique'),
            qty=('Qty', 'sum')
        ).reset_index().sort_values('tos', ascending=False)
        su_agg.columns = [t('fu_col_su'), t('fu_col_lines'), t('fu_col_to'), t('fu_col_qty')]
        
        col_su1, col_su2 = st.columns([1.2, 1])
        with col_su1:
            st.dataframe(su_agg, use_container_width=True, hide_index=True)
        with col_su2:
            fig_pie = px.pie(su_agg, values=t('fu_col_to'), names=t('fu_col_su'), hole=0.4, title="Podíl Pick TO podle typu obalu")
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(margin=dict(t=40, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Sloupec pro Typ jednotky (Storage Unit Type) nebyl v datech nalezen.")

    # --- 3. ANALÝZA EFEKTIVITY PŘEBALOVÁNÍ (VOLLPALETTE) ---
    st.divider()
    st.markdown("### 📦 Efektivita: Přímé balení bez přebalování (Vollpalette)")
    st.markdown("Algoritmus provádí přísnou křížovou kontrolu:")
    st.markdown("1. Byla pozice vybrána do nuly (**'X'**).")
    st.markdown("2. Byla vyloučena malá balení (Typ jednotky není **K1** ani KLT).")
    st.markdown("3. Zdrojové HU z pickování se **přesně shoduje** s HU vyfakturovaným u dané zakázky ve VEKP.")
    st.markdown("4. Ve **VEPO** je ověřeno, že dané HU opravdu obsahuje položky.")

    df_vekp = load_from_db('raw_vekp')
    df_vepo = load_from_db('raw_vepo')
    
    if df_vekp is None or df_vekp.empty:
        st.warning("⚠️ K vyhodnocení této metriky je nutné mít v Admin Zóně nahrán soubor **VEKP** (Obaly).")
        return

    # KROK A: Zpracování VEPO (Zjištění HU, která mají reálně obsah)
    vepo_hus = set()
    if df_vepo is not None and not df_vepo.empty:
        vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
        vepo_hus = set(df_vepo[vepo_hu_col].astype(str).str.strip().str.lstrip('0'))

    # KROK B: Zpracování VEKP (Vytvoření mapy: Delivery -> Seznam validních HU)
    df_vekp['Clean_Del'] = df_vekp['Generated delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    vekp_hu_col = next((c for c in df_vekp.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vekp.columns[0])
    c_hu_ext = df_vekp.columns[1] if len(df_vekp.columns) > 1 else vekp_hu_col

    df_vekp['Clean_HU_Int'] = df_vekp[vekp_hu_col].astype(str).str.strip().str.lstrip('0')
    df_vekp['Clean_HU_Ext'] = df_vekp[c_hu_ext].astype(str).str.strip().str.lstrip('0')

    del_to_valid_hus = {}
    for d, grp in df_vekp.groupby('Clean_Del'):
        valid_hus = set()
        for _, r in grp.iterrows():
            h_int = r['Clean_HU_Int']
            h_ext = r['Clean_HU_Ext']
            # Pokud máme VEPO, HU musí být ve VEPO (musí mít položky)
            if vepo_hus and h_int not in vepo_hus:
                continue
            valid_hus.add(h_int)
            valid_hus.add(h_ext)
        del_to_valid_hus[d] = valid_hus

    # KROK C: Vyčištění a detekce v Pick reportu
    fu_df['Clean_Del'] = fu_df['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    fu_df['Has_X'] = fu_df['Removal of total SU'].astype(str).str.strip().str.upper() == 'X'
    
    # Funkce pro vyloučení KLT / K1
    def is_klt(su_val):
        v = str(su_val).upper().strip()
        # Vyloučí K1, KLT, nebo jakýkoliv dvoumístný kód začínající na K (např. K2, K3)
        return v in ['K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'] or (v.startswith('K') and len(v) <= 2)
        
    fu_df['Is_KLT'] = fu_df[c_su].apply(is_klt) if c_su else False

    pick_hu_cols = ['Source storage unit', 'Source Storage Bin', 'Handling Unit']
    
    # KROK D: Finální křížová kontrola
    def check_is_vollpalette(row):
        if not row['Has_X']: return False
        if row['Is_KLT']: return False # Ignorujeme dopickované KLT
        
        clean_del = row['Clean_Del']
        valid_hus_for_del = del_to_valid_hus.get(clean_del, set())
        
        if not valid_hus_for_del: return False
        
        for col in pick_hu_cols:
            if col in row.index and pd.notna(row[col]):
                val = str(row[col]).strip().lstrip('0')
                if val and val != 'nan' and val != 'none':
                    # HU se musí shodovat s HU vyfakturovaným PŘESNĚ u této zakázky
                    if val in valid_hus_for_del:
                        return True
        return False

    fu_df['Neprebalovano'] = fu_df.apply(check_is_vollpalette, axis=1)
    
    # Z výpočtů metrik striktně odstraníme KLT krabičky
    fu_df_pallets = fu_df[~fu_df['Is_KLT']].copy()
    ignored_klt_count = fu_df[fu_df['Is_KLT']][queue_count_col].nunique()
    
    # --- MĚSÍČNÍ GRAF EFEKTIVITY ---
    if 'Month' in fu_df_pallets.columns:
        st.markdown("#### 📈 Měsíční trend odbavení celých palet")
        trend_fu = fu_df_pallets[fu_df_pallets['Has_X']].groupby(['Month', 'Neprebalovano'])[queue_count_col].nunique().reset_index()
        trend_fu['Status'] = np.where(trend_fu['Neprebalovano'], 'Nepřebalováno (Ziskové)', 'Přebaleno (Zbytečná práce)')
        
        fig_bar = px.bar(
            trend_fu, 
            x='Month', 
            y=queue_count_col, 
            color='Status', 
            barmode='group',
            color_discrete_map={'Nepřebalováno (Ziskové)': '#10b981', 'Přebaleno (Zbytečná práce)': '#ef4444'},
            labels={'Month': 'Měsíc', queue_count_col: 'Počet palet (TO)', 'Status': 'Stav palety'}
        )
        fig_bar.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=20, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_bar, use_container_width=True)
        st.markdown("<br>", unsafe_allow_html=True)
    
    # Výpočty pro zobrazení metrik (unikátní TO)
    total_fu_pal = fu_df_pallets[queue_count_col].nunique()
    total_x_pal = fu_df_pallets[fu_df_pallets['Has_X']][queue_count_col].nunique()
    total_neprebalovano = fu_df_pallets[fu_df_pallets['Neprebalovano']][queue_count_col].nunique()
    
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric("Celkem pickováno palet (TO)", f"{total_fu_pal:,}", help=f"Ignorováno {ignored_klt_count} TO, u kterých se dopickovávalo KLT (K1).")
    with c2:
        with st.container(border=True):
            st.metric("Celá paleta ze skladu (Značka 'X')", f"{total_x_pal:,}", help="U tolika TO skladník vybral pozici do nuly (mimo KLT).")
    with c3:
        with st.container(border=True):
            st.metric("Nepřebalováno (Úplná shoda) ✅", f"{total_neprebalovano:,}", help="Paleta prošla balením tak, jak přišla ze skladu (shoda s VEKP a VEPO pro danou zakázku).")
            
    # Zobrazení detailů - kde se práce ušetřila vs. kde se pálil čas přebalováním
    prebaleno_x = fu_df_pallets[(fu_df_pallets['Has_X']) & (~fu_df_pallets['Neprebalovano'])]
    
    st.markdown("<br>", unsafe_allow_html=True)
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        st.success(f"**✅ Úspěšné Vollpalety: {total_neprebalovano} TO**")
        nepreb_df = fu_df_pallets[fu_df_pallets['Neprebalovano']].drop_duplicates(subset=[queue_count_col]).copy()
        if not nepreb_df.empty:
            disp1 = nepreb_df[['Delivery', queue_count_col, 'Material', 'Qty', c_su] if c_su else ['Delivery', queue_count_col, 'Material', 'Qty']].copy()
            disp1.columns = ["Delivery", "Číslo TO", "Materiál", "Kusů", "Typ jednotky"] if c_su else ["Delivery", "Číslo TO", "Materiál", "Kusů"]
            st.dataframe(disp1, use_container_width=True, hide_index=True)
        else:
            st.info("Žádné palety nebyly odbaveny napřímo.")
            
    with col_t2:
        st.error(f"**⚠️ Zbytečná práce (Přebaleno): {prebaleno_x[queue_count_col].nunique()} TO**\n*Měly značku 'X', ale přebalily se na jiné HU.*")
        if not prebaleno_x.empty:
            disp2 = prebaleno_x.drop_duplicates(subset=[queue_count_col])[['Delivery', queue_count_col, 'Material', 'Qty', c_su] if c_su else ['Delivery', queue_count_col, 'Material', 'Qty']].copy()
            disp2.columns = ["Delivery", "Číslo TO", "Materiál", "Kusů", "Typ jednotky"] if c_su else ["Delivery", "Číslo TO", "Materiál", "Kusů"]
            st.dataframe(disp2, use_container_width=True, hide_index=True)
        else:
            st.info("Skvělá práce! Všechny celé palety ('X') byly úspěšně odbaveny bez přebalování.")
