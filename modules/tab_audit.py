import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import get_match_key

def render_audit(df_pick, df_vekp, df_vepo, df_oe, queue_count_col, billing_df, manual_boxes, weight_dict, dim_dict, box_dict, limit_vahy, limit_rozmeru, kusy_na_hmat):
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
        mat_search = st.selectbox("Zkontrolujte si konkrétní materiál:", options=[""] + sorted(df_pick['Material'].unique().tolist()))
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
    sel_del = st.selectbox("Vyberte Delivery pro kompletní rentgen:", options=[""] + sorted(df_pick['Delivery'].dropna().unique()))
    if sel_del:
        st.markdown("#### 1️⃣ Fáze: Pickování ve skladu")
        pick_del = df_pick[df_pick['Delivery'] == sel_del]
        c1, c2 = st.columns(2)
        c1.metric("Počet úkolů (TO)", pick_del[queue_count_col].nunique())
        c2.metric("Fyzických pohybů", int(pick_del['Pohyby_Rukou'].sum()))

        st.markdown("#### 2️⃣ Fáze: Systémové Obaly (VEKP)")
        if df_vekp is not None and not df_vekp.empty:
            vekp_del = df_vekp[df_vekp['Generated delivery'] == sel_del].copy()
            st.dataframe(vekp_del, hide_index=True, use_container_width=True)
        else: st.info("Chybí soubor VEKP pro druhou fázi.")

        st.markdown("#### 3️⃣ Fáze: Čas u balícího stolu (OE-Times)")
        if df_oe is not None:
            oe_del = df_oe[df_oe['Delivery'] == sel_del]
            if not oe_del.empty:
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Procesní čas", f"{oe_del.iloc[0].get('Process_Time_Min', 0):.1f} min")
                st.dataframe(oe_del, hide_index=True, use_container_width=True)
            else: st.info("K této zakázce nebyl v souboru OE-Times nalezen žádný záznam.")
