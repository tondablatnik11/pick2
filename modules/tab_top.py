import streamlit as st
import pandas as pd
from modules.utils import t

def render_top(df_pick):
    st.markdown(f"<div class='section-header'><h3>🏆 TOP 100 materiálů podle Queue</h3></div>", unsafe_allow_html=True)
    q_options = ["Všechny Queue dohromady"] + sorted(df_pick['Queue'].dropna().unique().tolist())
    selected_queue_disp = st.selectbox("Zobrazit TOP 100 pro:", options=q_options)

    df_top_filter = df_pick if selected_queue_disp == "Všechny Queue dohromady" else df_pick[df_pick['Queue'] == selected_queue_disp]

    if not df_top_filter.empty:
        agg = df_top_filter.groupby('Material').agg(
            pocet_picku=('Material', 'count'), celkove_mnozstvi=('Qty', 'sum'),
            celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'),
            pohyby_miss=('Pohyby_Loose_Miss', 'sum'), celkova_vaha=('Celkova_Vaha_KG', 'sum')
        ).reset_index()

        agg.rename(columns={'Material': "Materiál", 'pocet_picku': "Řádky", 'celkove_mnozstvi': "Kusů celkem", 'celkem_pohybu': "Celkem pohybů", 'pohyby_exact': "Pohyby (Přesně)", 'pohyby_miss': "Pohyby (Odhady)", 'celkova_vaha': "Hmotnost (kg)"}, inplace=True)

        top_100_df = agg.sort_values(by="Celkem pohybů", ascending=False).head(100)[["Materiál", "Řádky", "Kusů celkem", "Hmotnost (kg)", "Pohyby (Přesně)", "Pohyby (Odhady)", "Celkem pohybů"]]

        fmt_top = {"Hmotnost (kg)": "{:.1f}"}
        for c in top_100_df.columns:
            if c not in ["Materiál", "Hmotnost (kg)"]: fmt_top[c] = "{:.0f}"

        col_q1, col_q2 = st.columns([1.5, 1])
        with col_q1:
            st.dataframe(top_100_df.style.format(fmt_top), use_container_width=True, hide_index=True)
        with col_q2:
            st.bar_chart(top_100_df.set_index("Materiál")["Celkem pohybů"])

    st.divider()
    st.subheader("Materiály s chybějícími daty o balení (Žebříček odhadů)")
    all_mat_agg = df_pick.groupby('Material').agg(
        lines=('Material', 'count'), qty=('Qty', 'sum'), miss=('Pohyby_Loose_Miss', 'sum'), mov=('Pohyby_Rukou', 'sum')
    ).reset_index()
    all_mat_agg.columns = ["Materiál", "Řádky", "Kusů celkem", "Pohyby (Odhady)", "Celkem pohybů"]
    miss_df = all_mat_agg[all_mat_agg["Pohyby (Odhady)"] > 0].sort_values(by="Pohyby (Odhady)", ascending=False).head(100)

    if not miss_df.empty:
        st.dataframe(miss_df.style.format({c: "{:.0f}" for c in ["Pohyby (Odhady)", "Celkem pohybů"]}), use_container_width=True, hide_index=True)
    else:
        st.success("✅ Všechna data o baleních jsou k dispozici — žádné odhady!")
