import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

def render_pallets(df_pick):
    st.markdown(f"<div class='section-header'><h3>🎯 Analýza paletových zakázek (Mix Pallet)</h3></div>", unsafe_allow_html=True)

    df_pallets_clean = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
    if not df_pallets_clean.empty:
        grouped_orders = df_pallets_clean.groupby('Delivery').agg(
            num_materials=('Material', 'nunique'), total_qty=('Qty', 'sum'), num_positions=('Source Storage Bin', 'nunique'),
            celkem_pohybu=('Pohyby_Rukou', 'sum'), Month=('Month', 'first')
        )
        filtered_orders = grouped_orders[grouped_orders['num_materials'] == 1].copy()

        if not filtered_orders.empty:
            filtered_orders['mov_per_loc'] = np.where(filtered_orders['num_positions'] > 0, filtered_orders['celkem_pohybu'] / filtered_orders['num_positions'], 0)
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Počet zakázek", f"{len(filtered_orders):,}".replace(',', ' '))
            c2.metric("Prům. kusů / zakázku", f"{filtered_orders['total_qty'].mean():.1f}")
            c3.metric("Prům. pozic / zakázku", f"{filtered_orders['num_positions'].mean():.2f}")
            c4.metric("Prům. fyz. pohybů na lokaci", f"{filtered_orders['mov_per_loc'].mean():.1f}")

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
        else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
    else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
