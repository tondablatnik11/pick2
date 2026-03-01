import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from modules.utils import t, QUEUE_DESC

def render_dashboard(df_pick, queue_count_col):
    display_q = None
    tot_mov = df_pick['Pohyby_Rukou'].sum()
    if tot_mov > 0:
        st.markdown(f"<div class='section-header'><h3>{t('sec_ratio')}</h3><p>{t('ratio_desc')}</p></div>", unsafe_allow_html=True)
        st.markdown(f"**{t('ratio_moves')}**")
        c_r1, c_r2 = st.columns(2)
        with c_r1:
            with st.container(border=True): st.metric(t('ratio_exact'), f"{df_pick['Pohyby_Exact'].sum() / tot_mov * 100:.1f} %", f"{df_pick['Pohyby_Exact'].sum():,.0f} pohybů")
        with c_r2:
            with st.container(border=True): st.metric(t('ratio_miss'), f"{df_pick['Pohyby_Loose_Miss'].sum() / tot_mov * 100:.1f} %", f"{df_pick['Pohyby_Loose_Miss'].sum():,.0f} pohybů", delta_color="inverse")

    if (df_pick['Queue'].notna().any() and df_pick['Queue'].nunique() > 1):
        st.markdown(f"<div class='section-header'><h3>{t('sec_queue_title')}</h3></div>", unsafe_allow_html=True)
        df_q_filter = df_pick.copy()
        if not df_q_filter.empty:
            queue_agg_raw = df_q_filter.groupby([queue_count_col, 'Queue']).agg(celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'), pohyby_miss=('Pohyby_Loose_Miss', 'sum'), total_qty=('Qty', 'sum'), num_materials=('Material', 'nunique'), pocet_lokaci=('Source Storage Bin', 'nunique'), delivery=('Delivery', 'first')).reset_index()
            def adjust_queue_name(row):
                q_up = str(row['Queue']).upper()
                if q_up in ['PI_PL', 'PI_PL_OE']: return row['Queue'] + (' (Single)' if row['num_materials'] == 1 else ' (Mix)')
                return row['Queue']
            totals_rows = queue_agg_raw[queue_agg_raw['Queue'].str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
            totals_rows['Queue'] = totals_rows['Queue'] + ' (Total)'
            queue_agg_raw['Queue'] = queue_agg_raw.apply(adjust_queue_name, axis=1)
            queue_agg_final = pd.concat([queue_agg_raw, totals_rows], ignore_index=True)

            q_sum = queue_agg_final.groupby('Queue').agg(pocet_zakazek=('delivery', 'nunique'), prum_lokaci=('pocet_lokaci', 'mean'), lokaci_sum=('pocet_lokaci', 'sum'), pohybu_sum=('celkem_pohybu', 'sum'), exact_sum=('pohyby_exact', 'sum'), miss_sum=('pohyby_miss', 'sum')).reset_index()
            if queue_count_col == 'Transfer Order Number': q_sum = q_sum.merge(queue_agg_final.groupby('Queue')[queue_count_col].nunique().rename('pocet_TO'), on='Queue', how='left')
            else: q_sum['pocet_TO'] = q_sum['pocet_zakazek']

            q_sum['prum_pohybu_lokace'] = np.where(q_sum['lokaci_sum'] > 0, q_sum['pohybu_sum'] / q_sum['lokaci_sum'], 0)
            q_sum['pct_exact'] = np.where(q_sum['pohybu_sum'] > 0, q_sum['exact_sum'] / q_sum['pohybu_sum'] * 100, 0)
            q_sum['pct_miss'] = np.where(q_sum['pohybu_sum'] > 0, q_sum['miss_sum'] / q_sum['pohybu_sum'] * 100, 0)
            q_sum['Popis'] = q_sum['Queue'].map(QUEUE_DESC).fillna('')
            q_sum = q_sum.sort_values('prum_pohybu_lokace', ascending=False)

            display_q = q_sum[['Queue', 'Popis', 'pocet_TO', 'pocet_zakazek', 'prum_lokaci', 'prum_pohybu_lokace', 'pct_exact', 'pct_miss']].copy()
            display_q.columns = [t('q_col_queue'), t('q_col_desc'), t('q_col_to'), t('q_col_orders'), t('q_col_loc'), t('q_col_mov_loc'), t('q_pct_exact'), t('q_pct_miss')]

            fmt_q = {c: "{:.1f} %" if "%" in c else "{:.1f}" for c in display_q.columns if c not in [t('q_col_queue'), t('q_col_desc'), t('q_col_to'), t('q_col_orders')]}
            styled_q = display_q.style.format(fmt_q).set_properties(subset=[t('q_col_queue'), t('q_col_mov_loc')], **{'font-weight': 'bold', 'color': '#1f77b4', 'background-color': 'rgba(31,119,180,0.05)'})
            
            col_qt1, col_qt2 = st.columns([2.5, 1.5])
            with col_qt1: st.dataframe(styled_q, use_container_width=True, hide_index=True)
            with col_qt2:
                fig = px.bar(q_sum.drop_duplicates('Queue'), x='Queue', y='prum_pohybu_lokace', title='Náročnost (Pohyby na 1 lokaci)', text_auto='.1f', color='prum_pohybu_lokace', color_continuous_scale='Reds')
                fig.update_layout(xaxis_title="", yaxis_title="Pohyby", coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)
    return display_q
