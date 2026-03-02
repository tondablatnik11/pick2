import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t, QUEUE_DESC

def render_dashboard(df_pick, queue_count_col):
    # --- 1. Spolehlivost dat (Data Quality) ---
    st.markdown(f"<div class='section-header'><h3>{t('sec_ratio')}</h3><p>{t('ratio_desc')}</p></div>", unsafe_allow_html=True)
    
    total_moves = df_pick['Pohyby_Rukou'].sum()
    exact_moves = df_pick['Pohyby_Exact'].sum()
    miss_moves = df_pick['Pohyby_Loose_Miss'].sum()
    pct_exact = (exact_moves / total_moves * 100) if total_moves > 0 else 0
    pct_miss = (miss_moves / total_moves * 100) if total_moves > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric(t('ratio_moves'), f"{int(total_moves):,}")
    c2.metric(t('ratio_exact'), f"{int(exact_moves):,} ({pct_exact:.1f} %)")
    c3.metric(t('ratio_miss'), f"{int(miss_moves):,} ({pct_miss:.1f} %)")

    with st.expander(t('exp_missing_data')):
        miss_df = df_pick[df_pick['Pohyby_Loose_Miss'] > 0].groupby('Material').agg(
            Odhad_Pohybu=('Pohyby_Loose_Miss', 'sum'),
            Kusu=('Qty', 'sum')
        ).reset_index().sort_values('Odhad_Pohybu', ascending=False)
        st.dataframe(miss_df, hide_index=True, use_container_width=True)

    # --- 2. Tabulka průměrné náročnosti (Queue Table) ---
    st.markdown(f"<div class='section-header'><h3>{t('sec_queue_title')}</h3></div>", unsafe_allow_html=True)
    
    q_agg = df_pick.groupby('Queue').agg(
        pocet_to=(queue_count_col, 'nunique'),
        zakazky=('Delivery', 'nunique'),
        lokace=('Source Storage Bin', 'nunique'),
        kusy=('Qty', 'sum'),
        pohyby=('Pohyby_Rukou', 'sum'),
        exact_poh=('Pohyby_Exact', 'sum'),
        miss_poh=('Pohyby_Loose_Miss', 'sum')
    ).reset_index()

    q_agg['prum_lok'] = np.where(q_agg['pocet_to'] > 0, q_agg['lokace'] / q_agg['pocet_to'], 0)
    q_agg['prum_ks'] = np.where(q_agg['pocet_to'] > 0, q_agg['kusy'] / q_agg['pocet_to'], 0)
    q_agg['prum_poh_lok'] = np.where(q_agg['lokace'] > 0, q_agg['pohyby'] / q_agg['lokace'], 0)
    q_agg['prum_exact_lok'] = np.where(q_agg['lokace'] > 0, q_agg['exact_poh'] / q_agg['lokace'], 0)
    q_agg['prum_miss_lok'] = np.where(q_agg['lokace'] > 0, q_agg['miss_poh'] / q_agg['lokace'], 0)
    q_agg['pct_exact'] = np.where(q_agg['pohyby'] > 0, q_agg['exact_poh'] / q_agg['pohyby'] * 100, 0)
    q_agg['pct_miss'] = np.where(q_agg['pohyby'] > 0, q_agg['miss_poh'] / q_agg['pohyby'] * 100, 0)

    q_agg['Queue_Desc'] = q_agg['Queue'].map(QUEUE_DESC).fillna(t('unknown'))
    disp_q = q_agg[['Queue', 'Queue_Desc', 'pocet_to', 'zakazky', 'prum_lok', 'prum_ks', 'prum_poh_lok', 'prum_exact_lok', 'pct_exact', 'prum_miss_lok', 'pct_miss']].copy()
    disp_q.columns = [t('q_col_queue'), t('q_col_desc'), t('q_col_to'), t('q_col_orders'), t('q_col_loc'), t('q_col_pcs'), t('q_col_mov_loc'), t('q_col_exact_loc'), t('q_pct_exact'), t('q_col_miss_loc'), t('q_pct_miss')]
    
    st.dataframe(disp_q.style.format({
        t('q_col_loc'): "{:.1f}", t('q_col_pcs'): "{:.1f}", t('q_col_mov_loc'): "{:.2f}",
        t('q_col_exact_loc'): "{:.2f}", t('q_col_miss_loc'): "{:.2f}",
        t('q_pct_exact'): "{:.1f}%", t('q_pct_miss'): "{:.1f}%"
    }), hide_index=True, use_container_width=True)

    # --- 3. NOVÝ GRAF: Měsíční trend podle Queue ---
    st.markdown(f"<div class='section-header'><h3>📈 Trend náročnosti v čase podle Queue</h3></div>", unsafe_allow_html=True)
    
    if 'Month' in df_pick.columns:
        valid_queues = sorted([q for q in df_pick['Queue'].dropna().unique() if q != 'N/A'])
        
        # Výběr Queue - defaultně vybere první 3, aby graf nebyl hned na začátku přeplácaný
        selected_queues = st.multiselect(
            "Zvolte Queue pro zobrazení v grafu (můžete vybrat libovolný počet):",
            options=valid_queues,
            default=valid_queues[:3] if len(valid_queues) >= 3 else valid_queues
        )
        
        if selected_queues:
            trend_df = df_pick[df_pick['Queue'].isin(selected_queues)]
            
            trend_agg = trend_df.groupby(['Month', 'Queue']).agg(
                to_count=(queue_count_col, 'nunique'),
                loc_count=('Source Storage Bin', 'nunique'),
                moves_count=('Pohyby_Rukou', 'sum')
            ).reset_index()
            
            trend_agg['prum_poh_lok'] = np.where(trend_agg['loc_count'] > 0, trend_agg['moves_count'] / trend_agg['loc_count'], 0)
            
            fig = go.Figure()
            colors = px.colors.qualitative.Plotly # Konzistentní barevná paleta
            
            for i, q in enumerate(selected_queues):
                q_data = trend_agg[trend_agg['Queue'] == q].sort_values('Month')
                color = colors[i % len(colors)]
                
                if not q_data.empty:
                    # Sloupce pro Počet TO
                    fig.add_trace(go.Bar(
                        x=q_data['Month'], 
                        y=q_data['to_count'], 
                        name=f"{q} (Počet TO)", 
                        marker_color=color,
                        opacity=0.7,
                        offsetgroup=i
                    ))
                    
                    # Čáry pro Průměr pohybů na lokaci
                    fig.add_trace(go.Scatter(
                        x=q_data['Month'], 
                        y=q_data['prum_poh_lok'], 
                        name=f"{q} (Pohybů/lokaci)", 
                        mode='lines+markers+text', 
                        text=q_data['prum_poh_lok'].round(1),
                        textposition='top center',
                        yaxis='y2',
                        line=dict(color=color, width=3),
                        marker=dict(symbol='diamond', size=8)
                    ))
            
            fig.update_layout(
                barmode='group',
                yaxis=dict(title="Celkový počet TO"),
                yaxis2=dict(title="Průměr pohybů na lokaci", side="right", overlaying="y", showgrid=False),
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0), 
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Prosím vyberte alespoň jednu Queue pro zobrazení grafu.")
    else:
        st.info("Data neobsahují informace o měsíci.")

    return disp_q
