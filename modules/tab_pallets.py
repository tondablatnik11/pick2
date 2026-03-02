import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

def render_pallets(df_pick):
    st.markdown(f"<div class='section-header'><h3>🎯 {t('sec1_title')}</h3><p>{t('pallets_clean_info')}</p></div>", unsafe_allow_html=True)
    
    # 1. Vyfiltrujeme pouze paletové fronty
    pal_df = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
    
    if pal_df.empty:
        st.info("V aktuálních datech nejsou žádné zakázky z front PI_PL nebo PI_PL_OE.")
        return

    # 2. Agregace dat na úroveň celé zakázky (Delivery)
    pal_agg = pal_df.groupby('Delivery').agg(
        num_materials=('Material', 'nunique'),
        total_qty=('Qty', 'sum'),
        celkem_pohybu=('Pohyby_Rukou', 'sum'),
        lokace=('Source Storage Bin', 'nunique'),
        vaha_zakazky=('Celkova_Vaha_KG', 'sum'),
        Month=('Month', 'first')
    ).reset_index()

    # Rozřazení na Single SKU (1 materiál) a Mix (>1 materiál)
    pal_agg['Typ_Palety'] = np.where(pal_agg['num_materials'] == 1, 'Single SKU', 'Mix (Více materiálů)')
    
    # 3. METRIKY
    total_pal = len(pal_agg)
    single_pal = len(pal_agg[pal_agg['Typ_Palety'] == 'Single SKU'])
    mix_pal = len(pal_agg[pal_agg['Typ_Palety'] == 'Mix (Více materiálů)'])
    
    single_pct = (single_pal / total_pal * 100) if total_pal > 0 else 0
    mix_pct = (mix_pal / total_pal * 100) if total_pal > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True): 
            st.metric("Paletových zakázek celkem", f"{total_pal:,}")
    with c2:
        with st.container(border=True): 
            st.metric("📦 Single SKU (1 materiál)", f"{single_pal:,}", f"{single_pct:.1f} % podíl", delta_color="normal")
    with c3:
        with st.container(border=True): 
            st.metric("🔀 Mix palety (>1 materiál)", f"{mix_pal:,}", f"{mix_pct:.1f} % podíl", delta_color="inverse")
    with c4:
        avg_moves = pal_agg['celkem_pohybu'].mean() if not pal_agg.empty else 0
        with st.container(border=True): 
            st.metric("Průměr fyz. pohybů na zakázku", f"{avg_moves:.1f}")

    st.divider()

    col_t, col_g = st.columns([1, 1.5])

    # 4. TABULKA (Nejnáročnější Single SKU zakázky)
    with col_t:
        st.markdown("**Detailní přehled (Nejnáročnější Single SKU)**")
        single_df = pal_agg[pal_agg['Typ_Palety'] == 'Single SKU'].copy()
        
        if not single_df.empty:
            single_df['prum_poh_lok'] = np.where(single_df['lokace'] > 0, single_df['celkem_pohybu'] / single_df['lokace'], 0)
            disp_single = single_df[['Delivery', 'total_qty', 'celkem_pohybu', 'prum_poh_lok', 'vaha_zakazky']].sort_values('celkem_pohybu', ascending=False).head(50)
            disp_single.columns = ["Zakázka", "Kusů", "Pohyby celkem", "Pohybů / lokaci", "Celk. váha (kg)"]
            
            st.dataframe(disp_single.style.format({"Pohybů / lokaci": "{:.1f}", "Celk. váha (kg)": "{:.1f}"}), use_container_width=True, hide_index=True)
        else:
            st.info("Žádné Single SKU zakázky k zobrazení.")

    # 5. NOVÝ KOMBINOVANÝ GRAF (Trend v čase: Absolutní čísla + Procenta)
    with col_g:
        st.markdown("**📈 Měsíční trend (Single vs. Mix palety)**")
        if 'Month' in pal_agg.columns:
            trend_agg = pal_agg.groupby(['Month', 'Typ_Palety']).size().reset_index(name='pocet')
            
            pivot_trend = trend_agg.pivot(index='Month', columns='Typ_Palety', values='pocet').fillna(0).reset_index()
            
            if 'Single SKU' not in pivot_trend.columns: pivot_trend['Single SKU'] = 0
            if 'Mix (Více materiálů)' not in pivot_trend.columns: pivot_trend['Mix (Více materiálů)'] = 0
            
            pivot_trend['Celkem'] = pivot_trend['Single SKU'] + pivot_trend['Mix (Více materiálů)']
            pivot_trend['Single_pct'] = np.where(pivot_trend['Celkem'] > 0, pivot_trend['Single SKU'] / pivot_trend['Celkem'] * 100, 0)
            pivot_trend['Mix_pct'] = np.where(pivot_trend['Celkem'] > 0, pivot_trend['Mix (Více materiálů)'] / pivot_trend['Celkem'] * 100, 0)
            
            fig = go.Figure()
            
            # Sloupce (Absolutní počty, mírně průhledné, aby nekryly čáry)
            fig.add_trace(go.Bar(x=pivot_trend['Month'], y=pivot_trend['Single SKU'], name='Single SKU (Ks)', marker_color='rgba(16, 185, 129, 0.5)', text=pivot_trend['Single SKU'], textposition='inside', yaxis='y'))
            fig.add_trace(go.Bar(x=pivot_trend['Month'], y=pivot_trend['Mix (Více materiálů)'], name='Mix palety (Ks)', marker_color='rgba(245, 158, 11, 0.5)', text=pivot_trend['Mix (Více materiálů)'], textposition='inside', yaxis='y'))
            
            # Čáry (Procentuální podíl, plná barva)
            fig.add_trace(go.Scatter(x=pivot_trend['Month'], y=pivot_trend['Single_pct'], name='Podíl Single (%)', mode='lines+markers+text', text=pivot_trend['Single_pct'].round(1).astype(str) + '%', textposition='top center', marker_color='#059669', line=dict(width=3), yaxis='y2'))
            fig.add_trace(go.Scatter(x=pivot_trend['Month'], y=pivot_trend['Mix_pct'], name='Podíl Mix (%)', mode='lines+markers+text', text=pivot_trend['Mix_pct'].round(1).astype(str) + '%', textposition='bottom center', marker_color='#d97706', line=dict(width=3), yaxis='y2'))
            
            fig.update_layout(
                barmode='stack',
                yaxis=dict(title="Absolutní počet zakázek"),
                yaxis2=dict(title="Procentuální podíl (%)", side="right", overlaying="y", showgrid=False, range=[0, 115]),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Chybí data o měsících pro vykreslení trendu.")
