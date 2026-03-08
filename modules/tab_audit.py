import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import t, get_match_key, safe_del, safe_hu

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

def render_audit(df_pick, df_vekp, df_vepo, df_oe, queue_count_col, billing_df, manual_boxes=None, weight_dict=None, dim_dict=None, box_dict=None, limit_vahy=2.0, limit_rozmeru=15.0, kusy_na_hmat=1):
    if manual_boxes is None: manual_boxes = {}
    if weight_dict is None: weight_dict = {}
    if dim_dict is None: dim_dict = {}
    if box_dict is None: box_dict = {}

    # ==========================================
    # NOVÁ SEKCE: HROMADNÁ AUTOMATICKÁ KONTROLA
    # ==========================================
    st.markdown("<div class='section-header'><h3>🤖 Hromadná Automatická Kontrola (Data vs Aplikace)</h3></div>", unsafe_allow_html=True)
    st.markdown("Nahrajte kontrolní soubor (např. **kontrola.xlsx**), který obsahuje sloupce `Lieferung`, `Kategorie` a `Art`. Aplikace bleskově porovná svůj výpočet s tímto referenčním vzorkem na úrovni zabalených HU.")
    
    uploaded_ctrl = st.file_uploader("Nahrát kontrolní soubor (Excel/CSV)", type=["xlsx", "csv"], key="audit_ctrl_upload")
    
    if uploaded_ctrl:
        try:
            if uploaded_ctrl.name.endswith('.csv'):
                df_ctrl = pd.read_csv(uploaded_ctrl, dtype=str, sep=None, engine='python')
            else:
                df_ctrl = pd.read_excel(uploaded_ctrl, dtype=str)
            
            # Zjištění názvů sloupců (flexibilní vůči překlepům)
            cols_low = [str(c).lower().strip() for c in df_ctrl.columns]
            c_del = next((c for c, l in zip(df_ctrl.columns, cols_low) if l in ['lieferung', 'delivery']), None)
            c_kat = next((c for c, l in zip(df_ctrl.columns, cols_low) if 'kategorie' in l or 'category' in l), None)
            c_art = next((c for c, l in zip(df_ctrl.columns, cols_low) if l == 'art' or 'type' in l), None)
            
            if not (c_del and c_kat and c_art):
                st.error(f"❌ V souboru se nepodařilo najít všechny potřebné sloupce. Nalezeno: Lieferung=`{c_del}`, Kategorie=`{c_kat}`, Art=`{c_art}`. Zkontrolujte hlavičku souboru.")
            else:
                # 1. Zpracování referenčního souboru (Očekávaná data)
                df_ctrl['Clean_Del'] = df_ctrl[c_del].apply(safe_del)
                
                # Normalizace kategorií (např. "n sortenrein" -> "N Sortenrein")
                def norm_cat(k, a):
                    k = str(k).strip().upper()
                    a = str(a).strip().capitalize()
                    return f"{k} {a}"
                    
                df_ctrl['Category_Full'] = df_ctrl.apply(lambda r: norm_cat(r[c_kat], r[c_art]), axis=1)
                
                # Zjištění, kolik HU se očekává pro každou zakázku a kategorii
                expected_agg = df_ctrl.groupby(['Clean_Del', 'Category_Full']).size().reset_index(name='Expected_HUs')
                
                # 2. Načtení vypočítaných dat z aplikace
                if billing_df is not None and not billing_df.empty:
                    app_df = billing_df.copy()
                    app_df['Clean_Del'] = app_df['Clean_Del_Merge'].astype(str)
                    
                    # Očištění názvu pro bezpečné spojení
                    def clean_app_cat(v):
                        parts = str(v).split(' ')
                        if len(parts) >= 2:
                            return parts[0].upper() + " " + " ".join(parts[1:]).capitalize()
                        return str(v).capitalize()
                        
                    app_df['Category_Full'] = app_df['Category_Full'].apply(clean_app_cat)
                    
                    # Agregace dat aplikace
                    app_agg = app_df.groupby(['Clean_Del', 'Category_Full'])['pocet_hu'].sum().reset_index(name='App_HUs')
                    
                    # 3. Křížové porovnání
                    comp = pd.merge(expected_agg, app_agg, on=['Clean_Del', 'Category_Full'], how='outer').fillna(0)
                    comp['Expected_HUs'] = comp['Expected_HUs'].astype(int)
                    comp['App_HUs'] = comp['App_HUs'].astype(int)
                    comp['Rozdíl'] = comp['App_HUs'] - comp['Expected_HUs']
                    
                    # Filtrovat pouze ty zakázky, které opravdu jsou v nahraném kontrolním souboru
                    tested_dels = set(expected_agg['Clean_Del'])
                    comp_tested = comp[comp['Clean_Del'].isin(tested_dels)].copy()
                    
                    # 4. Matematika skóre
                    total_expected_hus = comp_tested['Expected_HUs'].sum()
                    comp_tested['Matched_HUs'] = comp_tested[['Expected_HUs', 'App_HUs']].min(axis=1)
                    total_matched_hus = comp_tested['Matched_HUs'].sum()
                    
                    mismatches = comp_tested[comp_tested['Rozdíl'] != 0].copy()
                    
                    total_dels = len(tested_dels)
                    err_dels = mismatches['Clean_Del'].nunique()
                    
                    # 5. Vykreslení výsledků
                    c1, c2, c3 = st.columns(3)
                    pct = (total_matched_hus / total_expected_hus * 100) if total_expected_hus > 0 else 0
                    
                    c1.metric("Očekáváno HU celkem (ze souboru)", total_expected_hus)
                    c2.metric("Shodně zařazeno HU ✅", f"{total_matched_hus} ({pct:.1f} %)")
                    c3.metric("Chybně zařazeno u zakázek ❌", f"{err_dels} z {total_dels}")
                    
                    if not mismatches.empty:
                        st.error(f"⚠️ Nalezeny rozdíly u {err_dels} zakázek! Zde je detailní přehled nesrovnalostí:")
                        disp = mismatches[['Clean_Del', 'Category_Full', 'Expected_HUs', 'App_HUs', 'Rozdíl']].sort_values('Clean_Del')
                        disp.columns = ['Zakázka (Delivery)', 'Kategorie HU', 'Očekáváno (Kontrola)', 'Vypočteno (Aplikace)', 'Rozdíl (Aplikace - Kontrola)']
                        
                        def color_diff(val):
                            try:
                                if val > 0: return 'color: #3b82f6; font-weight: bold'  # Aplikace přidala navíc
                                elif val < 0: return 'color: #ef4444; font-weight: bold' # Aplikaci chybí
                            except: pass
                            return ''
                            
                        # Try/except blok pro kompatibilitu se staršími verzemi Pandas styleru
                        try:
                            styled_disp = disp.style.map(color_diff, subset=['Rozdíl (Aplikace - Kontrola)'])
                        except AttributeError:
                            styled_disp = disp.style.applymap(color_diff, subset=['Rozdíl (Aplikace - Kontrola)'])
                            
                        st.dataframe(styled_disp, hide_index=True, use_container_width=True)
                    else:
                        st.success("🎉 PERFEKTNÍ! Aplikace se na 100 % shoduje s kontrolním souborem ve všech zakázkách a kategoriích.")
                else:
                    st.warning("⚠️ Nejdříve navštivte záložku **Fakturace**, aby se vypočítala data, a pak se sem vraťte.")
        except Exception as e:
            st.error(f"Nastala chyba při zpracování souboru: {e}")

    st.divider()

    # ==========================================
    # STÁVAJÍCÍ AUDITNÍ RENTGEN (Detailní prohlížení)
    # ==========================================
    col_au1, col_au2 = st.columns([3, 2])

    with col_au1:
        st.markdown("<div class='section-header'><h3>🎲 Detailní Auditní Report (Náhodné vzorky)</h3></div>", unsafe_allow_html=True)
        if st.button("🔄 Vygenerovat nové vzorky", type="primary") or 'audit_samples' not in st.session_state:
            audit_samples = {}
            valid_queues = sorted([q for q in df_pick['Queue'].dropna().unique() if q not in ['N/A', 'CLEARANCE']])
            for q in valid_queues:
                q_data = df_pick[df_pick['Queue'] == q]
                unique_tos = q_data[queue_count_col].dropna().unique()
                if len(unique_tos) > 0: audit_samples[q] = np.random.choice(unique_tos, min(5, len(unique_tos)), replace=False)
            st.session_state['audit_samples'] = audit_samples

        for q, tos in st.session_state.get('audit_samples', {}).items():
            with st.expander(f"📁 Queue: **{q}** — {len(tos)} vzorků"):
                for i, r_to in enumerate(tos, 1):
                    st.markdown(f"#### {i}. TO: `{r_to}`")
                    to_data = df_pick[df_pick[queue_count_col] == r_to]
                    for _, row in to_data.iterrows():
                        mat = row['Material']
                        qty = row['Qty']
                        raw_boxes = row.get('Box_Sizes_List', [])
                        boxes = raw_boxes if isinstance(raw_boxes, list) else []
                        real_boxes = [b for b in boxes if b > 1]
                        w = float(row.get('Piece_Weight_KG', 0))
                        d = float(row.get('Piece_Max_Dim_CM', 0))
                        st.markdown(f"**Mat:** `{mat}` | **Qty:** {int(qty)} | **Krabice:** {real_boxes} | **Váha:** {w:.3f} kg | **Rozměr:** {d:.1f} cm")
                        zbytek = qty
                        for b in real_boxes:
                            if zbytek >= b:
                                st.write(f"➡️ **{int(zbytek // b)}x Krabice** (po {b} ks)")
                                zbytek = zbytek % b
                        if zbytek > 0:
                            if (w >= limit_vahy) or (d >= limit_rozmeru): st.warning(f"➡️ Zbylých {int(zbytek)} ks překračuje limit → **{int(zbytek)} pohybů** (po 1 ks)")
                            else: st.success(f"➡️ Zbylých {int(zbytek)} ks do hrsti → **{int(np.ceil(zbytek / kusy_na_hmat))} pohybů**")
                        st.markdown(f"> **Fyzických pohybů: `{int(row.get('Pohyby_Rukou', 0))}`**")

    with col_au2:
        st.markdown("<div class='section-header'><h3>🔍 Prohlížeč Master Dat</h3></div>", unsafe_allow_html=True)
        mat_search = st.selectbox("Zkontrolujte si konkrétní materiál:", options=[""] + sorted(df_pick['Material'].dropna().astype(str).unique().tolist()))
        if mat_search:
            search_key = get_match_key(mat_search)
            if search_key in manual_boxes: st.success(f"✅ Ruční ověření nalezeno: balení **{manual_boxes[search_key]} ks**.")
            else: st.info("ℹ️ Žádné ruční ověření.")
            c_info1, c_info2 = st.columns(2)
            c_info1.metric("Váha / ks (MARM)", f"{weight_dict.get(search_key, 0):.3f} kg")
            c_info2.metric("Max. rozměr (MARM)", f"{dim_dict.get(search_key, 0):.1f} cm")
            marm_boxes = box_dict.get(search_key, [])
            st.metric("Krabicové jednotky (MARM)", str(marm_boxes) if marm_boxes else "*Chybí*")

    st.divider()
    st.markdown("<div class='section-header'><h3>🔍 Rentgen Zakázky (End-to-End Audit)</h3></div>", unsafe_allow_html=True)
    
    @fast_render
    def render_audit_interactive():
        df_pick['Clean_Del'] = df_pick['Delivery'].apply(safe_del)
        avail_dels = sorted(df_pick['Clean_Del'].dropna().unique())
        sel_del = st.selectbox("Vyberte Delivery pro kompletní rentgen:", options=[""] + avail_dels, key="audit_rentgen_selection")
        
        if sel_del:
            st.markdown("#### 1️⃣ Fáze: Pickování ve skladu")
            pick_del = df_pick[df_pick['Clean_Del'] == sel_del].copy()
            to_count = pick_del[queue_count_col].nunique()
            moves_count = pick_del['Pohyby_Rukou'].sum()
            
            c1, c2 = st.columns(2)
            c1.metric("Počet úkolů (TO)", to_count)
            c2.metric("Fyzických pohybů", int(moves_count))
            with st.expander("Zobrazit Pick List"): st.dataframe(pick_del[[queue_count_col, 'Material', 'Qty', 'Pohyby_Rukou', 'Removal of total SU']], hide_index=True, use_container_width=True)

            st.markdown("#### 2️⃣ Fáze: Systémové Obaly (VEKP / VEPO)")
            if df_vekp is not None and not df_vekp.empty:
                df_vekp['Clean_Del'] = df_vekp['Generated delivery'].apply(safe_del)
                vekp_del = df_vekp[df_vekp['Clean_Del'] == sel_del].copy()
                
                sel_del_kat = "Neznámá"
                if billing_df is not None and not billing_df.empty:
                    cat_row = billing_df[billing_df['Clean_Del_Merge'].astype(str) == sel_del]
                    if not cat_row.empty: 
                        sel_del_kat = str(cat_row.iloc[0]['Category_Full']).upper()
                
                if not vekp_del.empty:
                    vekp_hu_col_aud = next((c for c in vekp_del.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_del.columns[0])
                    c_hu_ext_aud = vekp_del.columns[1]
                    parent_col_aud = next((c for c in vekp_del.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
                    
                    vekp_del['Clean_HU_Int'] = vekp_del[vekp_hu_col_aud].apply(safe_hu)
                    vekp_del['Clean_HU_Ext'] = vekp_del[c_hu_ext_aud].apply(safe_hu)

                    if parent_col_aud: 
                        vekp_del['Clean_Parent'] = vekp_del[parent_col_aud].apply(safe_hu)
                    else: 
                        vekp_del['Clean_Parent'] = ""
                        
                    ext_to_int_aud = dict(zip(vekp_del['Clean_HU_Ext'], vekp_del['Clean_HU_Int']))
                    
                    parent_map_aud = {}
                    for _, r in vekp_del.iterrows():
                        child = str(r['Clean_HU_Int'])
                        parent = str(r['Clean_Parent'])
                        if parent in ext_to_int_aud: parent = ext_to_int_aud[parent]
                        parent_map_aud[child] = parent

                    valid_base_aud = set()
                    if df_vepo is not None and not df_vepo.empty:
                        vepo_hu_col_aud = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
                        valid_base_aud = set(df_vepo[vepo_hu_col_aud].apply(safe_hu))
                    else:
                        valid_base_aud = set(vekp_del['Clean_HU_Int'])

                    del_leaves = set(h for h in vekp_del['Clean_HU_Int'] if h in valid_base_aud)
                    del_roots = set()
                    
                    # Načtení dat z Centrálního Mozku
                    voll_set = st.session_state.get('voll_set', set())
                    actual_voll_hus = set()

                    for _, r in vekp_del.iterrows():
                        if (sel_del, r['Clean_HU_Ext']) in voll_set or (sel_del, r['Clean_HU_Int']) in voll_set:
                            actual_voll_hus.add(r['Clean_HU_Int'])
                    
                    for leaf in del_leaves:
                        if leaf in actual_voll_hus:
                            continue
                        curr = leaf
                        visited = set()
                        while curr in parent_map_aud and parent_map_aud[curr] != "" and curr not in visited:
                            visited.add(curr)
                            curr = parent_map_aud[curr]
                        del_roots.add(curr)

                    def get_audit_status(row):
                        h = str(row['Clean_HU_Int'])
                        
                        if h in actual_voll_hus:
                            return "🏭 Účtuje se (Vollpalette)"
                            
                        if h in del_roots:
                            return "✅ Účtuje se (Kořenová HU)"
                            
                        curr = h
                        visited = set()
                        while curr in parent_map_aud and parent_map_aud[curr] != "" and curr not in visited:
                            visited.add(curr)
                            curr = parent_map_aud[curr]
                            
                        if curr in del_roots:
                            if curr not in vekp_del['Clean_HU_Int'].values:
                                return f"🔗 Podřazený obal (Nadřazené HU {curr} chybí v reportu, ale vyfakturuje se)"
                            return f"❌ Neúčtuje se (Zabaleno do {curr})"
                            
                        return "❌ Neúčtuje se (Prázdný obal / Mimo strom)"

                    vekp_del['Status pro fakturaci'] = vekp_del.apply(get_audit_status, axis=1)
                    hu_count = len(del_roots) + len(actual_voll_hus)
                    st.metric(f"Zabalených HU (Kategorie z Fakturace)", hu_count)
                    
                    with st.expander("Zobrazit hierarchii obalů a detekci Vollpalet"):
                        disp_cols = [c_hu_ext_aud, 'Packaging materials', 'Total Weight', 'Status pro fakturaci']
                        if 'Packmittel' in vekp_del.columns and 'Packaging materials' not in vekp_del.columns:
                            disp_cols[1] = 'Packmittel'
                            
                        avail_cols = [c for c in disp_cols if c in vekp_del.columns]
                        disp_v = vekp_del[avail_cols].copy()
                        
                        def color_status(val):
                            if '🏭' in str(val) or '✅' in str(val): return 'color: #10b981; font-weight: bold'
                            if '🔗' in str(val): return 'color: #3b82f6; font-weight: bold'
                            if '❌' in str(val): return 'color: #ef4444; text-decoration: line-through'
                            return ''
                            
                        try:
                            styled_v = disp_v.style.map(color_status, subset=['Status pro fakturaci'])
                        except AttributeError:
                            styled_v = disp_v.style.applymap(color_status, subset=['Status pro fakturaci'])
                            
                        st.dataframe(styled_v, hide_index=True, use_container_width=True)
                else: st.warning(f"Zakázka {sel_del} nebyla nalezena ve VEKP (zkontrolujte případné nuly v Exportu).")
            else: st.info("Chybí soubor VEKP pro druhou fázi.")

            st.markdown("#### 3️⃣ Fáze: Čas u balícího stolu (OE-Times)")
            if df_oe is not None:
                df_oe_clean = df_oe.copy()
                df_oe_clean['Clean_Del'] = df_oe_clean['Delivery'].apply(safe_del)
                oe_del = df_oe_clean[df_oe_clean['Clean_Del'] == sel_del]
                if not oe_del.empty:
                    ro = oe_del.iloc[0]
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("Procesní čas", f"{ro.get('Process_Time_Min', 0):.1f} min")
                    cc2.metric("Pracovník / Směna", str(ro.get('Shift', '-')))
                    cc3.metric("Počet druhů zboží", str(ro.get('Number of item types', '-')))
                    with st.expander("Zobrazit kompletní záznam balení"): st.dataframe(oe_del, hide_index=True, use_container_width=True)
                else: st.info("K této zakázce nebyl v souboru OE-Times nalezen žádný záznam.")

    render_audit_interactive()
