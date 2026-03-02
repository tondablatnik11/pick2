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
    
    # KROK 1: Spočítáme statistiky pro každý jednotlivý pickovací úkol (TO)
    to_group = df_pick.groupby(queue_count_col).agg(
        Queue=('Queue', 'first'),
        lokace_v_to=('Source Storage Bin', 'nunique'), # Počet zastávek u regálu
        kusy_v_to=('Qty', 'sum'),
        pohyby_v_to=('Pohyby_Rukou', 'sum'),
        exact_poh=('Pohyby_Exact', 'sum'),
        miss_poh=('Pohyby_Loose_Miss', 'sum'),
        pocet_mat=('Material', 'nunique'),             # Zjištění, zda jde o Single nebo Mix
        Delivery=('Delivery', 'first')
    ).reset_index()

    # OPRAVA CHYBĚJÍCÍ FUNKCE: Rozřazení paletových front na Single a Mix
    def split_queue(row):
        q = str(row['Queue']).strip()
        if q in ['PI_PL', 'PI_PL_OE']:
            if row['pocet_mat'] <= 1:
                return f"{q} (Single)"
            else:
                return f"{q} (Mix)"
        return q

    to_group['Queue_Split'] = to_group.apply(split_queue, axis=1)

    # KROK 2: Nyní sečteme tyto reálné zastávky z TO do finální kategorie (Queue)
    q_agg = to_group.groupby('Queue_Split').agg(
        pocet_to=(queue_count_col, 'nunique'),
        zakazky=('Delivery', 'nunique'),
        lokace_celkem=('lokace_v_to', 'sum'),
        kusy_celkem=('kusy_v_to', 'sum'),
        pohyby_celkem=('pohyby_v_to', 'sum'),
        exact_celkem=('exact_poh', 'sum'),
        miss_celkem=('miss_poh', 'sum')
    ).reset_index()

    # Výpočty přesných průměrů
    q_agg['prum_lok_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['lokace_celkem'] / q_agg['pocet_to'], 0)
    q_agg['prum_ks_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['kusy_celkem'] / q_agg['pocet_to'], 0)
    q_agg['prum_poh_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['pohyby_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['prum_exact_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['exact_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['prum_miss_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['miss_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['pct_exact'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['exact_celkem'] / q_agg['pohyby_celkem'] * 100, 0)
    q_agg['pct_miss'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['miss_celkem'] / q_agg['pohyby_celkem'] * 100, 0)

    q_agg['Queue_Desc'] = q_agg['Queue_Split'].map(QUEUE_DESC).fillna(t('unknown'))
    
    # Výběr sloupců
    disp_q = q_agg[['Queue_Split', 'Queue_Desc', 'pocet_to', 'zakazky', 'prum_lok_to', 'prum_ks_to', 'prum_poh_lok', 'prum_exact_lok', 'pct_exact', 'prum_miss_lok', 'pct_miss']].copy()
    disp_q.columns = [
        "Queue", 
        "Popis fronty", 
        "Počet TO", 
        "Zasažených zakázek", 
        "Průměr lokací (zastávek) / TO", 
        "Průměr kusů / TO", 
        "Průměr pohybů na 1 lokaci", 
        "Pohyby přesně / lok.", 
        "% Přesně", 
        "Pohyby odhad / lok.", 
        "% Odhad"
    ]
    
    st.dataframe(disp_q.style.format({
        "Průměr lokací (zastávek) / TO": "{:.1f}", 
        "Průměr kusů / TO": "{:.1f}", 
        "Průměr pohybů na 1 lokaci": "{:.2f}",
        "Pohyby přesně / lok.": "{:.2f}", 
        "Pohyby odhad / lok.": "{:.2f}",
        "% Přesně": "{:.1f}%", 
        "% Odhad": "{:.1f}%"
    }), hide_index=True, use_container_width=True)

    # --- 3. GRAF: Měsíční trend podle Queue ---
    st.markdown(f"<div class='section-header'><h3>📈 Trend náročnosti v čase podle Queue</h3></div>", unsafe_allow_html=True)
    
    if 'Month' in df_pick.columns:
        # Propagujeme správné Queue kategorie i zpět do původní tabulky, aby graf fungoval
        q_split_map = to_group.set_index(queue_count_col)['Queue_Split'].to_dict()
        df_pick['Queue_Split_Graf'] = df_pick[queue_count_col].map(q_split_map).fillna(df_pick['Queue'])

        valid_queues = sorted([q for q in df_pick['Queue_Split_Graf'].dropna().unique() if q != 'N/A'])
        
        selected_queues = st.multiselect(
            "Zvolte Queue pro zobrazení v grafu (můžete vybrat libovolný počet):",
            options=valid_queues,
            default=valid_queues[:3] if len(valid_queues) >= 3 else valid_queues
        )
        
        if selected_queues:
            trend_df = df_pick[df_pick['Queue_Split_Graf'].isin(selected_queues)]
            
            trend_to_group = trend_df.groupby(['Month', queue_count_col]).agg(
                Queue_Split=('Queue_Split_Graf', 'first'),
                lokace=('Source Storage Bin', 'nunique'),
                pohyby=('Pohyby_Rukou', 'sum')
            ).reset_index()

            trend_agg = trend_to_group.groupby(['Month', 'Queue_Split']).agg(
                to_count=(queue_count_col, 'nunique'),
                loc_count=('lokace', 'sum'),
                moves_count=('pohyby', 'sum')
            ).reset_index()
            
            trend_agg['prum_poh_lok'] = np.where(trend_agg['loc_count'] > 0, trend_agg['moves_count'] / trend_agg['loc_count'], 0)
            
            fig = go.Figure()
            colors = px.colors.qualitative.Plotly 
            
            for i, q in enumerate(selected_queues):
                q_data = trend_agg[trend_agg['Queue_Split'] == q].sort_values('Month')
                color = colors[i % len(colors)]
                
                if not q_data.empty:
                    fig.add_trace(go.Bar(
                        x=q_data['Month'], 
                        y=q_data['to_count'], 
                        name=f"{q} (Počet TO)", 
                        marker_color=color,
                        opacity=0.7,
                        offsetgroup=i
                    ))
                    
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
