import streamlit as st
import pandas as pd
import plotly.express as px

def render_fu(df_pick, queue_count_col):
    st.markdown(f"<div class='section-header'><h3>🏭 Analýza front PI_PL_FU a PI_PL_FUOE</h3></div>", unsafe_allow_html=True)
    df_fu = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()

    if not df_fu.empty:
        if 'Storage Unit Type' in df_fu.columns:
            def categorize_su(su):
                su = str(su).strip().upper()
                if su in ['K1', 'K4']: return 'KLT'
                elif su in ['EP1', 'EP2', 'EP3', 'EP4']: return 'Paleta'
                elif su in ['', 'NAN', 'NONE']: return 'Nezadáno'
                else: return 'Ostatní'

            df_fu['SU_Category'] = df_fu['Storage Unit Type'].apply(categorize_su)
            df_fu['Storage Unit Type'] = df_fu['Storage Unit Type'].fillna('N/A')

            # --- UKAZATEL KLT vs PALETA ---
            klt_count = len(df_fu[df_fu['SU_Category'] == 'KLT'])
            pal_count = len(df_fu[df_fu['SU_Category'] == 'Paleta'])
            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Pickováno KLT", f"{klt_count:,}")
            c2.metric("🏭 Pickováno Palet", f"{pal_count:,}")
            c3.metric("❓ Ostatní / Nezadáno", f"{len(df_fu) - klt_count - pal_count:,}")

            # --- TABULKA DETAILU ---
            fu_agg = df_fu.groupby(['SU_Category', 'Storage Unit Type']).agg(
                pocet_radku=('Material', 'count'), pocet_to=(queue_count_col, 'nunique'), celkem_kusu=('Qty', 'sum')
            ).reset_index()
            fu_agg.columns = ["Kategorie", "Kód jednotky (SUT)", "Počet picků (Řádky)", "Počet TO", "Kusů celkem"]
            fu_agg = fu_agg.sort_values(by="Počet picků (Řádky)", ascending=False)
            
            st.divider()
            col_fu1, col_fu2 = st.columns([1, 1])
            with col_fu1:
                st.markdown("**Detailní rozpad podle SUT**")
                st.dataframe(fu_agg.style.format({"Kusů celkem": "{:,.0f}"}), use_container_width=True, hide_index=True)
            
            with col_fu2:
                # --- TREND GRAF ---
                st.markdown("**Vývoj pickování podle měsíců**")
                if 'Month' in df_fu.columns:
                    trend_df = df_fu.groupby(['Month', 'SU_Category']).size().reset_index(name='Pocet')
                    fig = px.bar(trend_df, x='Month', y='Pocet', color='SU_Category', barmode='stack', color_discrete_map={'KLT': '#38bdf8', 'Paleta': '#818cf8', 'Ostatní': '#94a3b8', 'Nezadáno': '#cbd5e1'})
                    fig.update_layout(xaxis_title="", yaxis_title="Počet picků", margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig, use_container_width=True)
        else: st.warning("❌ Sloupec 'Storage Unit Type' nebyl v nahraném Pick reportu nalezen.")
    else: st.info("ℹ️ Žádné záznamy pro fronty PI_PL_FU a PI_PL_FUOE.")
