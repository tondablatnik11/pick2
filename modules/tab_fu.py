import streamlit as st
import pandas as pd
from modules.utils import t

def render_fu(df_pick, queue_count_col):
    st.markdown(f"<div class='section-header'><h3>🏭 Analýza front PI_PL_FU a PI_PL_FUOE</h3><p>Rozpad picků podle typu skladovací jednotky (Storage Unit Type).</p></div>", unsafe_allow_html=True)
    df_fu = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()

    if not df_fu.empty:
        if 'Storage Unit Type' in df_fu.columns:
            def categorize_su(su):
                su = str(su).strip().upper()
                if su == 'K1': return 'KLT'
                elif su in ['EP1', 'EP2', 'EP3', 'EP4']: return 'Paleta'
                elif su in ['', 'NAN', 'NONE']: return 'Nezadáno'
                else: return 'Ostatní'

            df_fu['SU_Category'] = df_fu['Storage Unit Type'].apply(categorize_su)
            df_fu['Storage Unit Type'] = df_fu['Storage Unit Type'].fillna('N/A')

            fu_agg = df_fu.groupby(['SU_Category', 'Storage Unit Type']).agg(
                pocet_radku=('Material', 'count'), pocet_to=(queue_count_col, 'nunique'), celkem_kusu=('Qty', 'sum')
            ).reset_index()

            fu_agg.columns = ["Typ balení", "Kód jednotky", "Počet picků (Řádky)", "Počet TO", "Kusů celkem"]
            fu_agg = fu_agg.sort_values(by="Počet picků (Řádky)", ascending=False)

            col_fu1, col_fu2 = st.columns([3, 2])
            with col_fu1:
                st.dataframe(fu_agg.style.format({"Kusů celkem": "{:,.0f}"}), use_container_width=True, hide_index=True)
            with col_fu2:
                chart_data = fu_agg.groupby("Typ balení")["Počet picků (Řádky)"].sum()
                st.bar_chart(chart_data)
        else: st.warning("❌ Sloupec 'Storage Unit Type' nebyl v nahraném Pick reportu nalezen.")
    else: st.info("ℹ️ Pro vybrané období a filtry nebyly nalezeny žádné záznamy pro fronty PI_PL_FU a PI_PL_FUOE.")
