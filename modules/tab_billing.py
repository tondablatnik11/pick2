import streamlit as st
import pandas as pd
import numpy as np
from modules.utils import t

def render_billing(df_pick, df_vekp, df_vepo, df_cats, queue_count_col, aus_data):
    st.markdown(f"<div class='section-header'><h3>💰 Korelace mezi Pickováním a Fakturací</h3><p>Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.</p></div>", unsafe_allow_html=True)
    
    aus_category_map = {}
    if aus_data:
        df_likp_tmp = aus_data.get("LIKP", pd.DataFrame())
        df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame())
        df_t031_tmp = aus_data.get("T031", pd.DataFrame())
        kep_set = set()
        if not df_sdshp_tmp.empty:
            col_s = df_sdshp_tmp.columns[0]
            col_k = next((c for c in df_sdshp_tmp.columns if "KEP" in str(c).upper() or "FÄHIG" in str(c).upper()), None)
            if col_k: kep_set = set(df_sdshp_tmp.loc[df_sdshp_tmp[col_k].astype(str).str.strip() == "X", col_s].astype(str).str.strip())
        order_type_map = {}
        if not df_t031_tmp.empty: order_type_map = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))
        if not df_likp_tmp.empty:
            c_lief = df_likp_tmp.columns[0]
            c_vs = next((c for c in df_likp_tmp.columns if "Versandstelle" in str(c) or "Shipping" in str(c)), None)
            c_sped = next((c for c in df_likp_tmp.columns if "pediteur" in str(c) or "Transp" in str(c)), None)
            tmp_lf = df_likp_tmp[[c_lief]].copy()
            tmp_lf.columns = ["Lieferung"]
            tmp_lf["Lieferung"] = tmp_lf["Lieferung"].astype(str).str.strip()
            tmp_lf["Order_Type"] = df_likp_tmp[c_vs].astype(str).str.strip().map(order_type_map).fillna("N") if c_vs else "N"
            tmp_lf["is_KEP"] = df_likp_tmp[c_sped].astype(str).str.strip().isin(kep_set) if c_sped else False
            tmp_lf["Kategorie"] = np.where(tmp_lf["is_KEP"], np.where(tmp_lf["Order_Type"] == "O", "OE", "E"), np.where(tmp_lf["Order_Type"] == "O", "O", "N"))
            aus_category_map = tmp_lf.set_index("Lieferung")["Kategorie"].to_dict()

    billing_df = pd.DataFrame()
    if df_vekp is not None and not df_vekp.empty:
        vekp_c = df_vekp.dropna(subset=["Handling Unit", "Generated delivery"]).copy()
        vekp_filtered = vekp_c[vekp_c["Generated delivery"].isin(df_pick["Delivery"].dropna().unique())].copy()
        c_hu_int = next((c for c in vekp_filtered.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_filtered.columns[0])
        c_hu_ext = vekp_filtered.columns[1]
        c_parent = next((c for c in vekp_filtered.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower()), None)
        
        vekp_filtered['Clean_HU_Int'] = vekp_filtered[c_hu_int].astype(str).str.strip().str.lstrip('0')
        vekp_filtered['Clean_HU_Ext'] = vekp_filtered[c_hu_ext].astype(str).str.strip().str.lstrip('0')
        if c_parent: vekp_filtered['Clean_Parent'] = vekp_filtered[c_parent].astype(str).str.strip().str.lstrip('0').replace({'nan': '', 'none': ''})
        else: vekp_filtered['Clean_Parent'] = ""

        valid_base_hus = set()
        if df_vepo is not None and not df_vepo.empty:
            v_hu = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
            v_low = next((c for c in df_vepo.columns if "Lower-level" in str(c) or "untergeordn" in str(c).lower()), None)
            valid_base_hus = set(df_vepo[v_hu].astype(str).str.strip().str.lstrip('0'))
            if v_low: valid_base_hus.update(set(df_vepo[v_low].dropna().astype(str).str.strip().str.lstrip('0')))
        else:
            valid_base_hus = set(vekp_filtered['Clean_HU_Int'])

        hu_agg_list = []
        for delivery, group in vekp_filtered.groupby("Generated delivery"):
            ext_to_int = dict(zip(group['Clean_HU_Ext'], group['Clean_HU_Int']))
            p_map = {}
            for _, r in group.iterrows():
                child = str(r['Clean_HU_Int'])
                parent = str(r['Clean_Parent'])
                if parent in ext_to_int: parent = ext_to_int[parent]
                p_map[child] = parent
            
            leaves = [h for h in group['Clean_HU_Int'] if h in valid_base_hus]
            roots = set()
            for leaf in leaves:
                curr = leaf
                visited = set()
                while curr in p_map and p_map[curr] != "" and curr not in visited:
                    visited.add(curr)
                    curr = p_map[curr]
                roots.add(curr)
            hu_agg_list.append({"Delivery": delivery, "hu_leaf": len(leaves), "hu_top_level": len(roots)})
        
        hu_agg = pd.DataFrame(hu_agg_list)
        pick_agg = df_pick.groupby("Delivery").agg(
            pocet_to=(queue_count_col, "nunique"), pohyby_celkem=("Pohyby_Rukou", "sum"), pocet_lokaci=("Source Storage Bin", "nunique"), hlavni_fronta=("Queue", "first"), pocet_mat=("Material", "nunique")
        ).reset_index()

        billing_df = pd.merge(pick_agg, hu_agg, on="Delivery", how="left")

        def odvod_kategorii(row):
            kat = aus_category_map.get(row["Delivery"])
            if not kat:
                q = str(row.get('hlavni_fronta', '')).upper()
                if 'PI_PA_OE' in q: kat = "OE"
                elif 'PI_PA' in q: kat = "E"
                elif 'PI_PL_FUOE' in q or 'PI_PL_OE' in q: kat = "O"
                elif 'PI_PL' in q: kat = "N"
            art = "Sortenrein" if row.get('pocet_mat', 1) <= 1 else "Misch"
            return f"{kat} {art}" if kat else "Bez kategorie"

        billing_df["Category_Full"] = billing_df.apply(odvod_kategorii, axis=1)

        def urci_konecnou_hu(row):
            kat = str(row.get('Category_Full', '')).upper()
            if kat.startswith('E') or kat.startswith('OE'): return row.get('hu_leaf', 0)
            else: return row.get('hu_top_level', 0)

        billing_df['pocet_hu'] = billing_df.apply(urci_konecnou_hu, axis=1).fillna(0).astype(int)
        billing_df['TO_navic'] = (billing_df['pocet_to'] - billing_df['pocet_hu']).clip(lower=0).astype(int)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Zakázek celkem", f"{len(billing_df):,}")
        c2.metric("Fakturované palety/krabice (HU)", f"{int(billing_df['pocet_hu'].sum()):,}")
        c3.metric("Fyzických Pick TO", f"{int(billing_df['pocet_to'].sum()):,}")
        c4.metric("Nefakturované Picky (TO navíc)", f"{int(billing_df['TO_navic'].sum()):,}", delta_color="inverse")

        st.markdown(f"### ⚠️ Ztráta z konsolidace (Práce zdarma / Prodělek)")
        imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
        if not imb_df.empty:
            imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
            imb_disp.columns = ["Delivery", "Kategorie", "Pick TO celkem", "Pohyby rukou", "Účtované HU", "TO navíc (Rozdíl)"]
            st.dataframe(imb_disp.style.background_gradient(subset=["TO navíc (Rozdíl)"], cmap='Reds'), use_container_width=True, hide_index=True)
        else: st.success("Žádné zakázky s prodělkem nenalezeny!")
    else:
        st.warning("⚠️ Pro zobrazení těchto dat nahrajte soubor VEKP a VEPO.")

    return billing_df
