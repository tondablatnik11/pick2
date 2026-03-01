import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.graph_objects as go
from modules.utils import t

def render_packing(b_df, df_oe):
    st.markdown("<div class='section-header'><h3>⏱️ Analýza časů balení (End-to-End)</h3><p>Propojení délky balení u stolu s fyzickou náročností pickování v uličkách.</p></div>", unsafe_allow_html=True)
    
    if df_oe is not None and not df_oe.empty:
        if not b_df.empty:
            # --- OPRAVA PÁROVÁNÍ ---
            b_df['Clean_Del'] = b_df['Delivery'].astype(str).str.strip().str.lstrip('0')
            df_oe['Clean_Del'] = df_oe['Delivery'].astype(str).str.strip().str.lstrip('0')
            
            e2e_df = pd.merge(b_df, df_oe, on='Clean_Del', how='inner', suffixes=('', '_oe'))
            e2e_df = e2e_df[e2e_df['Process_Time_Min'] > 0].copy()
            
            if not e2e_df.empty:
                e2e_df['Minut na 1 HU'] = np.where(e2e_df['pocet_hu'] > 0, e2e_df['Process_Time_Min'] / e2e_df['pocet_hu'], 0)
                e2e_df['Pick Pohybů za 1 min balení'] = e2e_df['pohyby_celkem'] / e2e_df['Process_Time_Min']
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    with st.container(border=True): st.metric("✅ Zmapováno zakázek E2E", f"{len(e2e_df):,}")
                with c2:
                    with st.container(border=True): st.metric("⏱️ Prům. čas balení zakázky", f"{e2e_df['Process_Time_Min'].mean():.1f} min")
                with c3:
                    with st.container(border=True): st.metric("📦 Prům. rychlost balení", f"{e2e_df['Minut na 1 HU'].mean():.1f} min / 1 HU")

                with st.expander("🔍 Zobrazit kompletní Master Data tabulku (Pick -> Balení)"):
                    disp_e2e = e2e_df[['Delivery', 'CUSTOMER', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'Process_Time_Min', 'Minut na 1 HU', 'Pick Pohybů za 1 min balení']].copy()
                    disp_e2e.columns = ["Delivery", "Zákazník", "Pick TO", "Pick Pohyby", "Výsledné HU", "Čas Balení (min)", "Minut na 1 HU", "Pohybů / min balení"]
                    st.dataframe(disp_e2e.style.format("{:.1f}", subset=["Čas Balení (min)", "Minut na 1 HU", "Pohybů / min balení"]), use_container_width=True, hide_index=True)

        st.markdown("<div class='section-header'><h3>📊 Detailní rozpad časů a Obalů</h3></div>", unsafe_allow_html=True)
        sc1, sc2 = st.columns([1, 1.5])
        
        with sc1:
            st.markdown("**Nejpoužívanější obaly (KLT/Palety/Kartony)**")
            pack_stats = []
            for _, row in df_oe.iterrows():
                if row.get('Process_Time_Min', 0) <= 0: continue
                for col in ['KLT', 'Palety', 'Cartons']:
                    if col in df_oe.columns and str(row[col]).strip() not in ['nan', '', 'None']:
                        val = str(row[col])
                        nums = re.findall(r'(\d+)', val)
                        count = sum(int(n) for n in nums) if nums else 1
                        pack_stats.append({'Obalový materiál': val.split('(')[0].strip() if '(' in val else val.strip(), 'Pouzito_ks': count})
            if pack_stats:
                p_df = pd.DataFrame(pack_stats).groupby('Obalový materiál')['Pouzito_ks'].sum().reset_index().sort_values('Pouzito_ks', ascending=False).head(10)
                p_df.columns = ["Typ obalu", "Použito kusů celkem"]
                st.dataframe(p_df, hide_index=True, use_container_width=True)
            else: st.info("V datech nejsou specifikovány konkrétní obaly.")

        with sc2:
            st.markdown("**Trend průměrného času a počtu zabalených zakázek**")
            if not e2e_df.empty and 'Month' in e2e_df.columns:
                tr_oe = e2e_df.groupby('Month').agg(zak=('Clean_Del', 'nunique'), cas=('Process_Time_Min', 'mean')).reset_index()
                fig = go.Figure()
                fig.add_trace(go.Bar(x=tr_oe['Month'], y=tr_oe['zak'], name='Zabalené zakázky', marker_color='#6366f1'))
                fig.add_trace(go.Scatter(x=tr_oe['Month'], y=tr_oe['cas'], name='Průměrný čas (min)', yaxis='y2', mode='lines+markers', line=dict(color='#f59e0b', width=3)))
                fig.update_layout(yaxis2=dict(title="Čas (min)", side="right", overlaying="y", showgrid=False), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.markdown("### 🐌 Analýza 'Žroutů času' (Zpoždění)")
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
            st.success("V aktuálních datech nebyly detekovány žádné systémové příznaky zpoždění (sériová čísla atd.).")
    else:
        st.warning("⚠️ V databázi chybí tabulka s časy balení (OE-Times).")
