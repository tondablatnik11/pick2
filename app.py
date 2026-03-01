import streamlit as st
import pandas as pd
import numpy as np
import time
import re

# Databáze a výpočty
from database import save_to_db, load_from_db
from modules.utils import fast_compute_moves, get_match_key_vectorized, get_match_key, parse_packing_time, BOX_UNITS

# Záložky (Tabs)
from modules.tab_dashboard import render_dashboard
from modules.tab_pallets import render_pallets
from modules.tab_fu import render_fu
from modules.tab_top import render_top
from modules.tab_billing import render_billing
from modules.tab_packing import render_packing
from modules.tab_audit import render_audit

# ==========================================
# 1. NASTAVENÍ STRÁNKY A STYLING
# ==========================================
st.set_page_config(page_title="Warehouse Control Tower", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] { background-color: #ffffff; border: 1px solid #e2e8f0; padding: 1rem 1.5rem; border-radius: 0.75rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    .main-header { font-size: 2.75rem; font-weight: 800; background: -webkit-linear-gradient(45deg, #1e3a8a, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.1rem; color: #64748b; margin-bottom: 2rem; font-weight: 500; }
    .section-header { color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; margin-top: 2rem; margin-bottom: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CACHE PRO NAČTENÍ Z DATABÁZE
# ==========================================
@st.cache_data(show_spinner=False, ttl=3600)
def fetch_and_prep_data():
    df_pick_raw = load_from_db('raw_pick')
    if df_pick_raw is None or df_pick_raw.empty: return None

    df_marm_raw = load_from_db('raw_marm')
    df_queue_raw = load_from_db('raw_queue')
    df_manual_raw = load_from_db('raw_manual')

    # Čištění pick reportu
    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick['Material'] = df_pick['Material'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    
    # OPRAVA 1: CHYBĚJÍCÍ FILTR ADMINŮ
    num_removed_admins = 0
    if 'User' in df_pick.columns:
        mask_admins = df_pick['User'].isin(['UIDJ5089', 'UIH25501'])
        num_removed_admins = int(mask_admins.sum())
        df_pick = df_pick[~mask_admins].copy()

    df_pick['Match_Key'] = get_match_key_vectorized(df_pick['Material'])
    df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
    df_pick['Source Storage Bin'] = df_pick.get('Source Storage Bin', df_pick.get('Storage Bin', '')).fillna('').astype(str)
    df_pick['Removal of total SU'] = df_pick.get('Removal of total SU', '').fillna('').astype(str).str.strip().str.upper()
    df_pick['Date'] = pd.to_datetime(df_pick.get('Confirmation date', df_pick.get('Confirmation Date')), errors='coerce')
    
    queue_count_col = 'Delivery'
    df_pick['Queue'] = 'N/A'
    if df_queue_raw is not None and not df_queue_raw.empty:
        if 'Transfer Order Number' in df_pick.columns and 'Transfer Order Number' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue']).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
            queue_count_col = 'Transfer Order Number'
            
            # OPRAVA 2: CHYBĚJÍCÍ DOPLŇOVÁNÍ DATUMŮ
            for d_col in ['Confirmation Date', 'Creation Date']:
                if d_col in df_queue_raw.columns:
                    d_map = df_queue_raw.dropna(subset=['Transfer Order Number', d_col]).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')[d_col].to_dict()
                    to_dates = df_pick['Transfer Order Number'].map(d_map)
                    df_pick['Date'] = df_pick['Date'].fillna(pd.to_datetime(to_dates, errors='coerce'))
                    break
        elif 'SD Document' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['SD Document', 'Queue']).drop_duplicates('SD Document').set_index('SD Document')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Delivery'].map(q_map).fillna('N/A')

        # OPRAVA 3: CHYBĚJÍCÍ FILTR CLEARANCE
        df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

    # Zpracování Master Dat (Obaly, váhy a rozměry)
    manual_boxes = {}
    if df_manual_raw is not None and not df_manual_raw.empty:
        c_mat, c_pkg = df_manual_raw.columns[0], df_manual_raw.columns[1]
        for _, row in df_manual_raw.iterrows():
            raw_mat = str(row[c_mat])
            if raw_mat.upper() in ['NAN', 'NONE', '']: continue
            mat_key = get_match_key(raw_mat)
            pkg = str(row[c_pkg])
            nums = re.findall(r'\bK-(\d+)ks?\b|(\d+)\s*ks\b|balen[íi]\s+po\s+(\d+)|krabice\s+(?:po\s+)?(\d+)|(?:role|pytl[íi]k|pytel)[^\d]*(\d+)', pkg, flags=re.IGNORECASE)
            ext = sorted(list(set([int(g) for m in nums for g in m if g])), reverse=True)
            if not ext and re.search(r'po\s*kusech', pkg, re.IGNORECASE): ext = [1]
            if ext: manual_boxes[mat_key] = ext

    box_dict, weight_dict, dim_dict = {}, {}, {}
    if df_marm_raw is not None and not df_marm_raw.empty:
        df_marm_raw['Match_Key'] = get_match_key_vectorized(df_marm_raw['Material'])
        df_boxes = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(BOX_UNITS)].copy()
        df_boxes['Numerator'] = pd.to_numeric(df_boxes['Numerator'], errors='coerce').fillna(0)
        box_dict = df_boxes.groupby('Match_Key')['Numerator'].apply(lambda g: sorted([int(x) for x in g if x > 1], reverse=True)).to_dict()

        df_st = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(['ST', 'PCE', 'KS', 'EA', 'PC'])].copy()
        df_st['Gross Weight'] = pd.to_numeric(df_st['Gross Weight'], errors='coerce').fillna(0)
        df_st['Weight_KG'] = np.where(df_st['Unit of Weight'].astype(str).str.upper() == 'G', df_st['Gross Weight'] / 1000.0, df_st['Gross Weight'])
        weight_dict = df_st.groupby('Match_Key')['Weight_KG'].first().to_dict()

        def to_cm(val, unit):
            try:
                v = float(val); u = str(unit).upper().strip()
                return v / 10.0 if u == 'MM' else v * 100.0 if u == 'M' else v
            except: return 0.0

        for dim_col, short in [('Length', 'L'), ('Width', 'W'), ('Height', 'H')]:
            if dim_col in df_st.columns: df_st[short] = df_st.apply(lambda r, dc=dim_col: to_cm(r[dc], r.get('Unit of Dimension', 'CM')), axis=1)
            else: df_st[short] = 0.0
        dim_dict = df_st.set_index('Match_Key')[['L', 'W', 'H']].max(axis=1).to_dict()

    df_pick['Box_Sizes_List'] = df_pick['Match_Key'].apply(lambda m: manual_boxes.get(m, box_dict.get(m, [])))
    df_pick['Piece_Weight_KG'] = df_pick['Match_Key'].map(weight_dict).fillna(0.0)
    df_pick['Piece_Max_Dim_CM'] = df_pick['Match_Key'].map(dim_dict).fillna(0.0)

    # Vollpalety
    auto_voll_hus = set()
    mask_x = df_pick['Removal of total SU'] == 'X'
    if 'Handling Unit' in df_pick.columns: auto_voll_hus.update(df_pick.loc[mask_x, 'Handling Unit'].dropna().astype(str).str.strip())
    auto_voll_hus = {h for h in auto_voll_hus if h not in ["", "nan", "None"]}

    # OE-Times úprava
    df_oe = load_from_db('raw_oe')
    if df_oe is not None and not df_oe.empty:
        df_oe['Delivery'] = df_oe['DN NUMBER (SAP)'].astype(str).str.strip()
        df_oe['Process_Time_Min'] = df_oe['Process Time'].apply(parse_packing_time)
        
        agg_dict = {'Process_Time_Min': 'sum'}
        if 'CUSTOMER' in df_oe.columns: agg_dict['CUSTOMER'] = 'first'
        if 'Material' in df_oe.columns: agg_dict['Material'] = 'first'
        if 'KLT' in df_oe.columns: agg_dict['KLT'] = lambda x: '; '.join(x.dropna().astype(str))
        if 'Palety' in df_oe.columns: agg_dict['Palety'] = lambda x: '; '.join(x.dropna().astype(str))
        if 'Cartons' in df_oe.columns: agg_dict['Cartons'] = lambda x: '; '.join(x.dropna().astype(str))
        if 'Scanning serial numbers' in df_oe.columns: agg_dict['Scanning serial numbers'] = 'first'
        if 'Reprinting labels ' in df_oe.columns: agg_dict['Reprinting labels '] = 'first'
        if 'Difficult KLTs' in df_oe.columns: agg_dict['Difficult KLTs'] = 'first'
        if 'Shift' in df_oe.columns: agg_dict['Shift'] = 'first'
        if 'Number of item types' in df_oe.columns: agg_dict['Number of item types'] = 'first'
        
        df_oe = df_oe.groupby('Delivery').agg(agg_dict).reset_index()

    df_cats = load_from_db('raw_cats')
    if df_cats is not None and not df_cats.empty:
        df_cats['Lieferung'] = df_cats['Lieferung'].astype(str).str.strip()
        if 'Kategorie' in df_cats.columns and 'Art' in df_cats.columns:
            df_cats['Category_Full'] = df_cats['Kategorie'].astype(str).str.strip() + " " + df_cats['Art'].astype(str).str.strip()
        df_cats = df_cats.drop_duplicates('Lieferung')

    aus_data = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None: aus_data[sheet] = aus_df

    return {
        'df_pick': df_pick, 'queue_count_col': queue_count_col, 'auto_voll_hus': auto_voll_hus,
        'df_vekp': load_from_db('raw_vekp'), 'df_vepo': load_from_db('raw_vepo'),
        'df_cats': df_cats, 'df_oe': df_oe, 'aus_data': aus_data,
        'num_removed_admins': num_removed_admins, 'manual_boxes_count': len(manual_boxes)
    }

