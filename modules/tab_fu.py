import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from database import load_from_db
from modules.utils import t

def render_fu(df_pick, queue_count_col):
    st.markdown(f"<div class='section-header'><h3>🏭 {t('fu_title')}</h3><p>{t('fu_desc')}</p></div>", unsafe_allow_html=True)
    
    # 1. Filtrace pouze na paletové fronty (FU / FUOE)
    fu_df = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()
    
    if fu_df.empty:
        st.info("V datech chybí záznamy pro fronty PI_PL_FU nebo PI_PL_FUOE.")
        return
        
    c_su = 'Storage Unit Type' if 'Storage Unit Type' in fu_df.columns else ('Type' if 'Type' in fu_df.columns else None)
    
    # Funkce pro vyloučení KLT / K1 (aplikováno hned na začátku pro celou záložku)
    def is_klt_func(su_val):
        v = str(su_val).upper().strip()
        # Vyloučí K1, KLT, nebo jakýkoliv dvoumístný kód začínající na K (např. K2, K3)
        return v in ['K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'] or (v.startswith('K') and len(v) <= 2)
        
    fu_df['Is_KLT'] = fu_df[c_su].apply(is_klt_func) if c_su else False
    fu_df['Typ_Obalu'] = np.where(fu_df['Is_KLT'], 'KLT krabička', 'Paleta')

    # --- 2. Základní přehled (Storage Unit Type - KLT vs Palety) ---
    if c_su:
        st.markdown("### 🏷️ Měsíční podíl pickovaných Palet vs. KLT")
        
        # Seskupení pro jasnou a přehlednou tabulku
        su_agg = fu_df.groupby([c_su, 'Typ_Obalu']).agg(
            lines=('Material', 'count'),
            tos=(queue_count_col, 'nunique'),
            qty=('Qty', 'sum')
        ).reset_index().sort_values('tos', ascending=False)
        su_agg.columns = ["Kód obalu (SAP)", "Skupina obalu", "Pickovací řádky", "Počet TO", "Množství (ks)"]
        
        col_su1, col_su2 = st.columns([1, 1.8])
        with col_su1:
            st.dataframe(su_agg, use_container_width=True, hide_index=True)
            
        with col_su2:
            if 'Month' in fu_df.columns:
                trend_su = fu_df.groupby(['Month', 'Typ_Obalu'])[queue_count_col].nunique().reset_index()
                trend_su_pivot = trend_su.pivot(index='Month', columns='Typ_Obalu', values=queue_count_col).fillna(0)
                
                if 'Paleta' not in trend_su_pivot.columns: trend_su_pivot['Paleta'] = 0
                if 'KLT krabička' not in trend_su_pivot.columns: trend_su_pivot['KLT krabička'] = 0
                
                trend_su_pivot['Celkem'] = trend_su_pivot['Paleta'] + trend_su_pivot['KLT krabička']
                # Podíl Palet v daném měsíci
                trend_su_pivot['Palety_pct'] = np.where(trend_su_pivot['Celkem'] > 0, (trend_su_pivot['Paleta'] / trend_su_pivot['Celkem']) * 100, 0)
                trend_su_pivot = trend_su_pivot.reset_index().sort_values('Month')
                
                fig_su = go.Figure()
                fig_su.add_trace(go.Bar(
                    x=trend_su_pivot['Month'], 
                    y=trend_su_pivot['Paleta'],
                    name='Palety (TO)', 
                    marker_color='#3b82f6',
                    text=trend_su_pivot['Paleta'], 
                    textposition='auto'
                ))
                fig_su.add_trace(go.Bar(
                    x=trend_su_pivot['Month'], 
                    y=trend_su_pivot['KLT krabička'],
                    name='KLT (TO)', 
                    marker_color='#f59e0b',
                    text=trend_su_pivot['KLT krabička'], 
                    textposition='auto'
                ))
                fig_su.add_trace(go.Scatter(
                    x=trend_su_pivot['Month'], 
                    y=trend_su_pivot['Palety_pct'],
                    name='Podíl palet (%)', 
                    yaxis='y2',
                    mode='lines+markers+text',
                    text=trend_su_pivot['Palety_pct'].round(1).astype(str) + '%',
                    textposition='top center',
                    line=dict(color='#10b981', width=3),
                    marker=dict(symbol='circle', size=8)
                ))
                
                fig_su.update_layout(
                    barmode='group',
                    yaxis=dict(title="Počet TO"),
                    yaxis2=dict(title="Podíl palet (%)", side="right", overlaying="y", showgrid=False, range=[0, 115]),
                    plot_bgcolor="rgba(0,0,0,0)", 
                    paper_bgcolor="rgba(0,0,0,0)", 
                    margin=dict(t=20, b=10, l=10, r=10), 
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_su, use_container_width=True)
            else:
                st.info("Pro zobrazení trendového grafu chybí data o měsíci.")
    else:
        st.info("Sloupec pro Typ jednotky (Storage Unit Type) nebyl v datech nalezen.")

    # --- 3. ANALÝZA EFEKTIVITY PŘEBALOVÁNÍ (VOLLPALETTE) ---
    st.divider()
    st.markdown("### 📦 Efektivita: Přímé balení bez přebalování (Vollpalette)")
    st.markdown("Algoritmus provádí přísnou křížovou kontrolu:")
    st.markdown("1. Byla pozice vybrána do nuly (**'X'**).")
    st.markdown("2. Byla vyloučena malá balení (Typ jednotky není **K1** ani KLT).")
    st.markdown("3. Zdrojové HU z pickování se **přesně shoduje** s HU vyfakturovaným u dané zakázky ve VEKP.")
    st.markdown("4. Ve **VEPO** je ověřeno, že dané HU opravdu obsahuje položky.")

    df_vekp = load_from_db('raw_vekp')
    df_vepo = load_from_db('raw_vepo')
    
    if df_vekp is None or df_vekp.empty:
        st.warning("⚠️ K vyhodnocení této metriky je nutné mít v Admin Zóně nahrán soubor **VEKP** (Obaly).")
        return

    # KROK A: Zpracování VEPO (Zjištění HU, která mají reálně obsah)
    vepo_hus = set()
    if df_vepo is not None and not df_vepo.empty:
        vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
        vepo_hus = set(df_vepo[vepo_hu_col].astype(str).str.strip().str.lstrip('0'))

    # KROK B: Zpracování VEKP (Vytvoření mapy: Delivery -> Seznam validních HU)
    df_vekp['Clean_Del'] = df_vekp['Generated delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    vekp_hu_col = next((c for c in df_vekp.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vekp.columns[0])
    c_hu_ext = df_vekp.columns[1] if len(df_vekp.columns) > 1 else vekp_hu_col
    parent_col_vepo = next((c for c in df_vekp.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)

    df_vekp['Clean_HU_Int'] = df_vekp[vekp_hu_col].astype(str).str.strip().str.lstrip('0')
    df_vekp['Clean_HU_Ext'] = df_vekp[c_hu_ext].astype(str).str.strip().str.lstrip('0')
    
    if parent_col_vepo:
        df_vekp['Clean_Parent'] = df_vekp[parent_col_vepo].astype(str).str.strip().str.lstrip('0').replace({'nan': '', 'none': ''})
    else:
        df_vekp['Clean_Parent'] = ""

    del_to_valid_hus = {}
    for d, grp in df_vekp.groupby('Clean_Del'):
        valid_hus = set()
        for _, r in grp.iterrows():
            h_int = r['Clean_HU_Int']
            h_ext = r['Clean_HU_Ext']
            # Pokud máme VEPO, HU musí být ve VEPO (musí mít položky)
            if vepo_hus and h_int not in vepo_hus:
                continue
            valid_hus.add(h_int)
            valid_hus.add(h_ext)
        del_to_valid_hus[d] = valid_hus

    # KROK C: Vyčištění a detekce v Pick reportu
    fu_df['Clean_Del'] = fu_df['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    fu_df['Has_X'] = fu_df['Removal of total SU'].astype(str).str.strip().str.upper() == 'X'
    pick_hu_cols = ['Source storage unit', 'Source Storage Bin', 'Handling Unit']
    
    # KROK D: Finální křížová kontrola
    def check_is_vollpalette(row):
        if not row['Has_X']: return False
        if row['Is_KLT']: return False # Ignorujeme dopickované KLT
        
        clean_del = row['Clean_Del']
        valid_hus_for_del = del_to_valid_hus.get(clean_del, set())
        
        if not valid_hus_for_del: return False
        
        for col in pick_hu_cols:
            if col in row.index and pd.notna(row[col]):
                val = str(row[col]).strip().lstrip('0')
                if val and val != 'nan' and val != 'none':
                    # HU se musí shodovat s HU vyfakturovaným PŘESNĚ u této zakázky
                    if val in valid_hus_for_del:
                        return True
        return False

    fu_df['Neprebalovano'] = fu_df.apply(check_is_vollpalette, axis=1)
    
    # --- PŘÍPRAVA DAT PRO 4 SPECIFICKÉ POHLEDY ---
    
    # 1. Z výpočtů metrik striktně odstraníme KLT krabičky
    fu_df_pallets = fu_df[~fu_df['Is_KLT']].copy()
    ignored_klt_count = fu_df[fu_df['Is_KLT']][queue_count_col].nunique()
    
    # Skenování celého Pick Reportu pro určení "čistoty" zakázek
    df_scan = df_pick.copy()
    df_scan['Clean_Del'] = df_scan['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    df_scan['Q_Upper'] = df_scan['Queue'].astype(str).str.upper()
    
    del_all_queues = df_scan.groupby('Clean_Del')['Q_Upper'].apply(set).to_dict()
    
    pure_fu_combo_dels = {d for d, qs in del_all_queues.items() if qs.issubset({'PI_PL_FU', 'PI_PL_FUOE'})}
    only_fu_strict_dels = {d for d, qs in del_all_queues.items() if qs == {'PI_PL_FU'}}
    only_fuoe_strict_dels = {d for d, qs in del_all_queues.items() if qs == {'PI_PL_FUOE'}}

    # Datové sady pro jednotlivé záložky
    df_all = fu_df_pallets.copy()
    df_pure_combo = fu_df_pallets[fu_df_pallets['Clean_Del'].isin(pure_fu_combo_dels)].copy()
    df_only_fu = fu_df_pallets[fu_df_pallets['Clean_Del'].isin(only_fu_strict_dels)].copy()
    df_only_fuoe = fu_df_pallets[fu_df_pallets['Clean_Del'].isin(only_fuoe_strict_dels)].copy()

    # --- ZOBRAZENÍ V ZÁLOŽKÁCH (TABS) ---
    tab1, tab2, tab3, tab4 = st.tabs([
        "Všechny paletové zakázky (včetně kombinovaných)", 
        "🎯 Pouze čisté paletové zakázky (bez jiných front)",
        "📦 Pouze PI_PL_FU", 
        "🌍 Pouze PI_PL_FUOE"
    ])

    def render_tab_content(df_view, is_pure=False, label=""):
        if df_view.empty:
            st.info(f"V této kategorii ({label}) nebyly nalezeny žádné záznamy.")
            return

        # --- MĚSÍČNÍ GRAF EFEKTIVITY (S TRENDOVOU ČÁROU A HODNOTAMI) ---
        if 'Month' in df_view.columns:
            st.markdown("#### 📈 Měsíční trend odbavení celých palet")
            
            # Příprava dat pro graf
            trend_df = df_view[df_view['Has_X']].groupby(['Month', 'Neprebalovano'])[queue_count_col].nunique().reset_index()
            trend_pivot = trend_df.pivot(index='Month', columns='Neprebalovano', values=queue_count_col).fillna(0)
            
            if True not in trend_pivot.columns: trend_pivot[True] = 0
            if False not in trend_pivot.columns: trend_pivot[False] = 0
            
            trend_pivot['Celkem_X'] = trend_pivot[True] + trend_pivot[False]
            # Výpočet procentuální úspěšnosti
            trend_pivot['Uspesnost_pct'] = np.where(trend_pivot['Celkem_X'] > 0, (trend_pivot[True] / trend_pivot['Celkem_X']) * 100, 0)
            trend_pivot = trend_pivot.reset_index().sort_values('Month')
            
            fig_bar = go.Figure()
            
            # Zelené sloupce (Nepřebalováno = Zisk)
            fig_bar.add_trace(go.Bar(
                x=trend_pivot['Month'], 
                y=trend_pivot[True],
                name='Nepřebalováno (Ziskové)', 
                marker_color='#10b981',
                text=trend_pivot[True], 
                textposition='auto'
            ))
            
            # Červené sloupce (Přebaleno = Ztráta)
            fig_bar.add_trace(go.Bar(
                x=trend_pivot['Month'], 
                y=trend_pivot[False],
                name='Přebaleno (Zbytečná práce)', 
                marker_color='#ef4444',
                text=trend_pivot[False], 
                textposition='auto'
            ))
            
            # Modrá trendová čára (%)
            fig_bar.add_trace(go.Scatter(
                x=trend_pivot['Month'], 
                y=trend_pivot['Uspesnost_pct'],
                name='Úspěšnost bez přebalení (%)', 
                yaxis='y2',
                mode='lines+markers+text',
                text=trend_pivot['Uspesnost_pct'].round(1).astype(str) + '%',
                textposition='top center',
                line=dict(color='#3b82f6', width=3),
                marker=dict(symbol='circle', size=8)
            ))

            fig_bar.update_layout(
                barmode='group',
                yaxis=dict(title="Počet palet (TO)"),
                yaxis2=dict(title="Úspěšnost (%)", side="right", overlaying="y", showgrid=False, range=[0, 115]),
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)", 
                margin=dict(t=20, b=10, l=10, r=10), 
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            st.markdown("<br>", unsafe_allow_html=True)
        
        # Výpočty pro zobrazení metrik (unikátní TO)
        total_fu_pal = df_view[queue_count_col].nunique()
        total_x_pal = df_view[df_view['Has_X']][queue_count_col].nunique()
        total_neprebalovano = df_view[df_view['Neprebalovano']][queue_count_col].nunique()
        
        c1, c2, c3 = st.columns(3)
        with c1:
            help_txt = "Celkový počet paletových picků u zakázek, kde se nepickovalo z žádné jiné zóny." if is_pure else f"Ignorováno {ignored_klt_count} TO, u kterých se dopickovávalo KLT (např. K1)."
            with st.container(border=True):
                st.metric("Celkem pickováno palet (TO)", f"{total_fu_pal:,}", help=help_txt)
        with c2:
            with st.container(border=True):
                st.metric("Celá paleta ze skladu (Značka 'X')", f"{total_x_pal:,}", help="U tolika TO skladník vybral pozici do nuly (mimo KLT).")
        with c3:
            with st.container(border=True):
                st.metric("Nepřebalováno (Úplná shoda) ✅", f"{total_neprebalovano:,}", help="Paleta prošla balením tak, jak přišla ze skladu (shoda s VEKP a VEPO pro danou zakázku).")
                
        # Zobrazení detailů - kde se práce ušetřila vs. kde se pálil čas přebalováním
        prebaleno_x = df_view[(df_view['Has_X']) & (~df_view['Neprebalovano'])]
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.success(f"**✅ Úspěšné Vollpalety: {total_neprebalovano} TO**")
            nepreb_df = df_view[df_view['Neprebalovano']].drop_duplicates(subset=[queue_count_col]).copy()
            if not nepreb_df.empty:
                disp1 = nepreb_df[['Delivery', queue_count_col, 'Material', 'Qty', c_su] if c_su else ['Delivery', queue_count_col, 'Material', 'Qty']].copy()
                disp1.columns = ["Zakázka", "Číslo TO", "Materiál", "Kusů", "Typ jednotky"] if c_su else ["Zakázka", "Číslo TO", "Materiál", "Kusů"]
                st.dataframe(disp1, use_container_width=True, hide_index=True)
            else:
                st.info("Žádné palety nebyly odbaveny napřímo.")
                
        with col_t2:
            st.error(f"**⚠️ Zbytečná práce (Přebaleno): {prebaleno_x[queue_count_col].nunique()} TO**\n*Měly značku 'X', ale přebalily se na jiné HU.*")
            if not prebaleno_x.empty:
                disp2 = prebaleno_x.drop_duplicates(subset=[queue_count_col])[['Delivery', queue_count_col, 'Material', 'Qty', c_su] if c_su else ['Delivery', queue_count_col, 'Material', 'Qty']].copy()
                disp2.columns = ["Zakázka", "Číslo TO", "Materiál", "Kusů", "Typ jednotky"] if c_su else ["Zakázka", "Číslo TO", "Materiál", "Kusů"]
                st.dataframe(disp2, use_container_width=True, hide_index=True)
            else:
                st.info("Skvělá práce! Všechny celé palety ('X') byly úspěšně odbaveny bez přebalování.")

    # Vykreslení obsahu do jednotlivých záložek
    with tab1:
        st.markdown("Analýza **všech** picků z fronty FU, bez ohledu na to, zda k dané zakázce dorazil u stolu ještě další materiál z jiných uliček.")
        render_tab_content(df_all, is_pure=False, label="Všechny")
    with tab2:
        st.markdown("Analýza **čistých paletových zakázek**, které se nevybavovaly v žádné jiné frontě. Pokud se zde přebaluje, znamená to 100% zbytečnou práci u balícího stolu.")
        render_tab_content(df_pure_combo, is_pure=True, label="Čisté FU + FUOE")
    with tab3:
        st.markdown("Analýza zakázek, které obsahují **výhradně standardní palety (PI_PL_FU)**.")
        render_tab_content(df_only_fu, is_pure=True, label="Pouze FU")
    with tab4:
        st.markdown("Analýza zakázek, které obsahují **výhradně exportní palety (PI_PL_FUOE)**.")
        render_tab_content(df_only_fuoe, is_pure=True, label="Pouze FUOE")

    # --- 4. RENTGEN / AUDIT KONKRÉTNÍ ZAKÁZKY ---
    st.divider()
    st.markdown("<div class='section-header'><h3>🔍 Rentgen paletové zakázky (Audit logiky)</h3><p>Zde si můžete ověřit libovolnou zakázku z fronty FU a zjistit, proč ji algoritmus vyhodnotil jako Přebalenou/Nepřebalenou.</p></div>", unsafe_allow_html=True)
    
    audit_dels = sorted(fu_df['Clean_Del'].dropna().unique())
    sel_audit_del = st.selectbox("Vyberte zakázku (Delivery) pro rentgen:", options=[""] + audit_dels, key="audit_fu_del")
    
    if sel_audit_del:
        st.markdown(f"#### Výsledky pro zakázku: `{sel_audit_del}`")
        
        # A) Co ukazuje Pick Report
        st.markdown("**1. Data ze Skladu (Pick Report):**")
        pick_audit = fu_df[fu_df['Clean_Del'] == sel_audit_del].copy()
        
        cols_to_show = [queue_count_col, 'Material', 'Qty', 'Removal of total SU']
        if c_su: cols_to_show.append(c_su)
        for c in pick_hu_cols:
            if c in pick_audit.columns: cols_to_show.append(c)
            
        st.dataframe(pick_audit[cols_to_show], hide_index=True, use_container_width=True)
        
        # B) Co je vyfakturováno (VEKP)
        st.markdown("**2. Co je vyfakturováno (VEKP):**")
        vekp_audit = df_vekp[df_vekp['Clean_Del'] == sel_audit_del]
        if not vekp_audit.empty:
            disp_cols = ['Generated delivery', 'Clean_HU_Int', 'Clean_HU_Ext', 'Clean_Parent']
            if 'Packaging materials' in vekp_audit.columns: disp_cols.append('Packaging materials')
            elif 'Packmittel' in vekp_audit.columns: disp_cols.append('Packmittel')
                
            st.dataframe(vekp_audit[disp_cols], hide_index=True, use_container_width=True)
            valid_h = del_to_valid_hus.get(sel_audit_del, set())
            st.caption(f"Systém očekává přiřazení k těmto platným HU (dle VEPO): `{', '.join(valid_h)}`")
        else:
            st.warning("Žádné obaly ve VEKP pro tuto zakázku (nebo VEPO nenašlo položky).")
            valid_h = set()
            
        # C) Krok za krokem vyhodnocení
        st.markdown("**3. Myšlenkový pochod algoritmu (TO po TO):**")
        
        for _, r in pick_audit.drop_duplicates(subset=[queue_count_col]).iterrows():
            to_num = r[queue_count_col]
            with st.expander(f"Hodnocení pro TO: {to_num}", expanded=True):
                # 1. KLT kontrola
                if r['Is_KLT']:
                    st.info(f"🚫 Typ obalu je `{r.get(c_su, '')}` (KLT). Do paletové analýzy to vůbec nepočítám.")
                    continue
                else:
                    st.success(f"✔️ Typ obalu `{r.get(c_su, '')}` je Paleta.")
                
                # 2. X kontrola
                if not r['Has_X']:
                    st.error("❌ Pozice nebyla vybrána do nuly (Chybí značka 'X'). Logika končí.")
                    continue
                else:
                    st.success("✔️ Nalezena značka 'X' (Paleta vybrána z lokace celá).")
                
                # 3. HU kontrola
                hu_found = False
                for c in pick_hu_cols:
                    if c in r.index and pd.notna(r[c]):
                        val = str(r[c]).strip().lstrip('0')
                        if val in valid_h:
                            hu_found = True
                            st.success(f"✔️ Pickované HU `{val}` ze sloupce '{c}' nalezeno přímo ve VEKP u této zakázky!")
                            break
                        elif val and val != 'nan' and val != 'none':
                            st.warning(f"⚠️ Pickované HU `{val}` ze sloupce '{c}' ve VEKP pro tuto zakázku neexistuje.")
                            
                if hu_found:
                    st.success("**Závěr: ✅ Paleta byla vyhodnocena jako NEPŘEBALOVANÁ.**")
                else:
                    st.error("**Závěr: ❌ Shoda HU nenalezena. Paleta byla u stolu PŘEBALENA na novou HU.**")
