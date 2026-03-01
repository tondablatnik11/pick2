import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import t

def render_audit(df_pick, df_vekp, df_vepo, df_oe, queue_count_col, billing_df):
    st.markdown("<div class='section-header'><h3>🔍 Rentgen Zakázky (End-to-End Audit)</h3></div>", unsafe_allow_html=True)
    avail_dels = sorted(df_pick['Delivery'].dropna().unique())
    sel_del = st.selectbox("Vyberte Delivery pro kompletní rentgen:", options=[""] + avail_dels)
    
    if sel_del:
        st.markdown("#### 1️⃣ Fáze: Pickování ve skladu")
        pick_del = df_pick[df_pick['Delivery'] == sel_del]
        to_count = pick_del[queue_count_col].nunique()
        moves_count = pick_del['Pohyby_Rukou'].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Počet úkolů (TO)", to_count)
        c2.metric("Fyzických pohybů", int(moves_count))
        with st.expander("Zobrazit Pick List"): st.dataframe(pick_del[[queue_count_col, 'Material', 'Qty', 'Pohyby_Rukou', 'Removal of total SU']], hide_index=True, use_container_width=True)

        st.markdown("#### 2️⃣ Fáze: Systémové Obaly (VEKP / VEPO)")
        if df_vekp is not None and not df_vekp.empty:
            vekp_del = df_vekp[df_vekp['Generated delivery'] == sel_del].copy()
            
            sel_del_kat = "N"
            if billing_df is not None and not billing_df.empty:
                cat_row = billing_df[billing_df['Delivery'] == sel_del]
                if not cat_row.empty: sel_del_kat = str(cat_row.iloc[0]['Category_Full']).upper()
            
            vekp_hu_col_aud = next((c for c in vekp_del.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_del.columns[0])
            c_hu_ext_aud = vekp_del.columns[1]
            parent_col_aud = next((c for c in vekp_del.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower()), None)
            
            vekp_del['Clean_HU_Int'] = vekp_del[vekp_hu_col_aud].astype(str).str.strip().str.lstrip('0')
            vekp_del['Clean_HU_Ext'] = vekp_del[c_hu_ext_aud].astype(str).str.strip().str.lstrip('0')

            if parent_col_aud: vekp_del['Clean_Parent'] = vekp_del[parent_col_aud].astype(str).str.strip().str.lstrip('0').replace({'nan': '', 'none': ''})
            else: vekp_del['Clean_Parent'] = ""
                
            ext_to_int_aud = dict(zip(vekp_del['Clean_HU_Ext'], vekp_del['Clean_HU_Int']))
            parent_map_aud = {}
            for _, r in vekp_del.iterrows():
                child = str(r['Clean_HU_Int'])
                parent = str(r['Clean_Parent'])
                if parent in ext_to_int_aud: parent = ext_to_int_aud[parent]
                parent_map_aud[child] = parent

            if df_vepo is not None and not df_vepo.empty:
                vepo_hu_col_aud = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
                valid_base_aud = set(df_vepo[vepo_hu_col_aud].astype(str).str.strip().str.lstrip('0'))
            else:
                valid_base_aud = set(vekp_del['Clean_HU_Int'])

            del_leaves = set(h for h in vekp_del['Clean_HU_Int'] if h in valid_base_aud)
            del_roots = set()
            for leaf in del_leaves:
                curr = leaf
                visited = set()
                while curr in parent_map_aud and parent_map_aud[curr] != "" and curr not in visited:
                    visited.add(curr)
                    curr = parent_map_aud[curr]
                del_roots.add(curr)

            def get_audit_status(row):
                h = str(row['Clean_HU_Int'])
                if sel_del_kat.startswith("E") or sel_del_kat.startswith("OE"):
                    if h in del_leaves: return "✅ Účtuje se (Paket)"
                    return "❌ Neúčtuje se (Nadřazený obal / Prázdná)"
                else:
                    if h in del_roots: return "✅ Účtuje se (Paleta)"
                    return "❌ Neúčtuje se (Obalová hierarchie / Prázdná)"

            vekp_del['Status pro fakturaci'] = vekp_del.apply(get_audit_status, axis=1)
            
            auto_voll_hus_aud = st.session_state.get('auto_voll_hus', set())
            if c_hu_ext_aud:
                vekp_del['Status pro fakturaci'] = vekp_del.apply(
                    lambda r: "🏭 Účtuje se (Vollpalette)" if (str(r['Clean_HU_Ext']) in auto_voll_hus_aud and "✅" in r['Status pro fakturaci']) else r['Status pro fakturaci'], axis=1
                )

            hu_count = len(vekp_del[vekp_del['Status pro fakturaci'].str.contains('✅') | vekp_del['Status pro fakturaci'].str.contains('🏭')])
            st.metric("Zabalených HU (VEKP)", hu_count)
            
            with st.expander("Zobrazit hierarchii obalů"):
                disp_cols = [c_hu_ext_aud, 'Packaging materials', 'Total Weight', 'Status pro fakturaci']
                disp_v = vekp_del[[c for c in disp_cols if c in vekp_del.columns]].copy()
                def color_status(val):
                    if '✅' in str(val) or '🏭' in str(val): return 'color: green; font-weight: bold'
                    if '❌' in str(val): return 'color: #d62728; text-decoration: line-through'
                    return ''
                st.dataframe(disp_v.style.map(color_status, subset=['Status pro fakturaci']), hide_index=True, use_container_width=True)
        else: st.info("Chybí soubor VEKP pro druhou fázi.")

        st.markdown("#### 3️⃣ Fáze: Čas u balícího stolu (OE-Times)")
        if df_oe is not None:
            oe_del = df_oe[df_oe['Delivery'] == sel_del]
            if not oe_del.empty:
                ro = oe_del.iloc[0]
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Procesní čas", f"{ro.get('Process_Time_Min', 0):.1f} min")
                cc2.metric("Pracovník / Směna", str(ro.get('Shift', '-')))
                cc3.metric("Počet druhů zboží", str(ro.get('Num_Items', '-')))
                with st.expander("Zobrazit kompletní záznam balení"): st.dataframe(oe_del, hide_index=True, use_container_width=True)
            else: st.info("K této zakázce nebyl v souboru OE-Times nalezen žádný záznam.")