# ==========================================
# 3. HLAVNÍ BĚH APLIKACE
# ==========================================
def main():
    st.markdown(f"<div class='main-header'>🏢 Warehouse Control Tower</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sub-header'>End-to-End analýza (Modulární architektura)</div>", unsafe_allow_html=True)

    st.sidebar.header("⚙️ Konfigurace algoritmů")
    limit_vahy = st.sidebar.number_input("Hranice váhy (kg)", min_value=0.1, max_value=20.0, value=2.0, step=0.5)
    limit_rozmeru = st.sidebar.number_input("Hranice rozměru (cm)", min_value=1.0, max_value=200.0, value=15.0, step=1.0)
    kusy_na_hmat = st.sidebar.slider("Ks do hrsti", min_value=1, max_value=20, value=1, step=1)

    st.sidebar.divider()
    with st.sidebar.expander("🛠️ Admin Zóna (Nahrát data do DB)"):
        st.info("Nahrajte Excely sem. Zpracují se do databáze a aplikace poběží bleskově.")
        admin_pwd = st.text_input("Heslo:", type="password")
        if admin_pwd == "admin123":
            uploaded_files = st.file_uploader("Nahrát CSV/Excel", accept_multiple_files=True)
            if st.button("Uložit do databáze", type="primary") and uploaded_files:
                with st.spinner("Zpracovávám a ukládám do Supabase..."):
                    for file in uploaded_files:
                        fname = file.name.lower()
                        if fname.endswith('.xlsx') and 'auswertung' in fname:
                            aus_xl = pd.ExcelFile(file)
                            for sn in aus_xl.sheet_names: save_to_db(aus_xl.parse(sn, dtype=str), f"aus_{sn.lower()}")
                            continue
                        temp_df = pd.read_csv(file, dtype=str) if fname.endswith('.csv') else pd.read_excel(file, dtype=str)
                        cols = set(temp_df.columns)
                        if 'Delivery' in cols and 'Act.qty (dest)' in cols: save_to_db(temp_df, 'raw_pick')
                        elif 'Numerator' in cols and 'Alternative Unit of Measure' in cols: save_to_db(temp_df, 'raw_marm')
                        elif 'Handling Unit' in cols and 'Generated delivery' in cols: save_to_db(temp_df, 'raw_vekp')
                        elif ('Handling unit item' in cols or 'Handling Unit Position' in cols) and 'Material' in cols: save_to_db(temp_df, 'raw_vepo')
                        elif 'Lieferung' in cols and 'Kategorie' in cols: save_to_db(temp_df, 'raw_cats')
                        elif 'Queue' in cols and ('Transfer Order Number' in cols or 'SD Document' in cols): save_to_db(temp_df, 'raw_queue')
                        elif 'DN NUMBER (SAP)' in cols and 'Process Time' in cols: save_to_db(temp_df, 'raw_oe')
                        elif len(temp_df.columns) >= 2: save_to_db(temp_df, 'raw_manual')
                    st.cache_data.clear()
                    st.success("✅ Hotovo! Data jsou v databázi.")
                    time.sleep(1.5)
                    st.rerun()

    with st.spinner("🔄 Načítám data z databáze..."):
        data_dict = fetch_and_prep_data()

    if data_dict is None:
        st.warning("🗄️ Databáze je zatím prázdná. Otevřete levé menu 'Admin Zóna', zadejte heslo 'admin123' a nahrajte Pick Report a další soubory.")
        return

    df_pick = data_dict['df_pick']
    st.session_state['auto_voll_hus'] = data_dict['auto_voll_hus']
    num_removed_admins = data_dict['num_removed_admins']
    manual_boxes_count = data_dict['manual_boxes_count']

    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
    st.sidebar.divider()
    date_mode = st.sidebar.radio("Filtr období:", ['Celé období', 'Podle měsíce'], label_visibility="collapsed")
    if date_mode == 'Podle měsíce':
        df_pick = df_pick[df_pick['Month'] == st.sidebar.selectbox("Vyberte měsíc:", options=sorted(df_pick['Month'].unique()))].copy()

    tt, te, tm = fast_compute_moves(df_pick['Qty'].values, df_pick['Queue'].values, df_pick['Removal of total SU'].values, df_pick['Box_Sizes_List'].values, df_pick['Piece_Weight_KG'].values, df_pick['Piece_Max_Dim_CM'].values, limit_vahy, limit_rozmeru, kusy_na_hmat)
    df_pick['Pohyby_Rukou'], df_pick['Pohyby_Exact'], df_pick['Pohyby_Loose_Miss'] = tt, te, tm
    df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

    # OPRAVA 4: CHYBĚJÍCÍ INFORMAČNÍ HLÁŠKY
    c_i1, c_i2, c_i3 = st.columns(3)
    if num_removed_admins > 0:
        c_i1.info(f"💡 Vyloučeno **{num_removed_admins} systémových řádků** (UIDJ5089, UIH25501).")
    x_c = ((df_pick['Removal of total SU'] == 'X') & (df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE']))).sum()
    if x_c > 0:
        c_i2.warning(f"💡 Započítán 1 pohyb pro **{x_c} řádků** 'X' (Platí POUZE pro Queue: PI_PL_FU, PI_PL_FUOE).")
    if manual_boxes_count > 0:
        c_i3.success(f"✅ Načteno ruční ověření pro **{manual_boxes_count} unikátních materiálů**.")

    tabs = st.tabs(["📊 Dashboard & Queue", "📦 Palety", "🏭 Celé palety (FU)", "🏆 TOP Materiály", "💰 Fakturace (VEKP)", "⏱️ Časy Balení (OE)", "🔍 Detailní Audit"])

    with tabs[0]: render_dashboard(df_pick, data_dict['queue_count_col'])
    with tabs[1]: render_pallets(df_pick)
    with tabs[2]: render_fu(df_pick, data_dict['queue_count_col'])
    with tabs[3]: render_top(df_pick)
    with tabs[4]: billing_df = render_billing(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_cats'], data_dict['queue_count_col'], data_dict['aus_data'])
    with tabs[5]: render_packing(billing_df if 'billing_df' in locals() else pd.DataFrame(), data_dict['df_oe'])
    with tabs[6]: render_audit(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_oe'], data_dict['queue_count_col'], billing_df if 'billing_df' in locals() else pd.DataFrame())

if __name__ == "__main__":
    main()
