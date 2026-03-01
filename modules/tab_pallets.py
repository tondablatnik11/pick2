import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

def render_pallets(df_pick):
    # OPRAVENÝ NADPIS NA SINGLE SKU PALLET
    st.markdown(f"<div class='section-header'><h3>🎯 Analýza paletových zakázek (Single SKU Pallet)</h3><p>*(Jednodruhové palety, počítáno výhradně z front PI_PL a PI_PL_OE)*</p></div>", unsafe_allow_html=True)

    df_pallets_clean = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
    
    for col_name in ['Certificate Number']:
        if col_name not in df_pallets_clean.columns: df_pallets_clean[col_name] = ''

    if not df_pallets_clean.empty:
        grouped_orders = df_pallets_clean.groupby('Delivery').agg(
            num_materials=('Material', 'nunique'), material=('Material', 'first'),
            certs=('Certificate Number', lambda x: ", ".join([str(v) for v in x.dropna().unique() if str(v) not in ['', 'nan']])),
            total_qty=('Qty', 'sum'), num_positions=('Source Storage Bin', 'nunique'),
            celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'),
            pohyby_miss=('Pohyby_Loose_Miss', 'sum'), vaha_zakazky=('Celkova_Vaha_KG', 'sum'),
            max_rozmer=('Piece_Max_Dim_CM', 'first'), Month=('Month', 'first')
        )
        
        # FILTR PRO SINGLE SKU (1 materiál na zakázku)
        filtered_orders = grouped_orders[grouped_orders['num_materials'] == 1].copy()

        if not filtered_orders.empty:
            filtered_orders['mov_per_loc'] = np.where(filtered_orders['num_positions'] > 0, filtered_orders['celkem_pohybu'] / filtered_orders['num_positions'], 0)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                with st.container(border=True): st.metric("Počet zakázek", f"{len(filtered_orders):,}".replace(',', ' '))
            with c2:
                with st.container(border=True): st.metric("Prům. kusů / zakázku", f"{filtered_orders['total_qty'].mean():.1f}")
            with c3:
                with st.container(border=True): st.metric("Prům. pozic / zakázku", f"{filtered_orders['num_positions'].mean():.2f}")
            with c4:
                with st.container(border=True): st.metric("Prům. fyz. pohybů na lokaci", f"{filtered_orders['mov_per_loc'].mean():.1f}")

            # --- TREND GRAF ---
            st.divider()
            trend_df = filtered_orders.groupby('Month').agg(pocet_to=('total_qty', 'count'), prum_poh=('mov_per_loc', 'mean')).reset_index()
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=trend_df['Month'], y=trend_df['pocet_to'], name='Počet TO', marker_color='#38bdf8'))
            fig.add_trace(go.Scatter(x=trend_df['Month'], y=trend_df['prum_poh'], name='Pohyby na lokaci', yaxis='y2', mode='lines+markers', line=dict(color='#f43f5e', width=3)))
            
            fig.update_layout(
                title="Trend počtu zakázek a náročnosti",
                yaxis=dict(title="Počet TO", side="left"),
                yaxis2=dict(title="Prům. pohybů na lokaci", side="right", overlaying="y", showgrid=False),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=40, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)

            tot_p_pal = filtered_orders['celkem_pohybu'].sum()
            if tot_p_pal > 0:
                st.markdown("**Podíl z celkového počtu POHYBŮ:**")
                c_p1, c_p2 = st.columns(2)
                c_p1.metric("Přesně (Krabice / Palety / Volné)", f"{filtered_orders['pohyby_exact'].sum() / tot_p_pal * 100:.1f} %")
                c_p2.metric("Odhady (Chybí balení)", f"{filtered_orders['pohyby_miss'].sum() / tot_p_pal * 100:.1f} %", delta_color="inverse")

            with st.expander("Zobrazit tabulku zakázek (Single SKU)"):
                display_df = filtered_orders[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer', 'certs']].copy()
                display_df.columns = ["Materiál", "Kusů celkem", "Celkem pohybů", "Pohyby (Přesně)", "Pohyby (Odhady)", "Hmotnost (kg)", "Rozměr (cm)", "Certifikát"]
                st.dataframe(display_df, use_container_width=True, hide_index=True)
        else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
    else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
