import streamlit as st
import plotly.express as px
import pandas as pd
import numpy as np
import io
import re
import time

# NOVÝ IMPORT Z NAŠEHO SOUBORU DATABASE.PY
from database import save_to_db, load_from_db

# ==========================================
# 1. NASTAVENÍ STRÁNKY A PROFESIONÁLNÍ CSS
# ==========================================
st.set_page_config(page_title="Warehouse Control Tower", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0; padding: 1rem 1.5rem;
        border-radius: 0.75rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    div[data-testid="metric-container"] > div > div > div > div { color: #1e293b !important; font-weight: 700 !important; }
    .main-header { font-size: 2.75rem; font-weight: 800; background: -webkit-linear-gradient(45deg, #1e3a8a, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.1rem; color: #64748b; margin-bottom: 2rem; font-weight: 500; }
    .section-header { color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; margin-top: 2rem; margin-bottom: 1.5rem; }
    .stDataFrame { border-radius: 0.5rem !important; overflow: hidden !important; box-shadow: 0 1px 3px 0 rgba(0,0,0,0.1) !important; }
    </style>
""", unsafe_allow_html=True)

if 'lang' not in st.session_state: st.session_state.lang = 'cs'

QUEUE_DESC = {
    'PI_PL (Mix)': 'Mix Pallet', 'PI_PL (Total)': 'Mix Pallet', 'PI_PL (Single)': 'Mix Pallet',
    'PI_PL_OE (Mix)': 'Mix Pallet OE', 'PI_PA_OE': 'Parcel OE', 'PI_PL_OE (Total)': 'Mix Pallet OE',
    'PI_PL_OE (Single)': 'Mix Pallet OE', 'PI_PA': 'Parcel', 'PI_PA_RU': 'Parcel Express',
    'PI_PL_FU': 'Full Pallet', 'PI_PL_FUOE': 'Full Pallet OE'
}
BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

# -- Pro úsporu místa jsou texty zkráceny, aplikace použije defaultní názvy --
def t(key): return key 

# ==========================================
# 2. POMOCNÉ FUNKCE
# ==========================================
def get_match_key_vectorized(series):
    s = series.astype(str).str.strip().str.upper()
    mask_decimal = s.str.match(r'^\d+\.\d+$')
    s = s.copy(); s[mask_decimal] = s[mask_decimal].str.rstrip('0').str.rstrip('.')
    mask_numeric = s.str.match(r'^0+\d+$')
    s[mask_numeric] = s[mask_numeric].str.lstrip('0')
    return s

def get_match_key(val):
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit(): v = v.rstrip('0').rstrip('.')
    if v.isdigit(): v = v.lstrip('0') or '0'
    return v

def parse_packing_time(val):
    v = str(val).strip()
    if v in ['', 'nan', 'None', 'NaN']: return 0.0
    try:
        num = float(v)
        if num < 1.0: return num * 24 * 60
        return num
    except: pass
    parts = v.split(':')
    try:
        if len(parts) == 3: return int(parts[0])*60 + int(parts[1]) + float(parts[2])/60.0
        elif len(parts) == 2: return int(parts[0]) + float(parts[1])/60.0
    except: pass
    return 0.0

def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list, v_lim, d_lim, h_lim):
    res_total, res_exact, res_miss = [], [], []
    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list, box_list, w_list, d_list):
        if qty <= 0:
            res_total.append(0); res_exact.append(0); res_miss.append(0); continue
        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1); res_exact.append(1); res_miss.append(0); continue
        
        if not isinstance(boxes, list): boxes = []
        real_boxes = [b for b in boxes if b > 1]
        pb = pok = pmiss = 0
        zbytek = qty
        
        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b); pb += m; zbytek = zbytek % b
                
        if zbytek > 0:
            if w >= v_lim or d >= d_lim: p = int(zbytek)
            else: p = int(np.ceil(zbytek / h_lim))
            if len(boxes) > 0: pok += p
            else: pmiss += p
            
        res_total.append(pb + pok + pmiss); res_exact.append(pb + pok); res_miss.append(pmiss)
    return res_total, res_exact, res_miss

# ==========================================
# 3. ZPRACOVÁNÍ A NAČÍTÁNÍ DAT (S CACHE)
# ==========================================
@st.cache_data(show_spinner=False, ttl=3600)
def fetch_and_prep_data():
    """Tato funkce se spustí jen jednou za hodinu. Stáhne data z DB a přechroustá je v paměti."""
    df_pick_raw = load_from_db('raw_pick')
    if df_pick_raw is None or df_pick_raw.empty: return None

    df_marm_raw = load_from_db('raw_marm')
    df_queue_raw = load_from_db('raw_queue')
    df_vekp_raw = load_from_db('raw_vekp')
    df_vepo_raw = load_from_db('raw_vepo')
    df_cats_raw = load_from_db('raw_cats')
    df_oe_raw = load_from_db('raw_oe')
    df_manual_raw = load_from_db('raw_manual')
    
    st.session_state['auswertung_raw'] = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None: st.session_state['auswertung_raw'][sheet] = aus_df

    # --- ČIŠTĚNÍ PICK REPORTU ---
    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip().replace(['nan', 'NaN', 'None', ''], np.nan)
    df_pick['Material'] = df_pick['Material'].astype(str).str.strip().replace(['nan', 'NaN', 'None', ''], np.nan)
    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    df_pick['Match_Key'] = get_match_key_vectorized(df_pick['Material'])
    df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
    df_pick['Source Storage Bin'] = df_pick.get('Source Storage Bin', df_pick.get('Storage Bin', '')).fillna('').astype(str)
    df_pick['Removal of total SU'] = df_pick.get('Removal of total SU', '').fillna('').astype(str).str.strip().str.upper()
    df_pick['Date'] = pd.to_datetime(df_pick.get('Confirmation date', df_pick.get('Confirmation Date')), errors='coerce')

    if 'User' in df_pick.columns:
        mask_admins = df_pick['User'].isin(['UIDJ5089', 'UIH25501'])
        num_removed_admins = int(mask_admins.sum())
        df_pick = df_pick[~mask_admins].copy()
    else: num_removed_admins = 0

    queue_count_col = 'Delivery'
    df_pick['Queue'] = 'N/A'
    if df_queue_raw is not None and not df_queue_raw.empty:
        if 'Transfer Order Number' in df_pick.columns and 'Transfer Order Number' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue']).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
            queue_count_col = 'Transfer Order Number'
        elif 'SD Document' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['SD Document', 'Queue']).drop_duplicates('SD Document').set_index('SD Document')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Delivery'].map(q_map).fillna('N/A')
        df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

    # --- BALENÍ A MASTER DATA ---
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

    if df_vekp_raw is not None and not df_vekp_raw.empty: df_vekp_raw['Generated delivery'] = df_vekp_raw['Generated delivery'].astype(str).str.strip()
    if df_cats_raw is not None and not df_cats_raw.empty:
        df_cats_raw['Lieferung'] = df_cats_raw['Lieferung'].astype(str).str.strip()
        df_cats_raw['Category_Full'] = df_cats_raw['Kategorie'].astype(str).str.strip() + " " + df_cats_raw['Art'].astype(str).str.strip()
        df_cats_raw = df_cats_raw.drop_duplicates('Lieferung')

    if df_oe_raw is not None and not df_oe_raw.empty:
        df_oe_raw['Delivery'] = df_oe_raw['DN NUMBER (SAP)'].astype(str).str.strip()
        df_oe_raw['Process_Time_Min'] = df_oe_raw['Process Time'].apply(parse_packing_time)
        df_oe_raw = df_oe_raw.groupby('Delivery').agg(
            Process_Time_Min=('Process_Time_Min', 'sum'), CUSTOMER=('CUSTOMER', 'first'), Material=('Material', 'first'),
            KLT=('KLT', lambda x: '; '.join(x.dropna().astype(str))), Palety=('Palety', lambda x: '; '.join(x.dropna().astype(str))),
            Cartons=('Cartons', lambda x: '; '.join(x.dropna().astype(str))), Scan_SN=('Scanning serial numbers', 'first'),
            Reprint=('Reprinting labels ', 'first'), Diff_KLT=('Difficult KLTs', 'first'), Shift=('Shift', 'first'), Num_Items=('Number of item types', 'first')
        ).reset_index()

    auto_voll_hus = set()
    mask_x = df_pick['Removal of total SU'] == 'X'
    for c_hu in ['Source storage unit', 'Handling Unit']:
        if c_hu in df_pick.columns: auto_voll_hus.update(df_pick.loc[mask_x, c_hu].dropna().astype(str).str.strip())
    auto_voll_hus = {h for h in auto_voll_hus if h not in ["", "nan", "None"]}

    return {
        'df_pick': df_pick, 'queue_count_col': queue_count_col, 'num_removed_admins': num_removed_admins,
        'manual_boxes': manual_boxes, 'df_vekp': df_vekp_raw, 'df_vepo': df_vepo_raw, 'df_cats': df_cats_raw,
        'df_oe': df_oe_raw, 'auto_voll_hus': auto_voll_hus
    }

# ==========================================
# 4. HLAVNÍ BĚH APLIKACE A ADMIN ZÓNA
# ==========================================
def main():
    col_title, col_lang = st.columns([8, 1])
    with col_title:
        st.markdown(f"<div class='main-header'>🏢 Warehouse Control Tower</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub-header'>End-to-End analýza: Pickování -> Balení -> Fakturace</div>", unsafe_allow_html=True)

    # --- LEVÝ PANEL (PARAMETRY A ADMIN ZÓNA) ---
    st.sidebar.header("⚙️ Konfigurace")
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
                        try:
                            if fname.endswith('.xlsx') and 'auswertung' in fname:
                                aus_xl = pd.ExcelFile(file)
                                for sn in aus_xl.sheet_names:
                                    save_to_db(aus_xl.parse(sn, dtype=str), f"aus_{sn.lower()}")
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
                        except Exception as e:
                            st.error(f"Chyba u {file.name}: {e}")
                    st.cache_data.clear() # Smažeme starou mezipaměť
                    st.success("✅ Hotovo! Data jsou v databázi.")
                    time.sleep(1.5)
                    st.rerun()

    # --- NAČTENÍ A VÝPOČET DAT Z DATABÁZE ---
    with st.spinner("🔄 Načítám data z databáze... (Díky cache to trvá jen zlomek sekundy)"):
        data_dict = fetch_and_prep_data()

    if data_dict is None:
        st.warning("🗄️ Databáze je zatím prázdná. Otevřete levé menu 'Admin Zóna', zadejte heslo 'admin123' a nahrajte Pick Report a další soubory.")
        return

    df_pick = data_dict['df_pick']
    queue_count_col = data_dict['queue_count_col']
    df_vekp = data_dict['df_vekp']
    df_vepo = data_dict['df_vepo']
    df_oe = data_dict['df_oe']
    df_cats = data_dict['df_cats']
    st.session_state['auto_voll_hus'] = data_dict['auto_voll_hus']

    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
    st.sidebar.divider()
    date_mode = st.sidebar.radio("Filtr období:", ['Celé období', 'Podle měsíce'], label_visibility="collapsed")
    if date_mode == 'Podle měsíce':
        sel_month = st.sidebar.selectbox("Vyberte měsíc:", options=sorted(df_pick['Month'].unique()))
        df_pick = df_pick[df_pick['Month'] == sel_month].copy()

    # Fyzické výpočty
    tt, te, tm = fast_compute_moves(df_pick['Qty'].values, df_pick['Queue'].values, df_pick['Removal of total SU'].values,
                                    df_pick['Box_Sizes_List'].values, df_pick['Piece_Weight_KG'].values, df_pick['Piece_Max_Dim_CM'].values,
                                    limit_vahy, limit_rozmeru, kusy_na_hmat)
    df_pick['Pohyby_Rukou'], df_pick['Pohyby_Exact'], df_pick['Pohyby_Loose_Miss'] = tt, te, tm
    df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

    tabs = st.tabs([t('tab_dashboard'), t('tab_pallets'), t('tab_fu'), t('tab_top'), t('tab_billing'), t('tab_packing'), t('tab_audit')])

    # ==========================================
    # TAB 1: DASHBOARD & QUEUE
    # ==========================================
    with tabs[0]:
        display_q = None

        tot_mov = df_pick['Pohyby_Rukou'].sum()
        if tot_mov > 0:
            st.markdown(f"<div class='section-header'><h3>{t('sec_ratio')}</h3><p>{t('ratio_desc')}</p></div>", unsafe_allow_html=True)
            st.markdown(f"**{t('ratio_moves')}**")

            c_r1, c_r2 = st.columns(2)
            with c_r1:
                with st.container(border=True):
                    st.metric(
                        t('ratio_exact'),
                        f"{df_pick['Pohyby_Exact'].sum() / tot_mov * 100:.1f} %",
                        f"{df_pick['Pohyby_Exact'].sum():,.0f} {t('audit_phys_moves').lower()}"
                    )
            with c_r2:
                with st.container(border=True):
                    st.metric(
                        t('ratio_miss'),
                        f"{df_pick['Pohyby_Loose_Miss'].sum() / tot_mov * 100:.1f} %",
                        f"{df_pick['Pohyby_Loose_Miss'].sum():,.0f} {t('audit_phys_moves').lower()}",
                        delta_color="inverse"
                    )
            with st.expander(t('logic_explain_title')):
                st.info(t('logic_explain_text'))

        if (df_pick['Queue'].notna().any() and df_pick['Queue'].nunique() > 1):
            st.markdown(f"<div class='section-header'><h3>{t('sec_queue_title')}</h3></div>", unsafe_allow_html=True)

            df_q_filter = df_pick.copy()

            if not df_q_filter.empty:
                queue_agg_raw = df_q_filter.groupby(
                    [queue_count_col, 'Queue']
                ).agg(
                    celkem_pohybu=('Pohyby_Rukou', 'sum'),
                    pohyby_exact=('Pohyby_Exact', 'sum'),
                    pohyby_miss=('Pohyby_Loose_Miss', 'sum'),
                    total_qty=('Qty', 'sum'),
                    num_materials=('Material', 'nunique'),
                    pocet_lokaci=('Source Storage Bin', 'nunique'),
                    delivery=('Delivery', 'first')
                ).reset_index()

                def adjust_queue_name(row):
                    q_up = str(row['Queue']).upper()
                    if q_up in ['PI_PL', 'PI_PL_OE']:
                        suffix = ' (Single)' if row['num_materials'] == 1 else ' (Mix)'
                        return row['Queue'] + suffix
                    return row['Queue']

                totals_rows = queue_agg_raw[
                    queue_agg_raw['Queue'].str.upper().isin(['PI_PL', 'PI_PL_OE'])
                ].copy()
                totals_rows['Queue'] = totals_rows['Queue'] + ' (Total)'
                queue_agg_raw['Queue'] = queue_agg_raw.apply(adjust_queue_name, axis=1)
                queue_agg_final = pd.concat([queue_agg_raw, totals_rows], ignore_index=True)

                q_sum = queue_agg_final.groupby('Queue').agg(
                    pocet_zakazek=('delivery', 'nunique'),
                    prum_lokaci=('pocet_lokaci', 'mean'),
                    prum_kusu=('total_qty', 'mean'),
                    lokaci_sum=('pocet_lokaci', 'sum'),
                    pohybu_sum=('celkem_pohybu', 'sum'),
                    exact_sum=('pohyby_exact', 'sum'),
                    miss_sum=('pohyby_miss', 'sum')
                ).reset_index()

                if queue_count_col == 'Transfer Order Number':
                    to_counts = queue_agg_final.groupby('Queue')[queue_count_col].nunique()
                    q_sum = q_sum.merge(to_counts.rename('pocet_TO'), on='Queue', how='left')
                else:
                    q_sum['pocet_TO'] = q_sum['pocet_zakazek']

                q_sum['prum_pohybu_lokace'] = np.where(
                    q_sum['lokaci_sum'] > 0, q_sum['pohybu_sum'] / q_sum['lokaci_sum'], 0
                )
                q_sum['prum_exact_lokace'] = np.where(
                    q_sum['lokaci_sum'] > 0, q_sum['exact_sum'] / q_sum['lokaci_sum'], 0
                )
                q_sum['prum_miss_lokace'] = np.where(
                    q_sum['lokaci_sum'] > 0, q_sum['miss_sum'] / q_sum['lokaci_sum'], 0
                )
                q_sum['pct_exact'] = np.where(
                    q_sum['pohybu_sum'] > 0, q_sum['exact_sum'] / q_sum['pohybu_sum'] * 100, 0
                )
                q_sum['pct_miss'] = np.where(
                    q_sum['pohybu_sum'] > 0, q_sum['miss_sum'] / q_sum['pohybu_sum'] * 100, 0
                )
                q_sum['Popis'] = q_sum['Queue'].map(QUEUE_DESC).fillna('')
                q_sum = q_sum.sort_values('prum_pohybu_lokace', ascending=False)

                display_q = q_sum[[
                    'Queue', 'Popis', 'pocet_TO', 'pocet_zakazek', 'prum_lokaci',
                    'prum_pohybu_lokace', 'prum_exact_lokace', 'pct_exact',
                    'prum_miss_lokace', 'pct_miss'
                ]].copy()
                display_q.columns = [
                    t('q_col_queue'), t('q_col_desc'), t('q_col_to'), t('q_col_orders'),
                    t('q_col_loc'), t('q_col_mov_loc'), t('q_col_exact_loc'), t('q_pct_exact'),
                    t('q_col_miss_loc'), t('q_pct_miss')
                ]

                fmt_q = {}
                for c in display_q.columns:
                    if '%' in c:
                        fmt_q[c] = "{:.1f} %"
                    elif c not in [t('q_col_queue'), t('q_col_desc'),
                                   t('q_col_to'), t('q_col_orders')]:
                        fmt_q[c] = "{:.1f}"

                styled_q = (
                    display_q.style.format(fmt_q)
                    .set_properties(
                        subset=[t('q_col_queue'), t('q_col_mov_loc')],
                        **{'font-weight': 'bold', 'color': '#1f77b4',
                           'background-color': 'rgba(31,119,180,0.05)'}
                    )
                )
                col_qt1, col_qt2 = st.columns([2.5, 1.5])
            with col_qt1:
                st.dataframe(styled_q, use_container_width=True, hide_index=True)
            with col_qt2:
                # Moderní Plotly graf
                fig = px.bar(
                    q_sum.drop_duplicates('Queue'), 
                    x='Queue', 
                    y='prum_pohybu_lokace',
                    title='Náročnost (Pohyby na 1 lokaci)',
                    text_auto='.1f', # Ukáže čísla přímo na sloupcích
                    color='prum_pohybu_lokace', # Obarví sloupce podle zátěže
                    color_continuous_scale='Reds' # Čím víc pohybů, tím červenější
                )
                fig.update_layout(xaxis_title="", yaxis_title="Pohyby", coloraxis_showscale=False)
                st.plotly_chart(fig, use_container_width=True)

    # ==========================================
    # TAB 2: PALETOVÉ ZAKÁZKY
    # ==========================================
    with tabs[1]:
        st.markdown(f"<div class='section-header'><h3>{t('sec1_title')}</h3><p>{t('pallets_clean_info')}</p></div>", unsafe_allow_html=True)

        df_pallets_clean = df_pick[
            df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])
        ].copy()

        for col_name in ['Certificate Number']:
            if col_name not in df_pallets_clean.columns:
                df_pallets_clean[col_name] = ''

        if not df_pallets_clean.empty:
            grouped_orders = df_pallets_clean.groupby('Delivery').agg(
                num_materials=('Material', 'nunique'),
                material=('Material', 'first'),
                certs=('Certificate Number', lambda x: ", ".join(
                    [str(v) for v in x.dropna().unique() if str(v) not in ['', 'nan']]
                )),
                total_qty=('Qty', 'sum'),
                num_positions=('Source Storage Bin', 'nunique'),
                celkem_pohybu=('Pohyby_Rukou', 'sum'),
                pohyby_exact=('Pohyby_Exact', 'sum'),
                pohyby_miss=('Pohyby_Loose_Miss', 'sum'),
                vaha_zakazky=('Celkova_Vaha_KG', 'sum'),
                max_rozmer=('Piece_Max_Dim_CM', 'first')
            )

            filtered_orders = grouped_orders[grouped_orders['num_materials'] == 1].copy()

            if not filtered_orders.empty:
                filtered_orders['mov_per_loc'] = np.where(
                    filtered_orders['num_positions'] > 0,
                    filtered_orders['celkem_pohybu'] / filtered_orders['num_positions'], 0
                )

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    with st.container(border=True): st.metric(t('m_orders'), f"{len(filtered_orders):,}".replace(',', ' '))
                with c2:
                    with st.container(border=True): st.metric(t('m_qty'), f"{filtered_orders['total_qty'].mean():.1f}")
                with c3:
                    with st.container(border=True): st.metric(t('m_pos'), f"{filtered_orders['num_positions'].mean():.2f}")
                with c4:
                    with st.container(border=True): st.metric(t('m_mov_loc'), f"{filtered_orders['mov_per_loc'].mean():.1f}")

                tot_p_pal = filtered_orders['celkem_pohybu'].sum()
                if tot_p_pal > 0:
                    st.markdown(f"**{t('ratio_moves')}**")
                    c_p1, c_p2 = st.columns(2)
                    c_p1.metric(t('ratio_exact'),
                                f"{filtered_orders['pohyby_exact'].sum() / tot_p_pal * 100:.1f} %")
                    c_p2.metric(t('ratio_miss'),
                                f"{filtered_orders['pohyby_miss'].sum() / tot_p_pal * 100:.1f} %",
                                delta_color="inverse")

                with st.expander(t('exp_detail_title')):
                    display_df = filtered_orders[[
                        'material', 'total_qty', 'celkem_pohybu',
                        'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer', 'certs'
                    ]].copy()
                    display_df.columns = [
                        t('col_mat'), t('col_qty'), t('col_mov'), t('col_mov_exact'),
                        t('col_mov_miss'), t('col_wgt'), t('col_max_dim'), t('col_cert')
                    ]
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.warning(t('no_orders'))
        else:
            st.warning(t('no_orders'))

    # ==========================================
    # TAB 3: CELÉ PALETY A KLT (FU)
    # ==========================================
    with tabs[2]:
        st.markdown(f"<div class='section-header'><h3>{t('fu_title')}</h3><p>{t('fu_desc')}</p></div>", unsafe_allow_html=True)

        df_fu = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])].copy()

        if not df_fu.empty:
            if 'Storage Unit Type' in df_fu.columns:
                def categorize_su(su):
                    su = str(su).strip().upper()
                    if su == 'K1': 
                        return 'KLT'
                    elif su in ['EP1', 'EP2', 'EP3', 'EP4']: 
                        return 'Paleta'
                    elif su in ['', 'NAN', 'NONE']: 
                        return 'Nezadáno'
                    else: 
                        return 'Ostatní'

                df_fu['SU_Category'] = df_fu['Storage Unit Type'].apply(categorize_su)
                df_fu['Storage Unit Type'] = df_fu['Storage Unit Type'].fillna('N/A')

                fu_agg = df_fu.groupby(['SU_Category', 'Storage Unit Type']).agg(
                    pocet_radku=('Material', 'count'),
                    pocet_to=(queue_count_col, 'nunique'),
                    celkem_kusu=('Qty', 'sum')
                ).reset_index()

                fu_agg.columns = [
                    t('fu_col_cat'), t('fu_col_su'), t('fu_col_lines'), 
                    t('fu_col_to'), t('fu_col_qty')
                ]
                fu_agg = fu_agg.sort_values(by=t('fu_col_lines'), ascending=False)

                col_fu1, col_fu2 = st.columns([3, 2])
                with col_fu1:
                    st.dataframe(
                        fu_agg.style.format({t('fu_col_qty'): "{:,.0f}"}), 
                        use_container_width=True, 
                        hide_index=True
                    )
                with col_fu2:
                    chart_data = fu_agg.groupby(t('fu_col_cat'))[t('fu_col_lines')].sum()
                    st.bar_chart(chart_data)
            else:
                st.warning("❌ Sloupec 'Storage Unit Type' nebyl v nahraném Pick reportu nalezen.")
        else:
            st.info("ℹ️ Pro vybrané období a filtry nebyly nalezeny žádné záznamy pro fronty PI_PL_FU a PI_PL_FUOE.")

    # ==========================================
    # TAB 4: TOP MATERIÁLY
    # ==========================================
    with tabs[3]:
        st.markdown(f"<div class='section-header'><h3>{t('sec_queue_top_title')}</h3></div>", unsafe_allow_html=True)
        q_options = [t('all_queues')] + sorted(df_pick['Queue'].dropna().unique().tolist())
        selected_queue_disp = st.selectbox(t('q_select'), options=q_options)

        df_top_filter = (
            df_pick if selected_queue_disp == t('all_queues')
            else df_pick[df_pick['Queue'] == selected_queue_disp]
        )

        if not df_top_filter.empty:
            agg = df_top_filter.groupby('Material').agg(
                pocet_picku=('Material', 'count'),
                celkove_mnozstvi=('Qty', 'sum'),
                celkem_pohybu=('Pohyby_Rukou', 'sum'),
                pohyby_exact=('Pohyby_Exact', 'sum'),
                pohyby_miss=('Pohyby_Loose_Miss', 'sum'),
                celkova_vaha=('Celkova_Vaha_KG', 'sum')
            ).reset_index()

            agg.rename(columns={
                'Material': t('col_mat'),
                'pocet_picku': t('col_lines'),
                'celkove_mnozstvi': t('col_qty'),
                'celkem_pohybu': t('col_mov'),
                'pohyby_exact': t('col_mov_exact'),
                'pohyby_miss': t('col_mov_miss'),
                'celkova_vaha': t('col_wgt'),
            }, inplace=True)

            top_100_df = agg.sort_values(by=t('col_mov'), ascending=False).head(100)[[
                t('col_mat'), t('col_lines'), t('col_qty'), t('col_wgt'),
                t('col_mov_exact'), t('col_mov_miss'), t('col_mov')
            ]]

            fmt_top = {t('col_wgt'): "{:.1f}"}
            for c in top_100_df.columns:
                if c not in [t('col_mat'), t('col_wgt')]:
                    fmt_top[c] = "{:.0f}"

            col_q1, col_q2 = st.columns([1.5, 1])
            with col_q1:
                st.dataframe(top_100_df.style.format(fmt_top),
                             use_container_width=True, hide_index=True)
            with col_q2:
                st.bar_chart(top_100_df.set_index(t('col_mat'))[t('col_mov')])

        st.divider()
        st.subheader(t('exp_missing_data'))
        all_mat_agg = df_pick.groupby('Material').agg(
            lines=('Material', 'count'),
            qty=('Qty', 'sum'),
            miss=('Pohyby_Loose_Miss', 'sum'),
            mov=('Pohyby_Rukou', 'sum')
        ).reset_index()
        all_mat_agg.columns = [t('col_mat'), t('col_lines'), t('col_qty'),
                                t('col_mov_miss'), t('col_mov')]
        miss_df = (
            all_mat_agg[all_mat_agg[t('col_mov_miss')] > 0]
            .sort_values(by=t('col_mov_miss'), ascending=False)
            .head(100)
        )

        if not miss_df.empty:
            st.dataframe(
                miss_df.style.format({c: "{:.0f}" for c in [t('col_mov_miss'), t('col_mov')]}),
                use_container_width=True, hide_index=True
            )
        else:
            st.success(t('all_data_exact'))

    # ==========================================
    # TAB 5: ÚČTOVÁNÍ A BALENÍ (VEKP)
    # ==========================================
    with tabs[4]:
        st.markdown(f"<div class='section-header'><h3>{t('b_title')}</h3><p>{t('b_desc')}</p></div>", unsafe_allow_html=True)
        
        # --- GLOBÁLNÍ AUSWERTUNG MAPOVÁNÍ PRO KATEGORIE (O vs OE a KEP logiky) ---
        aus_category_map = {}
        aus_data = st.session_state.get("auswertung_raw", {})
        if aus_data:
            df_likp_tmp  = aus_data.get("LIKP",  pd.DataFrame())
            df_sdshp_tmp = aus_data.get("SDSHP_AM2", pd.DataFrame())
            df_t031_tmp  = aus_data.get("T031",  pd.DataFrame())
            
            kep_set = set()
            if not df_sdshp_tmp.empty:
                col_s = df_sdshp_tmp.columns[0]
                col_k = next((c for c in df_sdshp_tmp.columns if "KEP" in str(c).upper() or "FÄHIG" in str(c).upper()), None)
                if col_k:
                    kep_set = set(df_sdshp_tmp.loc[df_sdshp_tmp[col_k].astype(str).str.strip() == "X", col_s].astype(str).str.strip())
            
            order_type_map = {}
            if not df_t031_tmp.empty:
                order_type_map = dict(zip(df_t031_tmp.iloc[:, 0].astype(str).str.strip(), df_t031_tmp.iloc[:, 1].astype(str).str.strip()))

            if not df_likp_tmp.empty:
                c_lief = df_likp_tmp.columns[0]
                c_vs   = next((c for c in df_likp_tmp.columns if "Versandstelle" in str(c) or "Shipping" in str(c)), None)
                c_sped = next((c for c in df_likp_tmp.columns if "pediteur" in str(c) or "Transp" in str(c)), None)
                
                tmp_lf = df_likp_tmp[[c_lief]].copy()
                tmp_lf.columns = ["Lieferung"]
                tmp_lf["Lieferung"] = tmp_lf["Lieferung"].astype(str).str.strip()
                
                if c_vs:
                    tmp_lf["Order_Type"] = df_likp_tmp[c_vs].astype(str).str.strip().map(order_type_map).fillna("N")
                else:
                    tmp_lf["Order_Type"] = "N"
                    
                if c_sped:
                    tmp_lf["is_KEP"] = df_likp_tmp[c_sped].astype(str).str.strip().isin(kep_set)
                else:
                    tmp_lf["is_KEP"] = False
                    
                tmp_lf["Kategorie"] = np.where(
                    tmp_lf["is_KEP"],
                    np.where(tmp_lf["Order_Type"] == "O", "OE", "E"),
                    np.where(tmp_lf["Order_Type"] == "O", "O",  "N")
                )
                aus_category_map = tmp_lf.set_index("Lieferung")["Kategorie"].to_dict()

        billing_df = pd.DataFrame()
        pick_per_delivery = pd.DataFrame()

        if df_vekp is not None and not df_vekp.empty:
            vekp_clean = df_vekp.dropna(subset=["Handling Unit", "Generated delivery"]).copy()
            valid_deliveries = df_pick["Delivery"].dropna().unique()
            vekp_filtered = vekp_clean[vekp_clean["Generated delivery"].isin(valid_deliveries)].copy()
            
            vekp_hu_col = next((c for c in vekp_filtered.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), vekp_filtered.columns[0])
            vekp_ext_col = vekp_filtered.columns[1]
            parent_col_vepo = next((c for c in vekp_filtered.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)
            
            vekp_filtered['Clean_HU_Int'] = vekp_filtered[vekp_hu_col].astype(str).str.strip().str.lstrip('0')
            vekp_filtered['Clean_HU_Ext'] = vekp_filtered[vekp_ext_col].astype(str).str.strip().str.lstrip('0')
            
            if parent_col_vepo:
                vekp_filtered['Clean_Parent'] = vekp_filtered[parent_col_vepo].astype(str).str.strip().str.lstrip('0').replace({'nan': '', 'none': ''})
            else:
                vekp_filtered['Clean_Parent'] = ""

            # --- ZPŘESNĚNÍ POMOCÍ VEPO A TREE-CLIMBING ---
            valid_base_hus = set()
            if df_vepo is not None and not df_vepo.empty:
                vepo_hu_col = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
                vepo_lower_col = next((c for c in df_vepo.columns if "Lower-level" in str(c) or "untergeordn" in str(c).lower()), None)
                
                valid_base_hus = set(df_vepo[vepo_hu_col].astype(str).str.strip().str.lstrip('0'))
                if vepo_lower_col:
                    valid_base_hus.update(set(df_vepo[vepo_lower_col].dropna().astype(str).str.strip().str.lstrip('0')))
            else:
                valid_base_hus = set(vekp_filtered['Clean_HU_Int'])

            hu_agg_list = []
            for delivery, group in vekp_filtered.groupby("Generated delivery"):
                ext_to_int = dict(zip(group['Clean_HU_Ext'], group['Clean_HU_Int']))
                p_map = {}
                for _, r in group.iterrows():
                    child = str(r['Clean_HU_Int'])
                    parent = str(r['Clean_Parent'])
                    if parent in ext_to_int:
                        parent = ext_to_int[parent]
                    p_map[child] = parent
                    
                # Listy = jednotky, ve kterých je fyzicky materiál (podle VEPO)
                leaves = [h for h in group['Clean_HU_Int'] if h in valid_base_hus]
                
                roots = set()
                for leaf in leaves:
                    curr = leaf
                    visited = set()
                    while curr in p_map and p_map[curr] != "" and curr not in visited:
                        visited.add(curr)
                        curr = p_map[curr]
                    roots.add(curr)
                    
                hu_agg_list.append({
                    "Generated delivery": delivery,
                    "hu_leaf": len(leaves),
                    "hu_top_level": len(roots)
                })
                
            hu_agg = pd.DataFrame(hu_agg_list)
            if hu_agg.empty:
                hu_agg = pd.DataFrame(columns=["Generated delivery", "hu_leaf", "hu_top_level"])
            # -------------------------------------------------------------

            pick_agg = df_pick.groupby("Delivery").agg(
                pocet_to=(queue_count_col, "nunique"),
                pohyby_celkem=("Pohyby_Rukou", "sum"),
                pohyby_exact=("Pohyby_Exact", "sum"),
                pohyby_miss=("Pohyby_Loose_Miss", "sum"),
                pocet_lokaci=("Source Storage Bin", "nunique"),
                hlavni_fronta=("Queue", "first"),
                pocet_mat=("Material", "nunique")
            ).reset_index()
            pick_per_delivery = pick_agg.copy()

            billing_df = pd.merge(pick_agg, hu_agg,
                                  left_on="Delivery", right_on="Generated delivery", how="left")

            if df_cats is not None:
                billing_df = pd.merge(
                    billing_df, df_cats[["Lieferung", "Category_Full"]],
                    left_on="Delivery", right_on="Lieferung", how="left")
            else:
                billing_df["Category_Full"] = pd.NA

            def odvod_kategorii(row):
                cat_full = row.get('Category_Full')
                if pd.notna(cat_full) and str(cat_full).strip() not in ["", "nan", t("uncategorized")]:
                    return cat_full
                
                kat = aus_category_map.get(row["Delivery"])
                
                if not kat:
                    q = str(row.get('hlavni_fronta', '')).upper()
                    if 'PI_PA_OE' in q:
                        kat = "OE"
                    elif 'PI_PA' in q:
                        kat = "E"
                    elif 'PI_PL_FUOE' in q or 'PI_PL_OE' in q:
                        kat = "O"
                    elif 'PI_PL' in q:
                        kat = "N"
                        
                art = "Sortenrein" if row.get('pocet_mat', 1) <= 1 else "Misch"
                
                if kat:
                    return f"{kat} {art}"
                return t("uncategorized")

            billing_df["Category_Full"] = billing_df.apply(odvod_kategorii, axis=1)

            def urci_konecnou_hu(row):
                kat = str(row.get('Category_Full', '')).upper()
                if kat.startswith('E') or kat.startswith('OE'):
                    return row.get('hu_leaf', 0)
                else:
                    return row.get('hu_top_level', 0)

            billing_df["pocet_hu"] = billing_df.apply(urci_konecnou_hu, axis=1).fillna(0).astype(int)
            billing_df["pohybu_na_hu"] = np.where(
                billing_df["pocet_hu"] > 0,
                billing_df["pohyby_celkem"] / billing_df["pocet_hu"], 0)
            billing_df["TO_navic"] = (
                billing_df["pocet_to"] - billing_df["pocet_hu"]).clip(lower=0).astype(int)
            billing_df["avg_mov_per_loc"] = np.where(
                billing_df["pocet_lokaci"] > 0,
                billing_df["pohyby_celkem"] / billing_df["pocet_lokaci"], 0)

            st.session_state['billing_df'] = billing_df

        # ═══════════════════════════════════════════════════════════════
        # SEKCE A: PICK ↔ HU KORELACE
        # ═══════════════════════════════════════════════════════════════
        if not billing_df.empty:
            total_deliveries = len(df_pick["Delivery"].dropna().unique())
            total_pick_moves = int(df_pick["Pohyby_Rukou"].sum())
            total_tos = df_pick[queue_count_col].nunique()
            
            total_hus = billing_df["pocet_hu"].sum()
            moves_per_hu = total_pick_moves / total_hus if total_hus > 0 else 0

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            with c1:
                with st.container(border=True): st.metric(t("b_del_count"), f"{total_deliveries:,}".replace(",", " "))
            with c2:
                with st.container(border=True): st.metric(t("b_to_count"), f"{total_tos:,}".replace(",", " "))
            with c3:
                with st.container(border=True): st.metric(t("b_hu_count"), f"{int(total_hus):,}".replace(",", " "))
            with c4:
                with st.container(border=True): st.metric(t("b_mov_per_hu"), f"{moves_per_hu:.1f}")
            
            nerov_count = int((billing_df["TO_navic"] > 0).sum())
            nepokr_to_sum = int(billing_df["TO_navic"].sum())
            with c5:
                with st.container(border=True): st.metric(t("b_imbalance_orders"), f"{nerov_count:,}".replace(",", " "), f"{nerov_count / len(billing_df) * 100:.1f} % {t('b_of_all')}", delta_color="inverse")
            with c6:
                with st.container(border=True): st.metric(t("b_unpaid_to"), f"{nepokr_to_sum:,}".replace(",", " "), t("b_unpaid_to_help"), delta_color="inverse")

            st.divider()
            st.subheader(t("b_cat_title"))
            cat_summary = billing_df.groupby("Category_Full").agg(
                pocet_zakazek=("Delivery", "nunique"),
                pocet_to_sum=("pocet_to", "sum"),
                pocet_hu=("pocet_hu", "sum"),
                pocet_lokaci=("pocet_lokaci", "sum"),
                pohyby_celkem=("pohyby_celkem", "sum"),
                pohyby_exact=("pohyby_exact", "sum"),
                pohyby_miss=("pohyby_miss", "sum"),
                TO_navic=("TO_navic", "sum"),
            ).reset_index()
            cat_summary["avg_loc_per_hu"] = np.where(
                cat_summary["pocet_hu"] > 0, cat_summary["pocet_lokaci"] / cat_summary["pocet_hu"], 0)
            cat_summary["avg_mov_per_loc"] = np.where(
                cat_summary["pocet_lokaci"] > 0, cat_summary["pohyby_celkem"] / cat_summary["pocet_lokaci"], 0)
            cat_summary["pct_exact"] = np.where(
                cat_summary["pohyby_celkem"] > 0, cat_summary["pohyby_exact"] / cat_summary["pohyby_celkem"] * 100, 0)
            cat_summary["pct_miss"] = np.where(
                cat_summary["pohyby_celkem"] > 0, cat_summary["pohyby_miss"] / cat_summary["pohyby_celkem"] * 100, 0)
            cat_summary = cat_summary.sort_values("avg_mov_per_loc", ascending=False)
            
            cat_disp = cat_summary[[
                "Category_Full", "pocet_zakazek", "pocet_to_sum", "pocet_hu", "avg_loc_per_hu",
                "avg_mov_per_loc", "TO_navic", "pct_exact", "pct_miss"]].copy()
            cat_disp.columns = [
                t("b_col_type"), t("b_col_orders"), t("b_col_tos"), t("b_col_hu"), t("b_col_loc_hu"),
                t("b_col_mov_loc"), t("b_col_unpaid_to"), t("b_col_pct_ex"), t("b_col_pct_ms")]
            
            fmt_cat = {c: "{:.1f} %" for c in cat_disp.columns if "%" in c}
            fmt_cat.update({c: "{:.1f}" for c in [t("b_col_loc_hu"), t("b_col_mov_loc")]})
            fmt_cat.update({c: "{:,.0f}" for c in [t("b_col_orders"), t("b_col_tos"), t("b_col_hu"), t("b_col_unpaid_to")]})
            
            cb1, cb2 = st.columns([2.5, 1])
            with cb1:
                st.dataframe(cat_disp.style.format(fmt_cat).set_properties(
                    subset=[t("b_col_type"), t("b_col_mov_loc")], **{"font-weight": "bold"}),
                    use_container_width=True, hide_index=True)
            with cb2:
                chart_data = cat_summary[cat_summary["Category_Full"] != t("uncategorized")].set_index("Category_Full")["avg_mov_per_loc"]
                st.bar_chart(chart_data)

            st.divider()
            st.markdown(f"### {t('b_imbalance_title')}")
            st.info(t('b_imbalance_desc'))
            imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values("TO_navic", ascending=False).head(50)
            if not imb_df.empty:
                imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
                imb_disp.columns = ["Delivery", "Kategorie", "Pick TO celkem", "Pohyby rukou", "Účtované HU", t('b_col_unpaid_to')]
                st.dataframe(imb_disp.style.background_gradient(subset=[t('b_col_unpaid_to')], cmap='Reds'), use_container_width=True, hide_index=True)
            else:
                st.success(t("b_no_imbalance"))
        else:
            st.warning(t("b_missing_vekp"))

        # ═══════════════════════════════════════════════════════════════════
        # SEKCE B: AUSWERTUNG — logiky ze zákazníkova souboru (PONECHÁNO ZCELA PŮVODNÍ)
        # ═══════════════════════════════════════════════════════════════════
        st.divider()
        st.subheader("📊 " + t("b_aus_title"))
        st.markdown(t("b_aus_desc"))

        if not aus_data:
            st.info(t("b_aus_upload_hint"))
        else:
            try:
                df_likp  = aus_data.get("LIKP",  pd.DataFrame())
                df_vekp2 = aus_data.get("VEKP",  pd.DataFrame())
                df_vepo  = aus_data.get("VEPO",  pd.DataFrame())
                df_lips2 = aus_data.get("LIPS",  pd.DataFrame())
                df_sdshp = aus_data.get("SDSHP_AM2", pd.DataFrame())
                df_t031  = aus_data.get("T031",  pd.DataFrame())
                df_t023  = aus_data.get("T023",  pd.DataFrame())

                missing_sheets = [n for n, d in [("LIKP", df_likp), ("VEKP", df_vekp2),
                                                  ("VEPO", df_vepo), ("SDSHP_AM2", df_sdshp),
                                                  ("T031", df_t031)] if d.empty]
                if missing_sheets:
                    st.warning(f"Chybějící listy v Auswertung souboru: {', '.join(missing_sheets)}")

                kep_set = set()
                sdshp_display = pd.DataFrame()
                if not df_sdshp.empty:
                    col_s  = df_sdshp.columns[0]
                    col_k  = next((c for c in df_sdshp.columns if "KEP" in str(c)
                                   and ("f" in str(c).lower() or "hig" in str(c).lower())), None)
                    col_mw = next((c for c in df_sdshp.columns if "Brutto" in str(c)
                                   or "gewicht" in str(c).lower()), None)
                    col_zt = next((c for c in df_sdshp.columns if "Uhrzeit" in str(c)
                                   or ("Zeit" in str(c) and "Lade" in str(c))), None)
                    col_bz = next((c for c in df_sdshp.columns if "Bereit" in str(c)
                                   or "Zone" in str(c).lower()), None)
                    if col_k:
                        kep_set = set(df_sdshp.loc[
                            df_sdshp[col_k].astype(str).str.strip() == "X", col_s
                        ].astype(str).str.strip())
                    show_cols = [c for c in [col_s, col_k, col_mw, col_zt, col_bz] if c]
                    sdshp_display = df_sdshp[show_cols].copy() if show_cols else pd.DataFrame()

                order_type_map = {}
                if not df_t031.empty:
                    order_type_map = dict(zip(
                        df_t031.iloc[:, 0].astype(str).str.strip(),
                        df_t031.iloc[:, 1].astype(str).str.strip()))

                df_lf = pd.DataFrame()
                if not df_likp.empty:
                    c_lief = df_likp.columns[0]
                    c_vs   = next((c for c in df_likp.columns if "Versandstelle" in str(c)), None)
                    c_sped = next((c for c in df_likp.columns if "pediteur" in str(c)), None)
                    c_la   = next((c for c in df_likp.columns if "Lieferart" in str(c)), None)
                    c_ps   = next((c for c in df_likp.columns if "Packst" in str(c)), None)
                    c_gw   = next((c for c in df_likp.columns if "Gesamtgewicht" in str(c)
                                   and "netto" not in str(c).lower()), None)

                    keep = {c_lief: "Lieferung"}
                    for alias, col in [("Versandstelle", c_vs), ("Spediteur", c_sped),
                                       ("Lieferart", c_la), ("Packstucke", c_ps), ("Gew_kg", c_gw)]:
                        if col:
                            keep[col] = alias

                    df_lf = df_likp[list(keep.keys())].copy().rename(columns=keep)
                    df_lf["Lieferung"] = df_lf["Lieferung"].astype(str).str.strip()
                    df_lf = df_lf.drop_duplicates("Lieferung")

                    if "Versandstelle" in df_lf.columns:
                        df_lf["Order_Type"] = (df_lf["Versandstelle"].astype(str).str.strip()
                                               .map(order_type_map).fillna("N"))
                    else:
                        df_lf["Order_Type"] = "N"

                    if "Spediteur" in df_lf.columns:
                        df_lf["is_KEP"] = df_lf["Spediteur"].astype(str).str.strip().isin(kep_set)
                    else:
                        df_lf["is_KEP"] = False

                    df_lf["Kategorie"] = np.where(
                        df_lf["is_KEP"],
                        np.where(df_lf["Order_Type"] == "O", "OE", "E"),
                        np.where(df_lf["Order_Type"] == "O", "O",  "N"))

                    for nc in ["Packstucke", "Gew_kg"]:
                        if nc in df_lf.columns:
                            df_lf[nc] = pd.to_numeric(df_lf[nc], errors="coerce").fillna(0)

                vollpalette_lager = set()
                if not df_t023.empty:
                    vollpalette_lager.update(df_t023.iloc[:, 0].astype(str).str.strip())
                vollpalette_lager.update(st.session_state.get('auto_voll_hus', set()))

                hu_mat_agg = pd.DataFrame()
                if not df_vepo.empty:
                    c_hu_v  = df_vepo.columns[0]
                    c_del_v = next((c for c in df_vepo.columns if "Lieferung" in str(c)), None)
                    c_mat_v = next((c for c in df_vepo.columns if "Material" in str(c)), None)
                    if c_del_v and c_mat_v:
                        hu_mat_agg = df_vepo.groupby(c_hu_v).agg(
                            pocet_mat=(c_mat_v, "nunique"),
                            pocet_lief=(c_del_v, "nunique"),
                        ).reset_index()
                        hu_mat_agg.columns = ["HU_intern", "pocet_mat", "pocet_lief"]
                        hu_mat_agg["HU_intern"] = hu_mat_agg["HU_intern"].astype(str).str.strip()

                df_vk = pd.DataFrame()
                if not df_vekp2.empty:
                    c_hu_int = df_vekp2.columns[0]
                    c_hu_ext = df_vekp2.columns[1]
                    c_gen_d  = next((c for c in df_vekp2.columns if "generierte Lieferung" in str(c)
                                     or "Generated delivery" in str(c)), None)
                    c_pm     = next((c for c in df_vekp2.columns if str(c).strip() == "Packmittel"), None)
                    c_pma    = next((c for c in df_vekp2.columns if "Packmittelart" in str(c)
                                     or ("Packing Material Type" in str(c) and "Desc" not in str(c)
                                         and "\n" not in str(c))), None)
                    c_gew  = next((c for c in df_vekp2.columns if str(c).strip() == "Gesamtgewicht"), None)
                    c_lgew = next((c for c in df_vekp2.columns if str(c).strip() == "Ladungsgewicht"), None)
                    c_egew = next((c for c in df_vekp2.columns if str(c).strip() == "Eigengewicht"), None)
                    c_len  = next((c for c in df_vekp2.columns if str(c).strip() in ("Länge", "Length")), None)
                    c_wid  = next((c for c in df_vekp2.columns if str(c).strip() in ("Breite", "Width")), None)
                    c_hei  = next((c for c in df_vekp2.columns if str(c).strip() in ("Höhe", "Height")), None)
                    c_art  = next((c for c in df_vekp2.columns if str(c).strip() == "Art"), None)
                    c_kat  = next((c for c in df_vekp2.columns if str(c).strip() == "Kategorie"), None)
                    c_parent = next((c for c in df_vekp2.columns if "higher-level" in str(c).lower() or "übergeordn" in str(c).lower() or "superordinate" in str(c).lower()), None)

                    col_map = {c_hu_int: "HU_intern", c_hu_ext: "Handling_Unit_Ext"}
                    if c_parent:
                        col_map[c_parent] = "Parent_HU"
                    
                    for alias, col in [("Lieferung", c_gen_d), ("Packmittel", c_pm),
                                       ("Packmittelart", c_pma), ("Gesamtgewicht", c_gew),
                                       ("Ladungsgewicht", c_lgew), ("Eigengewicht", c_egew),
                                       ("Laenge", c_len), ("Breite", c_wid), ("Hoehe", c_hei),
                                       ("Art_vekp", c_art), ("Kat_vekp", c_kat)]:
                        if col:
                            col_map[col] = alias

                    df_vk = df_vekp2[list(col_map.keys())].copy().rename(columns=col_map)
                    df_vk["HU_intern"] = df_vk["HU_intern"].astype(str).str.strip()
                    df_vk["Handling_Unit_Ext"] = df_vk["Handling_Unit_Ext"].astype(str).str.strip()
                    df_vk['Clean_HU_Int'] = df_vk['HU_intern'].astype(str).str.strip().str.lstrip('0')
                    df_vk['Clean_HU_Ext'] = df_vk['Handling_Unit_Ext'].astype(str).str.strip().str.lstrip('0')
                    
                    if "Lieferung" in df_vk.columns:
                        df_vk["Lieferung"] = df_vk["Lieferung"].astype(str).str.strip()

                    for nc in ["Gesamtgewicht", "Ladungsgewicht", "Eigengewicht",
                               "Laenge", "Breite", "Hoehe", "Packmittelart"]:
                        if nc in df_vk.columns:
                            df_vk[nc] = pd.to_numeric(df_vk[nc], errors="coerce").fillna(0)

                    if "Eigengewicht" in df_vk.columns and "Ladungsgewicht" in df_vk.columns:
                        mask_zero = df_vk.get("Gesamtgewicht", pd.Series(dtype=float)) == 0
                        if "Gesamtgewicht" in df_vk.columns:
                            df_vk.loc[mask_zero, "Gesamtgewicht"] = (
                                df_vk.loc[mask_zero, "Eigengewicht"] +
                                df_vk.loc[mask_zero, "Ladungsgewicht"])
                                
                    if not df_lf.empty and "Lieferung" in df_lf.columns:
                        cat_map_vk = df_lf.set_index("Lieferung")["Kategorie"].to_dict()
                        df_vk["Kategorie"] = df_vk["Lieferung"].map(cat_map_vk).fillna("N")
                    else:
                        df_vk["Kategorie"] = "N"

                    vepo_nested_hus_aus = set()
                    vepo_parent_hus_aus = set()
                    if df_vepo is not None and not df_vepo.empty:
                        vepo_hu_col_aus = next((c for c in df_vepo.columns if "Internal HU" in str(c) or "HU-Nummer intern" in str(c)), df_vepo.columns[0])
                        vepo_lower_col_aus = next((c for c in df_vepo.columns if "Lower-level" in str(c) or "untergeordn" in str(c).lower()), None)
                        
                        if vepo_lower_col_aus:
                            vepo_nested_hus_aus = set(df_vepo[vepo_lower_col_aus].dropna().astype(str).str.strip().str.lstrip('0'))
                            vepo_nested_hus_aus = {h for h in vepo_nested_hus_aus if h not in ["", "nan", "none"]}
                            vepo_parent_hus_aus = set(df_vepo.loc[
                                df_vepo[vepo_lower_col_aus].notna() & (df_vepo[vepo_lower_col_aus].astype(str).str.strip() != ""),
                                vepo_hu_col_aus
                            ].astype(str).str.strip().str.lstrip('0'))

                        valid_hus_aus = set(df_vepo[vepo_hu_col_aus].astype(str).str.strip().str.lstrip('0'))
                        valid_hus_aus.update(vepo_nested_hus_aus)
                        df_vk = df_vk[df_vk['Clean_HU_Int'].isin(valid_hus_aus)].copy()

                    if vepo_nested_hus_aus or vepo_parent_hus_aus:
                        df_vk['is_top_level'] = ~df_vk['Clean_HU_Int'].isin(vepo_nested_hus_aus)
                        df_vk['is_leaf'] = ~df_vk['Clean_HU_Int'].isin(vepo_parent_hus_aus)
                    elif "Parent_HU" in df_vk.columns:
                        df_vk['Clean_Parent'] = df_vk["Parent_HU"].astype(str).str.strip().str.lstrip('0')
                        df_vk['Clean_Parent'] = df_vk['Clean_Parent'].replace({'nan': '', 'none': ''})
                        
                        id_to_int_vk = {}
                        for _, r in df_vk.iterrows():
                            internal = str(r['Clean_HU_Int'])
                            id_to_int_vk[internal] = internal
                            external = str(r['Clean_HU_Ext'])
                            if external and external != 'nan':
                                id_to_int_vk[external] = internal
                                
                        df_vk['Normalized_Parent_Int'] = df_vk['Clean_Parent'].apply(lambda p: id_to_int_vk.get(p, p))

                        parent_hus_vk = set(df_vk['Normalized_Parent_Int'].dropna())
                        parent_hus_vk = {p for p in parent_hus_vk if p != ""}
                        
                        df_vk["is_top_level"] = df_vk['Normalized_Parent_Int'] == ""
                        df_vk["is_leaf"] = ~df_vk['Clean_HU_Int'].isin(parent_hus_vk)
                    else:
                        df_vk["is_top_level"] = True
                        df_vk["is_leaf"] = True
                        
                    def is_billable_vk(row):
                        kat = str(row.get("Kategorie", "")).upper()
                        if kat.startswith("E") or kat.startswith("OE"):
                            return row.get("is_leaf", True)
                        else:
                            return row.get("is_top_level", True)

                    df_vk["is_billable_hu"] = df_vk.apply(is_billable_vk, axis=1)
                    df_vk = df_vk[df_vk["is_billable_hu"]].copy()

                    if "Art_vekp" not in df_vk.columns:
                        if not hu_mat_agg.empty:
                            df_vk = df_vk.merge(hu_mat_agg, on="HU_intern", how="left")
                        else:
                            df_vk["pocet_mat"] = 1
                            df_vk["pocet_lief"] = 1

                        def _calc_art(row):
                            if str(row.get("Handling_Unit_Ext", "")).strip() in vollpalette_lager:
                                return "Vollpalette"
                                
                            mat = row.get("pocet_mat", 1)
                            lief = row.get("pocet_lief", 1)
                            mat  = 1 if pd.isna(mat)  else int(mat)
                            lief = 1 if pd.isna(lief) else int(lief)
                            
                            return "Misch" if (mat > 1 or lief > 1) else "Sortenrein"

                        df_vk["Art_HU"] = df_vk.apply(_calc_art, axis=1)
                    else:
                        df_vk["Art_HU"] = df_vk["Art_vekp"]

                lips_vaha = pd.DataFrame()
                if not df_lips2.empty:
                    c_ll = df_lips2.columns[0]
                    c_bg = next((c for c in df_lips2.columns if "Bruttogewicht" in str(c)), None)
                    if c_bg:
                        lv = df_lips2[[c_ll, c_bg]].copy()
                        lv.columns = ["Lieferung", "Brutto_g"]
                        lv["Brutto_g"] = pd.to_numeric(lv["Brutto_g"], errors="coerce").fillna(0)
                        lv["Lieferung"] = lv["Lieferung"].astype(str).str.strip()
                        lips_vaha = lv.groupby("Lieferung")["Brutto_g"].sum().reset_index()
                        lips_vaha["Brutto_kg"] = lips_vaha["Brutto_g"] / 1000.0

                aus_lief = pd.DataFrame()
                art_cols_avail = []
                gew_col = None

                if not df_vk.empty and "Lieferung" in df_vk.columns:
                    agg_dict = {"anzahl_hu": ("HU_intern", "nunique")}
                    if "Gesamtgewicht" in df_vk.columns:
                        agg_dict["celk_gew"] = ("Gesamtgewicht", "sum")
                        agg_dict["avg_gew"]  = ("Gesamtgewicht", "mean")
                    if "Ladungsgewicht" in df_vk.columns:
                        agg_dict["avg_ladung"] = ("Ladungsgewicht", "mean")
                    if "Packmittel" in df_vk.columns:
                        agg_dict["pm_typy"] = ("Packmittel", lambda x: ", ".join(
                            sorted(x.dropna().astype(str).str.strip().unique())))

                    aus_lief = df_vk.groupby("Lieferung").agg(**agg_dict).reset_index()

                    if "Art_HU" in df_vk.columns:
                        art_piv = (df_vk.groupby(["Lieferung", "Art_HU"])["HU_intern"]
                                   .nunique().unstack(fill_value=0).reset_index())
                        aus_lief = aus_lief.merge(art_piv, on="Lieferung", how="left")

                    art_cols_avail = [c for c in ["Sortenrein", "Misch", "Vollpalette"]
                                      if c in aus_lief.columns]

                    if not df_lf.empty:
                        m_cols = ["Lieferung", "Kategorie", "Order_Type", "is_KEP"]
                        for opt in ["Spediteur", "Packstucke", "Gew_kg"]:
                            if opt in df_lf.columns:
                                m_cols.append(opt)
                        aus_lief = aus_lief.merge(df_lf[m_cols], on="Lieferung", how="left")
                    aus_lief["Kategorie"] = aus_lief["Kategorie"].fillna("N") if "Kategorie" in aus_lief.columns else "N"

                    if not lips_vaha.empty:
                        aus_lief = aus_lief.merge(lips_vaha[["Lieferung", "Brutto_kg"]],
                                                  on="Lieferung", how="left")

                    gew_col = ("Brutto_kg" if "Brutto_kg" in aus_lief.columns
                               else ("celk_gew" if "celk_gew" in aus_lief.columns else None))

                    if not pick_per_delivery.empty:
                        aus_lief = aus_lief.merge(
                            pick_per_delivery[["Delivery", "pohyby_celkem", "pohyby_exact",
                                               "pohyby_miss", "pocet_lokaci", "pocet_to"]],
                            left_on="Lieferung", right_on="Delivery", how="left")
                        aus_lief["avg_mov_per_loc"] = np.where(
                            aus_lief["pocet_lokaci"].fillna(0) > 0,
                            aus_lief["pohyby_celkem"].fillna(0) / aus_lief["pocet_lokaci"], np.nan)
                        aus_lief.drop(columns=["Delivery"], errors="ignore", inplace=True)

                kat_desc_map = {"E": "Paket (KEP)", "N": "Paleta",
                                "O": "OE Paleta", "OE": "OE Paket"}

                if not aus_lief.empty:
                    tot_l = aus_lief["Lieferung"].nunique()
                    tot_h = int(aus_lief["anzahl_hu"].sum()) if "anzahl_hu" in aus_lief.columns else 0
                    avg_h = tot_h / tot_l if tot_l > 0 else 0
                    pct_kep = (aus_lief["Kategorie"].isin(["E", "OE"]).mean() * 100
                               if "Kategorie" in aus_lief.columns else 0)
                    tot_gew = aus_lief[gew_col].sum() if gew_col else 0

                    has_pick = "pohyby_celkem" in aus_lief.columns and aus_lief["pohyby_celkem"].notna().any()
                    n_cols = 6 if has_pick else 5
                    metrics_cols = st.columns(n_cols)
                    with metrics_cols[0]:
                        with st.container(border=True): st.metric(t("b_aus_total_lief"), f"{tot_l:,}".replace(",", " "))
                    with metrics_cols[1]:
                        with st.container(border=True): st.metric(t("b_aus_total_hu"), f"{tot_h:,}".replace(",", " "))
                    with metrics_cols[2]:
                        with st.container(border=True): st.metric(t("b_aus_avg_hu_lief"), f"{avg_h:.2f}")
                    with metrics_cols[3]:
                        with st.container(border=True): st.metric(t("b_aus_total_vaha"), f"{tot_gew:,.0f} kg".replace(",", " "))
                    with metrics_cols[4]:
                        with st.container(border=True): st.metric(t("b_aus_pct_kep"), f"{pct_kep:.1f} %")
                    if has_pick:
                        avg_mpl_all = (aus_lief["pohyby_celkem"].sum() /
                                       aus_lief["pocet_lokaci"].sum()
                                       if aus_lief["pocet_lokaci"].sum() > 0 else 0)
                        with metrics_cols[5]:
                            with st.container(border=True): st.metric("Prům. pohybů / lokaci", f"{avg_mpl_all:.2f}")

                st.divider()
                st.markdown(f"<div class='section-header'><h3>{t('b_aus_kat_title')}</h3><p>{t('b_aus_kat_desc')}</p></div>", unsafe_allow_html=True)

                if not aus_lief.empty and "Kategorie" in aus_lief.columns:
                    has_pick_data = "pohyby_celkem" in aus_lief.columns

                    agg_k = {"pocet_lief": ("Lieferung", "nunique"),
                             "celk_hu": ("anzahl_hu", "sum")}
                    if gew_col:
                        agg_k["celk_gew"] = (gew_col, "sum")
                    if "avg_gew" in aus_lief.columns:
                        agg_k["prumer_gew"] = ("avg_gew", "mean")
                    for ac in art_cols_avail:
                        agg_k[f"hu_{ac}"] = (ac, "sum")
                    if has_pick_data:
                        agg_k["sum_pohyby"]  = ("pohyby_celkem",  "sum")
                        agg_k["sum_lokaci"]  = ("pocet_lokaci",   "sum")
                        agg_k["sum_to"]      = ("pocet_to",       "sum")

                    kat_grp = aus_lief.groupby("Kategorie").agg(**agg_k).reset_index()
                    kat_grp["prumer_hu"] = kat_grp["celk_hu"] / kat_grp["pocet_lief"]
                    kat_grp["Popis"] = kat_grp["Kategorie"].map(kat_desc_map).fillna(kat_grp["Kategorie"])

                    if has_pick_data:
                        kat_grp["avg_mov_per_loc"] = np.where(
                            kat_grp["sum_lokaci"] > 0,
                            kat_grp["sum_pohyby"] / kat_grp["sum_lokaci"], 0)

                    disp_cols  = ["Kategorie", "Popis", "pocet_lief", "celk_hu", "prumer_hu"]
                    disp_names = [t("b_aus_kat"), t("b_aus_popis"), t("b_aus_lief"),
                                  t("b_aus_hu"), t("b_aus_packst")]
                    if "celk_gew" in kat_grp.columns:
                        disp_cols.append("celk_gew"); disp_names.append(t("b_aus_vaha_total"))
                    if "prumer_gew" in kat_grp.columns:
                        disp_cols.append("prumer_gew"); disp_names.append(t("b_aus_avg_vaha"))
                    if has_pick_data:
                        disp_cols.append("sum_to")
                        disp_names.append("Pick TO celkem")
                        disp_cols.append("avg_mov_per_loc")
                        disp_names.append("Prům. pohybů / lokaci")
                    for ac in art_cols_avail:
                        disp_cols.append(f"hu_{ac}"); disp_names.append(f"HU {ac}")

                    disp_kat = kat_grp[disp_cols].copy()
                    disp_kat.columns = disp_names

                    fmt_kat = {t("b_aus_packst"): "{:.2f}"}
                    if t("b_aus_vaha_total") in disp_kat.columns:
                        fmt_kat[t("b_aus_vaha_total")] = "{:,.0f}"
                    if t("b_aus_avg_vaha") in disp_kat.columns:
                        fmt_kat[t("b_aus_avg_vaha")] = "{:.1f}"
                    if "Prům. pohybů / lokaci" in disp_kat.columns:
                        fmt_kat["Prům. pohybů / lokaci"] = "{:.2f}"
                    if "Pick TO celkem" in disp_kat.columns:
                        fmt_kat["Pick TO celkem"] = "{:,.0f}"

                    ck1, ck2 = st.columns([2.5, 1])
                    with ck1:
                        st.dataframe(disp_kat.style.format(fmt_kat)
                                     .set_properties(subset=["Prům. pohybů / lokaci"]
                                                     if "Prům. pohybů / lokaci" in disp_kat.columns
                                                     else [],
                                                     **{"font-weight": "bold", "color": "#d62728"}),
                                     use_container_width=True, hide_index=True)
                    with ck2:
                        if has_pick_data and "avg_mov_per_loc" in kat_grp.columns:
                            st.bar_chart(kat_grp.set_index("Kategorie")["avg_mov_per_loc"])
                        else:
                            st.bar_chart(kat_grp.set_index("Kategorie")["celk_hu"])
                else:
                    st.info("Nejsou dostupná data kategorií (chybí LIKP nebo VEKP).")

                st.divider()
                st.markdown(f"<div class='section-header'><h3>{t('b_aus_art_title')}</h3><p>{t('b_aus_art_desc')}</p></div>", unsafe_allow_html=True)

                if not df_vk.empty and "Art_HU" in df_vk.columns:
                    art_celk = df_vk["Art_HU"].value_counts()
                    art_sum = art_celk.sum()
                    ca1, ca2, ca3 = st.columns(3)
                    for col_m, label, icon in [(ca1, "Sortenrein", "📦"),
                                               (ca2, "Misch", "🔀"),
                                               (ca3, "Vollpalette", "🏭")]:
                        cnt = int(art_celk.get(label, 0))
                        pct = cnt / art_sum * 100 if art_sum > 0 else 0
                        with col_m:
                            with st.container(border=True):
                                st.metric(f"{icon} {label}", f"{cnt:,}".replace(",", " "), f"{pct:.1f} %")

                    if not aus_lief.empty and art_cols_avail:
                        st.markdown("**Distribuce typů HU podle kategorie:**")
                        art_cross = aus_lief.groupby("Kategorie")[art_cols_avail].sum().reset_index()
                        art_cross["Popis"] = art_cross["Kategorie"].map(kat_desc_map).fillna(art_cross["Kategorie"])
                        st.dataframe(art_cross[["Kategorie", "Popis"] + art_cols_avail],
                                     use_container_width=True, hide_index=True)

                st.divider()
                st.markdown("**📊 Počet HU na zásilku (Anzahl Packstücke):**")
                if not aus_lief.empty and "anzahl_hu" in aus_lief.columns:
                    ps_dist = aus_lief["anzahl_hu"].value_counts().sort_index().reset_index()
                    ps_dist.columns = ["Počet HU", "Počet zásilek"]
                    ps_dist["% zásilek"] = (ps_dist["Počet zásilek"] / ps_dist["Počet zásilek"].sum() * 100).round(1)
                    ps1, ps2 = st.columns([1, 2])
                    with ps1:
                        st.dataframe(ps_dist.style.format({"% zásilek": "{:.1f} %"}),
                                     use_container_width=True, hide_index=True)
                    with ps2:
                        st.bar_chart(ps_dist.set_index("Počet HU")["Počet zásilek"])

                if not df_vk.empty and any(c in df_vk.columns for c in ["Gesamtgewicht", "Ladungsgewicht"]):
                    st.divider()
                    st.markdown(f"<div class='section-header'><h3>⚖️ Váhy HU (Gesamtgewicht = Eigengewicht + Ladungsgewicht)</h3></div>", unsafe_allow_html=True)
                    st.caption("Ověřeno 99.8% shodou na zákazníkových datech.")

                    if "Packmittel" in df_vk.columns:
                        df_vk_pick = df_vk.copy()
                        if not pick_per_delivery.empty and "Lieferung" in df_vk_pick.columns:
                            df_vk_pick = df_vk_pick.merge(
                                pick_per_delivery[["Delivery", "pohyby_celkem", "pocet_lokaci", "pocet_to"]],
                                left_on="Lieferung", right_on="Delivery", how="left")

                        has_pick_in_vk = "pohyby_celkem" in df_vk_pick.columns

                        wt_agg_dict = {
                            "pocet_hu":    ("HU_intern", "nunique"),
                            "avg_total":   ("Gesamtgewicht", "mean"),
                        }
                        if "Eigengewicht" in df_vk_pick.columns:
                            wt_agg_dict["avg_eigen"] = ("Eigengewicht", "first")
                        if "Ladungsgewicht" in df_vk_pick.columns:
                            wt_agg_dict["avg_ladung"] = ("Ladungsgewicht", "mean")
                        if has_pick_in_vk:
                            wt_agg_dict["sum_pohyby"] = ("pohyby_celkem", "sum")
                            wt_agg_dict["sum_lokaci"]  = ("pocet_lokaci",  "sum")
                            wt_agg_dict["sum_to"]      = ("pocet_to",      "sum")

                        wt_grp = (df_vk_pick[df_vk_pick["Packmittel"].notna() &
                                             (df_vk_pick["Gesamtgewicht"] > 0)]
                                  .groupby("Packmittel").agg(**wt_agg_dict)
                                  .reset_index().sort_values("pocet_hu", ascending=False))

                        if has_pick_in_vk:
                            wt_grp["avg_mov_per_loc"] = np.where(
                                wt_grp["sum_lokaci"] > 0,
                                wt_grp["sum_pohyby"] / wt_grp["sum_lokaci"], 0)

                        rename_wt = {
                            "Packmittel": t("b_aus_carton"),
                            "pocet_hu":   t("b_aus_pocet"),
                            "avg_total":  "Prům. Gesamtgew. (kg)",
                            "avg_eigen":  "Eigengewicht (kg)",
                            "avg_ladung": "Prům. Ladungsgew. (kg)",
                            "sum_pohyby": "Pohyby celkem",
                            "sum_lokaci": "Lokací celkem",
                            "sum_to":     "TO celkem",
                            "avg_mov_per_loc": "Prům. pohybů / lok.",
                        }
                        wt_disp = wt_grp.rename(columns={k: v for k, v in rename_wt.items()
                                                          if k in wt_grp.columns})
                        fmt_wt = {v: "{:.2f}" for v in ["Prům. Gesamtgew. (kg)", "Eigengewicht (kg)",
                                                         "Prům. Ladungsgew. (kg)", "Prům. pohybů / lok."]}
                        fmt_wt.update({v: "{:,.0f}" for v in ["Pohyby celkem", "Lokací celkem", "TO celkem"]})
                        fmt_wt = {k: v for k, v in fmt_wt.items() if k in wt_disp.columns}

                        st.dataframe(
                            wt_disp.style.format(fmt_wt)
                            .set_properties(subset=["Prům. pohybů / lok."]
                                            if "Prům. pohybů / lok." in wt_disp.columns else [],
                                            **{"font-weight": "bold", "background-color": "#fff8e1"}),
                            use_container_width=True, hide_index=True)

                    if not lips_vaha.empty:
                        tot_lips = lips_vaha["Brutto_kg"].sum()
                        tot_vekp_gew = df_vk["Gesamtgewicht"].sum() if "Gesamtgewicht" in df_vk.columns else 0
                        st.caption(
                            f"Celková váha dle LIPS (gramy → kg): **{tot_lips:,.0f} kg** | "
                            f"dle VEKP Gesamtgewicht: **{tot_vekp_gew:,.0f} kg** | "
                            f"Rozdíl: **{abs(tot_lips - tot_vekp_gew):,.0f} kg**")

                if not df_vk.empty and "Packmittel" in df_vk.columns:
                    st.divider()
                    st.markdown(f"<div class='section-header'><h3>{t('b_aus_carton_title')}</h3></div>", unsafe_allow_html=True)
                    st.caption("Rozměry a vlastní váhy krabic z Auswertungu, obohaceno o pohyby z vašeho pick reportu.")

                    dim_cols = [c for c in ["Laenge", "Breite", "Hoehe", "Eigengewicht"] if c in df_vk.columns]

                    df_vk_c = df_vk.copy()
                    if not pick_per_delivery.empty and "Lieferung" in df_vk_c.columns:
                        df_vk_c = df_vk_c.merge(
                            pick_per_delivery[["Delivery", "pohyby_celkem", "pocet_lokaci", "pocet_to"]],
                            left_on="Lieferung", right_on="Delivery", how="left")

                    has_pick_c = "pohyby_celkem" in df_vk_c.columns

                    c_agg = {
                        "pocet": ("HU_intern", "nunique"),
                        "avg_gew": ("Gesamtgewicht", "mean") if "Gesamtgewicht" in df_vk_c.columns else ("HU_intern", "count"),
                        **{d: (d, "first") for d in dim_cols},
                    }
                    if has_pick_c:
                        c_agg["sum_pohyby"] = ("pohyby_celkem", "sum")
                        c_agg["sum_lokaci"]  = ("pocet_lokaci",  "sum")
                        c_agg["sum_to"]      = ("pocet_to",      "sum")

                    carton_agg = (df_vk_c[df_vk_c["Packmittel"].notna()]
                                  .groupby("Packmittel").agg(**c_agg)
                                  .reset_index().sort_values("pocet", ascending=False))

                    if has_pick_c:
                        carton_agg["avg_mov_per_loc"] = np.where(
                            carton_agg["sum_lokaci"] > 0,
                            carton_agg["sum_pohyby"] / carton_agg["sum_lokaci"], 0)

                    rename_c = {
                        "Packmittel": t("b_aus_carton"), "pocet": t("b_aus_pocet"),
                        "avg_gew": t("b_aus_avg_vaha"),
                        "Laenge": t("b_aus_delka"), "Breite": t("b_aus_sirka"),
                        "Hoehe": t("b_aus_vyska"), "Eigengewicht": "Vl. váha krabice (kg)",
                        "sum_pohyby": "Pohyby celkem", "sum_lokaci": "Lokací celkem",
                        "sum_to": "TO celkem", "avg_mov_per_loc": "Prům. pohybů / lok.",
                    }
                    carton_disp = carton_agg.rename(columns={k: v for k, v in rename_c.items()
                                                              if k in carton_agg.columns})
                    fmt_c = {}
                    for col_name, fmt in [(t("b_aus_avg_vaha"), "{:.2f}"),
                                          ("Vl. váha krabice (kg)", "{:.2f}"),
                                          (t("b_aus_delka"), "{:.0f}"),
                                          (t("b_aus_sirka"), "{:.0f}"),
                                          (t("b_aus_vyska"), "{:.0f}"),
                                          ("Prům. pohybů / lok.", "{:.2f}"),
                                          ("Pohyby celkem", "{:,.0f}"),
                                          ("Lokací celkem", "{:,.0f}"),
                                          ("TO celkem", "{:,.0f}")]:
                        if col_name in carton_disp.columns:
                            fmt_c[col_name] = fmt

                    st.dataframe(
                        carton_disp.style.format(fmt_c)
                        .set_properties(subset=["Prům. pohybů / lok."]
                                        if "Prům. pohybů / lok." in carton_disp.columns else [],
                                        **{"font-weight": "bold", "background-color": "#fff8e1"}),
                        use_container_width=True, hide_index=True)

                st.divider()
                st.markdown(f"<div class='section-header'><h3>{t('b_aus_sped_title')}</h3></div>", unsafe_allow_html=True)
                kc1, kc2 = st.columns(2)
                with kc1:
                    with st.container(border=True): st.metric(t("b_aus_kep_count"), str(len(kep_set)))
                with kc2:
                    with st.container(border=True): st.metric(t("b_aus_nonkep_count"), str(len(df_sdshp) - len(kep_set) if not df_sdshp.empty else 0))
                
                if not sdshp_display.empty:
                    col_s0 = sdshp_display.columns[0]
                    sdshp_d2 = sdshp_display.copy()
                    sdshp_d2["Je KEP"] = sdshp_d2[col_s0].astype(str).str.strip().isin(kep_set).map({True: "✅ KEP", False: "—"})
                    with st.expander("Zobrazit tabulku dopravců (SDSHP_AM2)"):
                        st.dataframe(sdshp_d2, use_container_width=True, hide_index=True)

                st.divider()
                st.markdown(f"<div class='section-header'><h3>{t('b_aus_voll_title')}</h3></div>", unsafe_allow_html=True)
                vt1, vt2 = st.columns(2)
                with vt1:
                    with st.container(border=True): st.metric(t("b_aus_voll_count"), f"{len(vollpalette_lager):,}".replace(",", " "))
                if not df_vk.empty and "Art_HU" in df_vk.columns:
                    with vt2:
                        with st.container(border=True): st.metric("HU označených Vollpalette", f"{int((df_vk['Art_HU'] == 'Vollpalette').sum()):,}".replace(",", " "))
                if not df_t023.empty:
                    with st.expander("Zobrazit T023 — přímé pohyby celých palet"):
                        t023_d = df_t023.copy()
                        t023_d.columns = (["Lagereinheit (HU)", "Transport Order č.", "Pozice TO"] + list(t023_d.columns[3:]))
                        st.dataframe(t023_d, use_container_width=True, hide_index=True)

                st.divider()
                with st.expander(t("b_aus_detail_exp"), expanded=False):
                    if not aus_lief.empty:
                        det_cols_s = ["Lieferung", "Kategorie"]
                        det_fmt    = {}
                        if "anzahl_hu" in aus_lief.columns: det_cols_s.append("anzahl_hu")
                        if gew_col: det_cols_s.append(gew_col); det_fmt[gew_col] = "{:.1f}"
                        for ac in art_cols_avail:
                            if ac in aus_lief.columns: det_cols_s.append(ac)
                        if "avg_mov_per_loc" in aus_lief.columns:
                            det_cols_s.append("avg_mov_per_loc"); det_fmt["avg_mov_per_loc"] = "{:.2f}"
                        if "pm_typy" in aus_lief.columns: det_cols_s.append("pm_typy")

                        det_aus = aus_lief[det_cols_s].copy()
                        det_aus["Popis"] = det_aus["Kategorie"].map(kat_desc_map).fillna(det_aus["Kategorie"])
                        sort_by = gew_col if (gew_col and gew_col in det_aus.columns) else "Lieferung"
                        det_aus = det_aus.sort_values(sort_by, ascending=False)

                        col_renames = {"Lieferung": "Delivery", "Kategorie": t("b_aus_kat"), "anzahl_hu": t("b_aus_hu"), "pm_typy": t("b_aus_carton"),
                                       "Popis": t("b_aus_popis"), "Brutto_kg": "Váha LIPS (kg)", "celk_gew": "Váha VEKP (kg)", "avg_mov_per_loc": "Prům. pohybů / lokaci"}
                        det_aus = det_aus.rename(columns={k: v for k, v in col_renames.items() if k in det_aus.columns})
                        det_fmt_renamed = {col_renames.get(k, k): v for k, v in det_fmt.items()}
                        st.dataframe(det_aus.style.format({k: v for k, v in det_fmt_renamed.items() if k in det_aus.columns}), use_container_width=True, hide_index=True)
                    else:
                        st.info("Žádná data zásilek k zobrazení.")

            except Exception as _e:
                import traceback
                st.error(f"Chyba při zpracování Auswertung: {_e}")
                with st.expander("Detail chyby (pro debugging)"):
                    st.code(traceback.format_exc())

    # ==========================================
    # TAB 6: ČASY BALENÍ (OE-TIMES)
    # ==========================================
    with tabs[5]:
        st.markdown("<div class='section-header'><h3>⏱️ Analýza časů balení (End-to-End)</h3><p>Propojení délky balení u stolu s fyzickou náročností pickování v uličkách.</p></div>", unsafe_allow_html=True)
        
        if df_oe is not None and not df_oe.empty:
            b_df = st.session_state.get('billing_df', pd.DataFrame())
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
                        st.dataframe(disp_e2e.style.background_gradient(subset=["Čas Balení (min)"], cmap='Oranges').format("{:.1f}", subset=["Čas Balení (min)", "Minut na 1 HU", "Pohybů / min balení"]), use_container_width=True, hide_index=True)

            st.markdown("<div class='section-header'><h3>📊 Detailní rozpad časů</h3></div>", unsafe_allow_html=True)
            sc1, sc2, sc3 = st.columns(3)
            
            with sc1:
                st.markdown("**Podle Zákazníka (Customer)**")
                cust_agg = df_oe[df_oe['Process_Time_Min'] > 0].groupby('CUSTOMER').agg(
                    Zakazky=('Delivery', 'nunique'), Prum_Cas=('Process_Time_Min', 'mean')
                ).reset_index().sort_values('Prum_Cas', ascending=False)
                st.dataframe(cust_agg.style.format({'Prum_Cas': '{:.1f} min'}), hide_index=True, use_container_width=True)

            with sc2:
                st.markdown("**Podle Materiálu**")
                mat_agg = df_oe[(df_oe['Process_Time_Min'] > 0) & (df_oe['Material'].notna())].groupby('Material').agg(
                    Zakazky=('Delivery', 'nunique'), Prum_Cas=('Process_Time_Min', 'mean')
                ).reset_index().sort_values('Prum_Cas', ascending=False).head(20)
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
                    p_agg = p_df.groupby('Obal').agg(
                        Vyskyt_v_Zakazkach=('Cas_Zakazky', 'count'),
                        Prum_Cas_Cele_Zakazky=('Cas_Zakazky', 'mean'),
                        Celkem_Pouzito_ks=('Pouzito_ks', 'sum')
                    ).reset_index().sort_values('Prum_Cas_Cele_Zakazky', ascending=False)
                    st.dataframe(p_agg.style.format({'Prum_Cas_Cele_Zakazky': '{:.1f} min'}), hide_index=True, use_container_width=True)
                else: st.info("Žádná specifikace obalů nenalezena.")

            st.markdown("<div class='section-header'><h3>🐌 Analýza 'Žroutů času' (Vliv na délku balení)</h3></div>", unsafe_allow_html=True)
            eaters = []
            for col in ['Scanning serial numbers', 'Reprinting labels ', 'Difficult KLTs']:
                if col in df_oe.columns:
                    mask = df_oe[col].astype(str).str.strip().str.upper().isin(['Y', 'X', 'YES', 'ANO', '1']) | (pd.to_numeric(df_oe[col], errors='coerce').fillna(0) > 0)
                    with_flag = df_oe[mask]['Process_Time_Min'].mean()
                    without_flag = df_oe[~mask]['Process_Time_Min'].mean()
                    if pd.notna(with_flag) and pd.notna(without_flag):
                        eaters.append({"Událost": col, "Prům. čas (Pokud nastane)": with_flag, "Prům. čas (Běžně)": without_flag, "Rozdíl (Zpoždění)": with_flag - without_flag, "Počet výskytů": mask.sum()})
            
            if eaters:
                edf = pd.DataFrame(eaters).sort_values("Rozdíl (Zpoždění)", ascending=False)
                st.dataframe(edf.style.background_gradient(subset=["Rozdíl (Zpoždění)"], cmap='Reds').format("{:.1f} min", subset=["Prům. čas (Pokud nastane)", "Prům. čas (Běžně)", "Rozdíl (Zpoždění)"]), hide_index=True, use_container_width=True)

        else:
            st.warning("⚠️ Pro zobrazení této sekce nahrajte prosím soubor s časy balení (OE-Times.xlsx).")

    # ==========================================
    # TAB 7: NÁSTROJE & AUDIT
    # ==========================================
    with tabs[6]:
        col_au1, col_au2 = st.columns([3, 2])

        with col_au1:
            st.markdown(f"<div class='section-header'><h3>{t('audit_title')}</h3></div>", unsafe_allow_html=True)

            need_new_samples = (
                'audit_samples' not in st.session_state
                or st.session_state.get('last_audit_hash') != st.session_state.get('last_files_hash')
            )

            if need_new_samples or st.button(t('audit_gen_btn'), type="primary"):
                audit_samples = {}
                valid_queues = sorted([
                    q for q in df_pick['Queue'].dropna().unique() if q not in ['N/A', 'CLEARANCE']
                ])
                for q in valid_queues:
                    q_data = df_pick[df_pick['Queue'] == q]
                    unique_tos = q_data[queue_count_col].dropna().unique()
                    if len(unique_tos) > 0:
                        audit_samples[q] = np.random.choice(
                            unique_tos, min(5, len(unique_tos)), replace=False
                        )
                st.session_state['audit_samples'] = audit_samples
                st.session_state['last_audit_hash'] = st.session_state.get('last_files_hash')

            for q, tos in st.session_state.get('audit_samples', {}).items():
                with st.expander(f"📁 Queue: **{q}** — {len(tos)} vzorků", expanded=False):
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
                            su = str(row.get('Removal of total SU', ''))
                            src_bin = row.get('Source Storage Bin', '?')
                            queue_str = str(row.get('Queue', '')).upper()

                            boxes_str = str(real_boxes) if real_boxes else f"*{t('box_missing')}*"
                            st.markdown(
                                f"**Mat:** `{mat}` | **Bin:** `{src_bin}` | "
                                f"**Qty:** {int(qty)} | **{t('box_sizes')}:** {boxes_str} | "
                                f"**{t('marm_weight')}:** {w:.3f} kg | "
                                f"**{t('marm_dim')}:** {d:.1f} cm"
                            )

                            if su == 'X' and queue_str in ['PI_PL_FU', 'PI_PL_FUOE']:
                                st.info(t('audit_su_x').format(queue_str))
                            else:
                                if su == 'X':
                                    st.caption(t('audit_su_ign').format(queue_str))

                                zbytek = qty
                                for b in real_boxes:
                                    if zbytek >= b:
                                        m = int(zbytek // b)
                                        st.write(t('audit_box').format(m, b))
                                        zbytek = zbytek % b

                                if zbytek > 0:
                                    over_limit = (w >= limit_vahy) or (d >= limit_rozmeru)
                                    limit_str = (f"{limit_vahy}kg" if w >= limit_vahy else f"{limit_rozmeru}cm")
                                    if over_limit:
                                        st.warning(t('audit_lim').format(int(zbytek), limit_str, int(zbytek)))
                                    else:
                                        hmaty = int(np.ceil(zbytek / kusy_na_hmat))
                                        st.success(t('audit_grab').format(int(zbytek), hmaty, kusy_na_hmat))

                            total_moves = int(row.get('Pohyby_Rukou', 0))
                            st.markdown(f"> **{t('audit_phys_moves')}: `{total_moves}`**")
                            st.write("---")

        with col_au2:
            st.markdown(f"<div class='section-header'><h3>{t('sec3_title')}</h3></div>", unsafe_allow_html=True)
            mat_search = st.selectbox(
                t('search_label'),
                options=[""] + sorted(df_pick['Material'].unique().tolist())
            )

            if mat_search:
                search_key = get_match_key(mat_search)

                if search_key in manual_boxes:
                    st.success(t('ovr_found').format(manual_boxes[search_key]))
                else:
                    st.info(t('ovr_not_found'))

                c_info1, c_info2 = st.columns(2)
                c_info1.metric(t('marm_weight'), f"{weight_dict.get(search_key, 0):.3f} kg")
                c_info2.metric(t('marm_dim'), f"{dim_dict.get(search_key, 0):.1f} cm")

                marm_boxes = box_dict.get(search_key, [])
                if marm_boxes:
                    st.metric(t('marm_boxes'), str(marm_boxes))
                else:
                    st.metric(t('marm_boxes'), f"*{t('box_missing')}*")

        # --- NOVÝ END-TO-END RENTGEN ZAKÁZKY ---
        st.divider()
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
                if 'billing_df' in locals() and not billing_df.empty:
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

        # ==========================================
        # EXPORT DO EXCELU
        # ==========================================
        st.divider()
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            pd.DataFrame({
                "Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"],
                "Value": [f"{limit_vahy} kg", f"{limit_rozmeru} cm",
                          f"{kusy_na_hmat} pcs", num_removed_admins]
            }).to_excel(writer, index=False, sheet_name='Settings')

            if display_q is not None and not display_q.empty:
                display_q.to_excel(writer, index=False, sheet_name='Queue_Analysis')

            df_pal_exp = df_pick[
                df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])
            ].groupby('Delivery').agg(
                num_materials=('Material', 'nunique'),
                material=('Material', 'first'),
                total_qty=('Qty', 'sum'),
                celkem_pohybu=('Pohyby_Rukou', 'sum'),
                pohyby_exact=('Pohyby_Exact', 'sum'),
                pohyby_miss=('Pohyby_Loose_Miss', 'sum'),
                vaha_zakazky=('Celkova_Vaha_KG', 'sum'),
                max_rozmer=('Piece_Max_Dim_CM', 'first')
            )
            df_pal_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
            if not df_pal_single.empty:
                df_pal_single[[
                    'material', 'total_qty', 'celkem_pohybu',
                    'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer'
                ]].rename(columns={
                    'material': t('col_mat'), 'total_qty': t('col_qty'),
                    'celkem_pohybu': t('col_mov'), 'pohyby_exact': t('col_mov_exact'),
                    'pohyby_miss': t('col_mov_miss'), 'vaha_zakazky': t('col_wgt'),
                    'max_rozmer': t('col_max_dim')
                }).to_excel(writer, index=True, sheet_name='Single_Mat_Orders')

            df_pick.groupby('Material').agg(
                Moves=('Pohyby_Rukou', 'sum'),
                Qty=('Qty', 'sum'),
                Exact=('Pohyby_Exact', 'sum'),
                Estimates=('Pohyby_Loose_Miss', 'sum'),
                Lines=('Material', 'count')
            ).reset_index().sort_values('Moves', ascending=False).to_excel(
                writer, index=False, sheet_name='Material_Totals'
            )

        st.download_button(
            label=t('btn_download'),
            data=buffer.getvalue(),
            file_name=f"Warehouse_Control_Tower_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )


if __name__ == "__main__":
    main()
