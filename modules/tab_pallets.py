import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import t

def render_pallets(df_pick):
    st.markdown(f"<div class='section-header'><h3>🎯 Analýza paletových zakázek (Mix Pallet)</h3><p>*(Počítáno výhradně z front PI_PL a PI_PL_OE)*</p></div>", unsafe_allow_html=True)

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
            max_rozmer=('Piece_Max_Dim_CM', 'first')
        )
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

            tot_p_pal = filtered_orders['celkem_pohybu'].sum()
            if tot_p_pal > 0:
                st.markdown("**Podíl z celkového počtu POHYBŮ:**")
                c_p1, c_p2 = st.columns(2)
                c_p1.metric("Přesně (Krabice / Palety / Volné)", f"{filtered_orders['pohyby_exact'].sum() / tot_p_pal * 100:.1f} %")
                c_p2.metric("Odhady (Chybí balení)", f"{filtered_orders['pohyby_miss'].sum() / tot_p_pal * 100:.1f} %", delta_color="inverse")

            with st.expander("Zobrazit tabulku zakázek (1 materiál)"):
                display_df = filtered_orders[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer', 'certs']].copy()
                display_df.columns = ["Materiál", "Kusů celkem", "Celkem pohybů", "Pohyby (Přesně)", "Pohyby (Odhady)", "Hmotnost (kg)", "Rozměr (cm)", "Certifikát"]
                st.dataframe(display_df, use_container_width=True, hide_index=True)
        else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
    else: st.warning("Nenalezeny žádné zakázky pro zobrazení.")
