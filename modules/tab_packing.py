import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.graph_objects as go

def render_packing(b_df, df_oe):
    st.markdown("<div class='section-header'><h3>⏱️ Analýza časů balení (End-to-End)</h3><p>Propojení délky balení u stolu s fyzickou náročností pickování v uličkách.</p></div>", unsafe_allow_html=True)
    
    if df_oe is not None and not df_oe.empty:
        if not b_df.empty:
            b_df_clean = b_df.copy()
            oe_clean = df_oe.copy()
            
            # 1. NEKOMPROMISNÍ ČIŠTĚNÍ ZAKÁZEK PRO PÁROVÁNÍ
            # (Odstraní desetinné .0, odstraní mezery, odstraní přední nuly)
            b_del_col = 'Delivery' if 'Delivery' in b_df_clean.columns else b_df_clean.columns[0]
            b_df_clean['Clean_Del'] = b_df_clean[b_del_col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
            
            oe_del_col = 'Delivery' if 'Delivery' in oe_clean.columns else oe_clean.columns[0]
            oe_clean['Clean_Del'] = oe_clean[oe_del_col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
            
            # Celkový počet načtených zakázek přímo ze souboru OE-Times
            total_oe = oe_clean['Clean_Del'].nunique()
            
            # 2. PROPOJENÍ ZAKÁZEK (INNER JOIN = Vezme jen to, co existuje v OBOCH souborech)
            e2e_df = pd.merge(b_df_clean, oe_clean, on='Clean_Del', how='inner', suffixes=('', '_oe'))
            
            if not e2e_df.empty:
                # Rozdělení na zakázky s platným časem (pro průměry) a všechny (pro celkový počet)
                valid_time_df = e2e_df[e2e_df['Process_Time_Min'] > 0].copy()
                
                if not valid_time_df.empty:
                    valid_time_df['Minut na 1 HU'] = np.where(valid_time_df['pocet_hu'] > 0, valid_time_df['Process_Time_Min'] / valid_time_df['pocet_hu'], 0)
                    valid_time_df['Pick Pohybů za 1 min balení'] = valid_time_df['pohyby_celkem'] / valid_time_df['Process_Time_Min']
                    
                    avg_time = valid_time_df['Process_Time_Min'].mean()
                    avg_spd = valid_time_df['Minut na 1 HU'].mean()
                else:
                    avg_time = 0
                    avg_spd = 0
                
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    with st.container(border=True): 
                        st.metric(
                            "Nahráno v OE-Times", 
                            f"{total_oe:,}", 
                            help="Celkový počet unikátních zakázek načtených ze souboru s časy balení."
                        )
                with c2:
                    with st.container(border=True): 
                        st.metric(
                            "✅ Zmapováno E2E", 
                            f"{len(e2e_df):,}", 
                            help="Zakázky, které se úspěšně propojily (průnik). Existují jak v OE-Times, tak v aktuálním Pick Reportu."
                        )
                with c3:
                    with st.container(border=True): 
                        st.metric("⏱️ Prům. čas balení", f"{avg_time:.1f} min")
                with c4:
                    with st.container(border=True): 
                        st.metric("📦 Rychlost (min/HU)", f"{avg_spd:.1f} min")

                with st.expander("🔍 Zobrazit rozpad nezmapovaných zakázek (Chybí v Pick Reportu)"):
                    missing_in_pick = oe_clean[~oe_clean['Clean_Del'].isin(b_df_clean['Clean_Del'])]
                    st.warning(f"Zde je seznam {len(missing_in_pick)} zakázek, které sice pracovníci zabalili u stolu (jsou v OE-Times), ale aplikace k nim nemá zdrojová data o fyzickém pickování. Je pravděpodobné, že byly pickovány v jiném období, než jaké pokrývá nahraný Pick Report.")
                    st.dataframe(missing_in_pick, use_container_width=True, hide_index=True)

                with st.expander("🔍 Zobrazit kompletní Master Data tabulku (Úspěšné E2E)"):
                    disp_cols = ['Delivery', 'CUSTOMER', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'Process_Time_Min']
                    avail_cols = [c for c in disp_cols if c in e2e_df.columns]
                    
                    disp_e2e = e2e_df[avail_cols].copy()
                    disp_e2e.rename(columns={'Process_Time_Min': 'Čas Balení (min)', 'pocet_to': 'Pick TO', 'pohyby_celkem': 'Pick Pohyby', 'pocet_hu': 'Výsledné HU'}, inplace=True)
                    st.dataframe(disp_e2e, use_container_width=True, hide_index=True)

        st.markdown("<div class='section-header'><h3>📊 Detailní rozpad časů a Obalů</h3></div>", unsafe_allow_html=True)
        sc1, sc2 = st.columns([1, 1.5])
        
        with sc1:
            st.markdown("**Nejpoužívanější obaly (KLT/Palety/Kartony)**")
            pack_stats = []
            for _, row in df_oe.iterrows():
                # Zde chceme načíst obaly pro VŠECH 1043 zakázek bez ohledu na párování
                for col in ['KLT', 'Palety', 'Cartons']:
                    if col in df_oe.columns and str(row[col]).strip() not in ['nan', '', 'None']:
                        val = str(row[col])
                        nums = re.findall(r'(\d+)', val)
                        count = sum(int(n) for n in nums) if nums else 1
                        mat_name = val.split('(')[0].strip() if '(' in val else val.strip()
                        pack_stats.append({'Obalový materiál': mat_name, 'Pouzito_ks': count})
            if pack_stats:
                p_df = pd.DataFrame(pack_stats).groupby('Obalový materiál')['Pouzito_ks'].sum().reset_index().sort_values('Pouzito_ks', ascending=False).head(10)
                p_df.columns = ["Typ obalu", "Použito kusů celkem"]
                st.dataframe(p_df, hide_index=True, use_container_width=True)
            else: 
                st.info("V datech nejsou specifikovány konkrétní obaly.")

        with sc2:
            st.markdown("**Trend průměrného času a počtu zabalených zakázek**")
            if not e2e_df.empty and 'Month' in e2e_df.columns and not valid_time_df.empty:
                tr_oe = valid_time_df.groupby('Month').agg(zak=('Clean_Del', 'nunique'), cas=('Process_Time_Min', 'mean')).reset_index()
                fig = go.Figure()
                fig.add_trace(go.Bar(x=tr_oe['Month'], y=tr_oe['zak'], name='Zabalené zakázky', marker_color='#6366f1', text=tr_oe['zak'], textposition='auto'))
                fig.add_trace(go.Scatter(x=tr_oe['Month'], y=tr_oe['cas'], name='Průměrný čas (min)', yaxis='y2', mode='lines+markers+text', text=tr_oe['cas'].round(1), textposition='top center', line=dict(color='#f59e0b', width=3)))
                fig.update_layout(yaxis2=dict(title="Čas (min)", side="right", overlaying="y", showgrid=False), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Nedostatek zmapovaných dat pro vykreslení trendu.")

        st.divider()
        st.markdown("### 🐌 Analýza 'Žroutů času' (Zpoždění)")
        eaters = []
        # Ošetření neviditelných mezer v názvech sloupců Excelu
        oe_cols_clean = {c.strip(): c for c in df_oe.columns}
        
        for col_clean in ['Scanning serial numbers', 'Reprinting labels', 'Difficult KLTs']:
            col = oe_cols_clean.get(col_clean, col_clean)
            if col in df_oe.columns and 'Process_Time_Min' in df_oe.columns:
                valid_oe = df_oe[df_oe['Process_Time_Min'] > 0]
                if not valid_oe.empty:
                    # Rozpoznání označení problému (Y, X, 1, atd.)
                    mask_valid = valid_oe[col].astype(str).str.strip().str.upper().isin(['Y', 'X', 'YES', 'ANO', '1', 'TRUE']) | (pd.to_numeric(valid_oe[col], errors='coerce').fillna(0) > 0)
                    with_flag = valid_oe[mask_valid]['Process_Time_Min'].mean()
                    without_flag = valid_oe[~mask_valid]['Process_Time_Min'].mean()
                    
                    if pd.notna(with_flag) and pd.notna(without_flag):
                        eaters.append({"Událost": col_clean, "Prům. čas (Pokud nastane)": with_flag, "Prům. čas (Běžně)": without_flag, "Rozdíl (Zpoždění)": with_flag - without_flag})
        
        if eaters:
            edf = pd.DataFrame(eaters).sort_values("Rozdíl (Zpoždění)", ascending=False)
            st.dataframe(edf.style.format("{:.1f} min", subset=["Prům. čas (Pokud nastane)", "Prům. čas (Běžně)", "Rozdíl (Zpoždění)"]), hide_index=True, use_container_width=True)
        else:
            st.success("V aktuálních datech nebyly detekovány žádné významné příznaky zpoždění nebo na ně nebylo evidováno dostatek dat.")
    else:
        st.warning("⚠️ V databázi chybí tabulka s časy balení (OE-Times).")
