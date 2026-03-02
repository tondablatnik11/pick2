import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t

def get_sut_col(df):
    """Pokusí se chytře najít sloupec s Typem skladovací jednotky (SUT)"""
    cols_up = {str(c).strip().upper(): c for c in df.columns}
    
    # Přímé přesné shody
    for k in ['SU TYPE', 'SUT', 'STORAGE UNIT TYPE', 'TYP SU', 'TYP SKLADOVACÍ JEDNOTKY', 'TYP SKLAD. JEDN.', 'TYP SKLAD.JEDN.', 'SUTYPE']:
        if k in cols_up: return cols_up[k]
        
    # Částečné shody, pokud se sloupec jmenuje trochu jinak
    for k, original_col in cols_up.items():
        if 'SU TYP' in k or 'SUT' in k or 'UNIT TYPE' in k or 'TYP SKLAD' in k or 'SKLAD. JEDN' in k:
            return original_col
            
    return None

def categorize_su(sut):
    """Rozřadí kódy SUT na Palety, KLT a zbytek"""
    if pd.isna(sut) or str(sut).strip() == '': 
        return 'Neznámé'
        
    s = str(sut).strip().upper()
    
    # Identifikace palet (obvykle začínají na E (Euro), P (Pallet), C (Chep), D, V nebo přímo obsahují PAL)
    if 'PAL' in s or s.startswith('E') or s.startswith('P') or s.startswith('C') or s.startswith('D') or s.startswith('V') or 'VVP' in s or 'CHEP' in s: 
        return 'Paleta'
        
    # Identifikace KLT krabic (obvykle začínají na K nebo B)
    elif 'KLT' in s or s.startswith('K') or s.startswith('B'): 
        return 'KLT'
        
    else:
        return 'Ostatní / Neznámé'

