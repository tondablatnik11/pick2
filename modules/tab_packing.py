import streamlit as st
import pandas as pd
import numpy as np
import re
from modules.utils import t

def render_packing(b_df, df_oe):
    st.markdown("<div class='section-header'><h3>⏱️ Analýza časů balení (End-to-End)</h3><p>Propojení délky balení u stolu s fyzickou náročností pickování v uličkách.</p></div>", unsafe_allow_html=True)
    
    if df_oe is not None and not df_oe.empty:
        if not b_df.empty:
            e2e_df = pd.merge(b_df, df_oe, on='Delivery', how='inner')
            e2e_df = e2e_df[e2e_df['Process_Time_Min'] > 0].copy()
            
            if not e2e_df.empty:
                e2e_df['Minut na 1 HU'] = np.where(e2e_df['pocet_hu'] > 0, e2e_df['Process_Time_Min'] / e2e_df['pocet_hu'], 0)
                e2e_df['Pick Pohybů za 1 min balení'] = e2e_df['pohyby_celkem'] / e2e_df['Process_Time_Min']
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    with st.container(border=True): st.metric("Zmapováno zakázek E2E", f"{len(e2e_df):,}")
                with c2:
                    with st.container(border=True): st.metric("Prům. čas balení zakázky", f"{e2e_df['Process_Time_Min'].mean():.1f} min")
                with c3:
                    with st.container(border=True): st.metric("Prům. rychlost balení", f"{e2e_df['Minut na 1 HU'].mean():.1f} min / 1 HU")

                with st.expander("🔍 Zobrazit kompletní Master Data tabulku (Pick -> Balení)"):
                    disp_e2e = e2e_df[['Delivery', 'CUSTOMER', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'Process_Time_Min', 'Minut na 1 HU', 'Pick Pohybů za 1 min balení']].copy()
                    disp_e2e.columns = ["Delivery", "Zákazník", "Pick TO", "Pick Pohyby", "Výsledné HU", "Čas Balení (min)", "Minut na 1 HU", "Pohybů / min balení"]
                    st.dataframe(disp_e2e.style.format("{:.1f}", subset=["Čas Balení (min)", "Minut na 1 HU", "Pohybů / min balení"]), use_container_width=True, hide_index=True)

        st.markdown("<div class='section-header'><h3>📊 Detailní rozpad časů</h3></div>", unsafe_allow_html=True)
        sc1, sc2, sc3 = st.columns(3)
        
        with sc1:
            st.markdown("**Podle Zákazníka**")
            cust_agg = df_oe[df_oe['Process_Time_Min'] > 0].groupby('CUSTOMER').agg(Zakazky=('Delivery', 'nunique'), Prum_Cas=('Process_Time_Min', 'mean')).reset_index().sort_values('Prum_Cas', ascending=False)
            st.dataframe(cust_agg.style.format({'Prum_Cas': '{:.1f} min'}), hide_index=True, use_container_width=True)

        with sc2:
            st.markdown("**Podle Materiálu**")
            mat_agg = df_oe[(df_oe['Process_Time_Min'] > 0) & (df_oe['Material'].notna())].groupby('Material').agg(Zakazky=('Delivery', 'nunique'), Prum_Cas=('Process_Time_Min', 'mean')).reset_index().sort_values('Prum_Cas', ascending=False).head(20)
            st.dataframe(mat_agg.style.format({'Prum_Cas': '{:.1f} min'}), hide_index=True, use_container_width=True)

        with sc3:
            st.markdown("**Podle Obalu (KLT, Palety, Kartony)**")
            pack_stats = []
            for _, row in df_oe.iterrows():
                time_min = row.get('Process_Time_Min', 0)
                if time_min <= 0: continue
                for col in ['KLT', 'Palety', 'Cartons']:
                    if col in df_oe.columns and str(row[col]).strip().lower() not in ['nan', '', 'none']:
                        matches = re.findall(r'([^,;]+?)\s*\(\s*(\d+)\s*[xX]\s*\)', str(row[col]))
                        for m in matches: pack_stats.append({'Obal': m[0].strip(), 'Cas_Zakazky': time_min, 'Pouzito_ks': int(m[1])})
            if pack_stats:
                p_df = pd.DataFrame(pack_stats)
                p_agg = p_df.groupby('Obal').agg(Vyskyt_v_Zakazkach=('Cas_Zakazky', 'count'), Prum_Cas_Cele_Zakazky=('Cas_Zakazky', 'mean')).reset_index().sort_values('Prum_Cas_Cele_Zakazky', ascending=False)
                st.dataframe(p_agg.style.format({'Prum_Cas_Cele_Zakazky': '{:.1f} min'}), hide_index=True, use_container_width=True)

        st.markdown("<div class='section-header'><h3>🐌 Analýza 'Žroutů času' (Zpoždění)</h3></div>", unsafe_allow_html=True)
        eaters = []
        for col in ['Scanning serial numbers', 'Reprinting labels ', 'Difficult KLTs']:
            if col in df_oe.columns:
                mask = df_oe[col].astype(str).str.strip().str.upper().isin(['Y', 'X', 'YES', 'ANO', '1']) | (pd.to_numeric(df_oe[col], errors='coerce').fillna(0) > 0)
                with_flag = df_oe[mask]['Process_Time_Min'].mean()
                without_flag = df_oe[~mask]['Process_Time_Min'].mean()
                if pd.notna(with_flag) and pd.notna(without_flag):
                    eaters.append({"Událost": col, "Prům. čas (Pokud nastane)": with_flag, "Prům. čas (Běžně)": without_flag, "Rozdíl (Zpoždění)": with_flag - without_flag})
        
        if eaters:
            edf = pd.DataFrame(eaters).sort_values("Rozdíl (Zpoždění)", ascending=False)
            st.dataframe(edf.style.format("{:.1f} min", subset=["Prům. čas (Pokud nastane)", "Prům. čas (Běžně)", "Rozdíl (Zpoždění)"]), hide_index=True, use_container_width=True)
    else:
        st.warning("⚠️ V databázi chybí tabulka s časy balení (OE-Times.xlsx).")
