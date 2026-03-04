import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import t, get_match_key

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

def render_audit(df_pick, df_vekp, df_vepo, df_oe, queue_count_col, billing_df, manual_boxes=None, weight_dict=None, dim_dict=None, box_dict=None, limit_vahy=2.0, limit_rozmeru=15.0, kusy_na_hmat=1):
    if manual_boxes is None: manual_boxes = {}
    if weight_dict is None: weight_dict = {}
    if dim_dict is None: dim_dict = {}
    if box_dict is None: box_dict = {}

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
        df_pick['Clean_Del'] = df_pick['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
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
                df_vekp['Clean_Del'] = df_vekp['Generated delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
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
                    
                    vekp_del['Clean_HU_Int'] = vekp_del[vekp_hu_col_aud].astype(str).str.strip().str.lstrip('0')
                    vekp_del['Clean_HU_Ext'] = vekp_del[c_hu_ext_aud].astype(str).str.strip().str.lstrip('0')

                    if parent_col_aud: 
                        vekp_del['Clean_Parent'] = vekp_del[parent_col_aud].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
                        vekp_del.loc[vekp_del['Clean_Parent'].str.lower().isin(['nan', 'none', '']), 'Clean_Parent'] = ""
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
                        valid_base_aud = set(df_vepo[vepo_hu_col_aud].astype(str).str.strip().str.lstrip('0'))
                    else:
                        valid_base_aud = set(vekp_del['Clean_HU_Int'])

                    del_leaves = set(h for h in vekp_del['Clean_HU_Int'] if h in valid_base_aud)
                    del_roots = set()
                    actual_voll_hus = set()

                    # Získání Vollpalet čistě (Vyřazení KLT)
                    c_su = 'Storage Unit Type' if 'Storage Unit Type' in pick_del.columns else ('Type' if 'Type' in pick_del.columns else None)
                    def is_klt(v):
                        v = str(v).upper().strip()
                        return v in ['K1','K2','K3','K4','KLT','KLT1','KLT2'] or (v.startswith('K') and len(v) <= 2)

                    pick_hu_cols = ['Source storage unit', 'Source Storage Bin', 'Handling Unit']
                    voll_cands = set()
                    for _, r in pick_del.iterrows():
                        if str(r.get('Removal of total SU', '')).upper() == 'X':
                            if c_su and is_klt(r.get(c_su, '')): continue
                            for col in pick_hu_cols:
                                if col in r.index and pd.notna(r[col]):
                                    v = str(r[col]).strip().lstrip('0')
                                    if v: voll_cands.add(v)
                    
                    # Logika šplhání po stromu bez ohledu na kategorii!
                    for leaf in del_leaves:
                        leaf_exts = vekp_del.loc[vekp_del['Clean_HU_Int'] == leaf, 'Clean_HU_Ext'].values
                        leaf_ext = leaf_exts[0] if len(leaf_exts) > 0 else ""
                        
                        if leaf in voll_cands or leaf_ext in voll_cands:
                            actual_voll_hus.add(leaf)
                        else:
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
                            
                        # Obal není kořenem - kde to skončí?
                        curr = h
                        visited = set()
                        while curr in parent_map_aud and parent_map_aud[curr] != "" and curr not in visited:
                            visited.add(curr)
                            curr = parent_map_aud[curr]
                            
                        if curr in del_roots:
                            # Tady je to kouzlo: Pokud chybí rodičovská paleta z VEKP, audit tě na to upozorní.
                            if curr not in vekp_del['Clean_HU_Int'].values:
                                return f"🔗 Podřazený obal (Nadřazené HU {curr} chybí v reportu, ale vyfakturuje se)"
                            return f"❌ Neúčtuje se (Zabaleno do {curr})"
                            
                        return "❌ Neúčtuje se (Prázdný obal / Mimo strom)"

                    vekp_del['Status pro fakturaci'] = vekp_del.apply(get_audit_status, axis=1)

                    # Výpočet Billed HU - nyní natvrdo přes strom
                    hu_count = len(del_roots) + len(actual_voll_hus)
                        
                    st.metric(f"Zabalených HU (Kategorie: {sel_del_kat})", hu_count)
                    
                    with st.expander("Zobrazit hierarchii obalů"):
                        disp_cols = [c_hu_ext_aud, 'Packaging materials', 'Total Weight', 'Status pro fakturaci']
                        avail_cols = [c for c in disp_cols if c in vekp_del.columns]
                        disp_v = vekp_del[avail_cols].copy()
                        
                        def color_status(val):
                            if '🏭' in str(val) or '✅' in str(val): return 'color: #10b981; font-weight: bold' # Zelená
                            if '🔗' in str(val): return 'color: #3b82f6; font-weight: bold' # Modrá pro podřazené bez rodiče
                            if '❌' in str(val): return 'color: #ef4444; text-decoration: line-through' # Červená pro klasicky podřazené
                            return ''
                            
                        st.dataframe(disp_v.style.map(color_status, subset=['Status pro fakturaci']), hide_index=True, use_container_width=True)
                else: st.warning(f"Zakázka {sel_del} nebyla nalezena ve VEKP (zkontrolujte případné nuly v Exportu).")
            else: st.info("Chybí soubor VEKP pro druhou fázi.")

            st.markdown("#### 3️⃣ Fáze: Čas u balícího stolu (OE-Times)")
            if df_oe is not None:
                df_oe_clean = df_oe.copy()
                df_oe_clean['Clean_Del'] = df_oe_clean['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
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