def render_fu(df_pick, queue_count_col):
    st.markdown(f"<div class='section-header'><h3>🏭 {t('fu_title')}</h3><p>{t('fu_desc')}</p></div>", unsafe_allow_html=True)
    
    # Vyfiltrujeme pouze FU fronty
    fu_df = df_pick[df_pick['Queue'].astype(str).str.upper().str.contains('PI_PL_FU')].copy()
    
    if fu_df.empty:
        st.info("V aktuálních datech nejsou žádné zakázky z front PI_PL_FU nebo PI_PL_FUOE.")
        return

    # Zjistíme, jak se jmenuje sloupec pro SU type
    sut_col = get_sut_col(fu_df)
    
    if sut_col:
        fu_df['Skladovaci_Jednotka'] = fu_df[sut_col].fillna('Neznámé')
    else:
        fu_df['Skladovaci_Jednotka'] = 'Neznámé (Sloupec SUT nenalezen)'

    # Rozřazení do kategorií
    fu_df['Typ_Obalu'] = fu_df['Skladovaci_Jednotka'].apply(categorize_su)

    # 1. HLAVNÍ METRIKY (Celková procenta)
    total_lines = len(fu_df)
    klt_lines = len(fu_df[fu_df['Typ_Obalu'] == 'KLT'])
    pal_lines = len(fu_df[fu_df['Typ_Obalu'] == 'Paleta'])
    
    klt_pct = (klt_lines / total_lines * 100) if total_lines > 0 else 0
    pal_pct = (pal_lines / total_lines * 100) if total_lines > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True): 
            st.metric("Celkem picků (Řádků ve FU)", f"{total_lines:,}")
    with c2:
        with st.container(border=True): 
            st.metric("📦 Z toho KLT přepravky", f"{klt_lines:,}", f"{klt_pct:.1f} % podíl", delta_color="off")
    with c3:
        with st.container(border=True): 
            st.metric("🏭 Z toho Palety", f"{pal_lines:,}", f"{pal_pct:.1f} % podíl", delta_color="off")
    with c4:
        with st.container(border=True): 
            st.metric("Celkový poměr (KLT : Palety)", f"{klt_pct:.0f} : {pal_pct:.0f}")

    st.divider()

    col_t, col_g = st.columns([1, 1.5])

    # 2. DETAILY V TABULCE
    with col_t:
        st.markdown("**Přehled podle přesných kódů (SUT)**")
        agg_df = fu_df.groupby(['Typ_Obalu', 'Skladovaci_Jednotka']).agg(
            radky=('Material', 'count'),
            kusy=('Qty', 'sum'),
            pocet_to=(queue_count_col, 'nunique')
        ).reset_index().sort_values('radky', ascending=False)
        
        agg_df['Podíl (%)'] = (agg_df['radky'] / total_lines * 100).round(1).astype(str) + " %"
        
        disp_df = agg_df[['Typ_Obalu', 'Skladovaci_Jednotka', 'radky', 'pocet_to', 'kusy', 'Podíl (%)']].copy()
        disp_df.columns = [t('fu_col_cat'), t('fu_col_su'), t('fu_col_lines'), t('fu_col_to'), t('fu_col_qty'), 'Podíl (%)']
        st.dataframe(disp_df, use_container_width=True, hide_index=True)

    # 3. INTERAKTIVNÍ GRAF S TRENDEM
    with col_g:
        st.markdown("**📈 Měsíční trend (KLT vs. Palety)**")
        if 'Month' in fu_df.columns:
            trend_agg = fu_df.groupby(['Month', 'Typ_Obalu']).agg(
                radky=('Material', 'count')
            ).reset_index()
            
            pivot_trend = trend_agg.pivot(index='Month', columns='Typ_Obalu', values='radky').fillna(0).reset_index()
            
            if 'KLT' not in pivot_trend.columns: pivot_trend['KLT'] = 0
            if 'Paleta' not in pivot_trend.columns: pivot_trend['Paleta'] = 0
            
            pivot_trend['Celkem'] = pivot_trend['KLT'] + pivot_trend['Paleta'] + pivot_trend.get('Ostatní / Neznámé', 0)
            pivot_trend['KLT_pct'] = np.where(pivot_trend['Celkem'] > 0, pivot_trend['KLT'] / pivot_trend['Celkem'] * 100, 0)
            pivot_trend['Paleta_pct'] = np.where(pivot_trend['Celkem'] > 0, pivot_trend['Paleta'] / pivot_trend['Celkem'] * 100, 0)
            
            fig = go.Figure()
            
            # Sloupce (Absolutní počty, průhledné aby nezakrývaly čáry)
            fig.add_trace(go.Bar(x=pivot_trend['Month'], y=pivot_trend['Paleta'], name='Palety (Ks)', marker_color='rgba(56, 189, 248, 0.5)', text=pivot_trend['Paleta'], textposition='inside', yaxis='y'))
            fig.add_trace(go.Bar(x=pivot_trend['Month'], y=pivot_trend['KLT'], name='KLT (Ks)', marker_color='rgba(244, 63, 94, 0.5)', text=pivot_trend['KLT'], textposition='inside', yaxis='y'))
            
            # Čáry (Procenta, barevně syté a s popisky nahoře/dole)
            fig.add_trace(go.Scatter(x=pivot_trend['Month'], y=pivot_trend['Paleta_pct'], name='Podíl Palet (%)', mode='lines+markers+text', text=pivot_trend['Paleta_pct'].round(1).astype(str) + '%', textposition='top center', marker_color='#0284c7', line=dict(width=3), yaxis='y2'))
            fig.add_trace(go.Scatter(x=pivot_trend['Month'], y=pivot_trend['KLT_pct'], name='Podíl KLT (%)', mode='lines+markers+text', text=pivot_trend['KLT_pct'].round(1).astype(str) + '%', textposition='bottom center', marker_color='#e11d48', line=dict(width=3), yaxis='y2'))
            
            fig.update_layout(
                barmode='stack',
                yaxis=dict(title="Absolutní počet picků (Řádky)"),
                yaxis2=dict(title="Procentuální podíl (%)", side="right", overlaying="y", showgrid=False, range=[0, 110]),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chybí data o měsících pro vykreslení trendu.")
