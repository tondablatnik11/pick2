import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from modules.utils import t

def render_pallets(df_pick):
    # Chytrý lokální překladač
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>{t('pal_title')}</h3><p>{t('pal_desc')}</p></div>", unsafe_allow_html=True)

    # Filtrace pouze na hlavní paletové fronty (Standard + Export)
    df_pal = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()

    if df_pal.empty:
        st.info(_t("Žádná data pro paletové fronty (PI_PL, PI_PL_OE).", "No data found for pallet queues (PI_PL, PI_PL_OE)."))
        return

    # Seskupení podle zakázky (Delivery)
    df_pal_exp = df_pal.groupby('Delivery').agg(
        num_materials=('Material', 'nunique'),
        materials_list=('Material', lambda x: ', '.join(x.unique())),
        total_qty=('Qty', 'sum'),
        total_moves=('Pohyby_Rukou', 'sum'),
        total_weight=('Celkova_Vaha_KG', 'sum'),
        max_dim=('Piece_Max_Dim_CM', 'max'),
        queue=('Queue', 'first')
    ).reset_index()

    # Rozdělení na Single a Mix
    df_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
    df_mix = df_pal_exp[df_pal_exp['num_materials'] > 1].copy()

    # --- Metriky nahoře ---
    col1, col2, col3 = st.columns(3)
    with col1:
        with st.container(border=True):
            st.metric(_t("Paletových zakázek celkem", "Total Pallet Orders"), f"{len(df_pal_exp):,}")
    with col2:
        with st.container(border=True):
            st.metric(_t("Jednodruhové (Single)", "Single-Material (Single)"), f"{len(df_single):,}")
    with col3:
        with st.container(border=True):
            st.metric(_t("Vícedruhové (Mix)", "Multi-Material (Mix)"), f"{len(df_mix):,}")

    st.divider()

    # --- Graf poměru Single vs Mix ---
    col_ch1, col_ch2 = st.columns([1, 2])
    
    with col_ch1:
        st.markdown(f"**{_t('Poměr zakázek: Single vs. Mix', 'Order Ratio: Single vs. Mix')}**")
        pie_data = pd.DataFrame({
            'Type': [_t('Single (1 materiál)', 'Single (1 Material)'), _t('Mix (Více materiálů)', 'Mix (>1 Material)')],
            'Count': [len(df_single), len(df_mix)]
        })
        fig = px.pie(pie_data, values='Count', names='Type', hole=0.4, color_discrete_sequence=['#10b981', '#ef4444'])
        fig.update_traces(textposition='inside', textinfo='percent+label')
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    with col_ch2:
        # --- Tabulky s detaily ---
        st.markdown(f"**🟢 {_t('TOP 100: Jednodruhové zakázky (Single)', 'TOP 100: Single-Material Orders (Single)')}**")
        st.markdown(_t("Tyto zakázky jsou ideální pro okamžité odeslání (bez nutnosti složité konsolidace u stolu).", "These orders are ideal for direct shipping (no complex consolidation needed at the desk)."))
        
        if not df_single.empty:
            disp_single = df_single.sort_values('total_qty', ascending=False).head(100).copy()
            disp_single = disp_single[['Delivery', 'materials_list', 'total_qty', 'total_moves', 'total_weight', 'max_dim', 'queue']]
            disp_single.columns = [
                _t("Zakázka", "Order"), 
                _t("Materiál", "Material"), 
                _t("Kusů", "Qty"), 
                _t("Pohyby rukou", "Hand Moves"), 
                _t("Váha (kg)", "Weight (kg)"), 
                _t("Max Rozměr (cm)", "Max Dim (cm)"), 
                "Queue"
            ]
            st.dataframe(disp_single.style.format({_t("Váha (kg)", "Weight (kg)"): "{:.1f}", _t("Max Rozměr (cm)", "Max Dim (cm)"): "{:.1f}"}), use_container_width=True, hide_index=True)
        else:
            st.info(_t("Žádné jednodruhové zakázky nenalezeny.", "No single-material orders found."))

    st.markdown(f"<br>**🔴 {_t('Vícedruhové zakázky (Mix) vyžadující konsolidaci', 'Multi-Material Orders (Mix) requiring consolidation')}**", unsafe_allow_html=True)
    
    if not df_mix.empty:
        disp_mix = df_mix.sort_values('num_materials', ascending=False).copy()
        disp_mix = disp_mix[['Delivery', 'num_materials', 'total_qty', 'total_moves', 'total_weight', 'queue']]
        disp_mix.columns = [
            _t("Zakázka", "Order"), 
            _t("Počet druhů materiálů", "Material Types Count"), 
            _t("Celkem Kusů", "Total Qty"), 
            _t("Pohyby rukou celkem", "Total Hand Moves"), 
            _t("Váha (kg)", "Weight (kg)"), 
            "Queue"
        ]
        st.dataframe(disp_mix.style.format({_t("Váha (kg)", "Weight (kg)"): "{:.1f}"}), use_container_width=True, hide_index=True)
    else:
        st.info(_t("Žádné vícedruhové zakázky nenalezeny.", "No multi-material orders found."))
