import streamlit as st
import pandas as pd
import numpy as np
import io
import time

# Databáze a výpočty
from database import save_to_db, load_from_db
from modules.utils import t, fast_compute_moves, get_match_key_vectorized, get_match_key, parse_packing_time, BOX_UNITS

# Záložky (Tabs) z naší nové struktury
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
    div[data-testid="metric-container"] { background-color: #ffffff; border: 1px solid #e2e8f0; padding: 1rem 1.5rem; border-radius: 0.75rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    .main-header { font-size: 2.75rem; font-weight: 800; background: -webkit-linear-gradient(45deg, #1e3a8a, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.1rem; color: #64748b; margin-bottom: 2rem; font-weight: 500; }
    .section-header { color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; margin-top: 2rem; margin-bottom: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

if 'lang' not in st.session_state: st.session_state.lang = 'cs'

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

    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick['Material'] = df_pick['Material'].astype(str).str.strip().replace(to_replace=['nan', 'NaN', 'None', 'none', ''], value=np.nan)
    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    
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
            for d_col in ['Confirmation Date', 'Creation Date']:
                if d_col in df_queue_raw.columns:
                    d_map = df_queue_raw.dropna(subset=['Transfer Order Number', d_col]).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')[d_col].to_dict()
                    to_dates = df_pick['Transfer Order Number'].map(d_map)
                    df_pick['Date'] = df_pick['Date'].fillna(pd.to_datetime(to_dates, errors='coerce'))
                    break
        elif 'SD Document' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['SD Document', 'Queue']).drop_duplicates('SD Document').set_index('SD Document')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Delivery'].map(q_map).fillna('N/A')
        df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

    import re
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

    auto_voll_hus = set()
    mask_x = df_pick['Removal of total SU'] == 'X'
    if 'Handling Unit' in df_pick.columns: auto_voll_hus.update(df_pick.loc[mask_x, 'Handling Unit'].dropna().astype(str).str.strip())
    auto_voll_hus = {h for h in auto_voll_hus if h not in ["", "nan", "None"]}

    df_oe = load_from_db('raw_oe')
    if df_oe is not None and not df_oe.empty:
        df_oe['Delivery'] = df_oe['DN NUMBER (SAP)'].astype(str).str.strip()
        df_oe['Process_Time_Min'] = df_oe['Process Time'].apply(parse_packing_time)
        agg_dict = {'Process_Time_Min': 'sum'}
        for col in ['CUSTOMER', 'Material', 'Scanning serial numbers', 'Reprinting labels ', 'Difficult KLTs', 'Shift', 'Number of item types']:
            if col in df_oe.columns: agg_dict[col] = 'first'
        for col in ['KLT', 'Palety', 'Cartons']:
            if col in df_oe.columns: agg_dict[col] = lambda x: '; '.join(x.dropna().astype(str))
        df_oe = df_oe.groupby('Delivery').agg(agg_dict).reset_index()

    df_cats = load_from_db('raw_cats')
    if df_cats is not None and not df_cats.empty:
        df_cats['Lieferung'] = df_cats['Lieferung'].astype(str).str.strip()
        if 'Kategorie' in df_cats.columns and 'Art' in df_cats.columns: df_cats['Category_Full'] = df_cats['Kategorie'].astype(str).str.strip() + " " + df_cats['Art'].astype(str).str.strip()
        df_cats = df_cats.drop_duplicates('Lieferung')

    aus_data = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None: aus_data[sheet] = aus_df

    return {
        'df_pick': df_pick, 'queue_count_col': queue_count_col, 'auto_voll_hus': auto_voll_hus,
        'df_vekp': load_from_db('raw_vekp'), 'df_vepo': load_from_db('raw_vepo'),
        'df_cats': df_cats, 'df_oe': df_oe, 'aus_data': aus_data,
        'num_removed_admins': num_removed_admins, 'manual_boxes': manual_boxes,
        'weight_dict': weight_dict, 'dim_dict': dim_dict, 'box_dict': box_dict
    }

# ==========================================
# 3. HLAVNÍ BĚH APLIKACE A ADMIN ZÓNA
# ==========================================
def main():
    col_title, col_lang = st.columns([8, 1])
    with col_title:
        st.markdown(f"<div class='main-header'>{t('title')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub-header'>{t('desc')}</div>", unsafe_allow_html=True)
    with col_lang:
        if st.button(t('switch_lang')):
            st.session_state.lang = 'en' if st.session_state.lang == 'cs' else 'cs'
            st.rerun()

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
                        try:
                            fname = file.name.lower()
                            if fname.endswith('.xlsx') and 'auswertung' in fname:
                                aus_xl = pd.ExcelFile(file)
                                for sn in aus_xl.sheet_names: 
                                    save_to_db(aus_xl.parse(sn, dtype=str), f"aus_{sn.lower()}")
                                st.success(f"✅ Uloženo (Auswertung): {file.name}")
                                continue

                            temp_df = pd.read_csv(file, dtype=str, sep=None, engine='python') if fname.endswith('.csv') else pd.read_excel(file, dtype=str)
                            
                            # Odstraníme neviditelné znaky a převedeme na velká písmena pro "chytré" hledání
                            temp_df.columns = temp_df.columns.str.strip()
                            cols = temp_df.columns.tolist()
                            cols_up = [str(c).upper() for c in cols]
                            
                            # Vylepšené, nerozbitné rozpoznávání (hledá jen části textu a ignoruje velikost písmen)
                            if any('DELIVERY' in c for c in cols_up) and any('ACT.QTY' in c for c in cols_up):
                                save_to_db(temp_df, 'raw_pick')
                                st.success(f"✅ Uloženo jako Pick Report: {file.name}")
                            elif any('NUMERATOR' in c for c in cols_up) and any('ALTERNATIVE UNIT' in c for c in cols_up): 
                                save_to_db(temp_df, 'raw_marm')
                                st.success(f"✅ Uloženo jako MARM: {file.name}")
                            elif any('HANDLING UNIT' in c for c in cols_up) and any('GENERATED DELIVERY' in c for c in cols_up): 
                                save_to_db(temp_df, 'raw_vekp')
                                st.success(f"✅ Uloženo jako VEKP: {file.name}")
                            elif (any('HANDLING UNIT ITEM' in c for c in cols_up) or any('HANDLING UNIT POSITION' in c for c in cols_up)) and any('MATERIAL' in c for c in cols_up): 
                                save_to_db(temp_df, 'raw_vepo')
                                st.success(f"✅ Uloženo jako VEPO: {file.name}")
                            elif any('LIEFERUNG' in c for c in cols_up) and any('KATEGORIE' in c for c in cols_up): 
                                save_to_db(temp_df, 'raw_cats')
                                st.success(f"✅ Uloženo jako Kategorie: {file.name}")
                            elif any('QUEUE' in c for c in cols_up) and (any('TRANSFER ORDER' in c for c in cols_up) or any('SD DOCUMENT' in c for c in cols_up)): 
                                save_to_db(temp_df, 'raw_queue')
                                st.success(f"✅ Uloženo jako Queue: {file.name}")
                            elif any('DN NUMBER' in c for c in cols_up) and any('PROCESS TIME' in c for c in cols_up):
                                # Jakmile to pozná OE-Times, sjednotí názvy sloupců, aby je pak aplikace bez problému našla
                                rename_map = {}
                                for orig, up in zip(cols, cols_up):
                                    if 'DN NUMBER' in up: rename_map[orig] = 'DN NUMBER (SAP)'
                                    if 'PROCESS TIME' in up: rename_map[orig] = 'Process Time'
                                temp_df.rename(columns=rename_map, inplace=True)
                                save_to_db(temp_df, 'raw_oe')
                                st.success(f"✅ Uloženo jako OE-Times: {file.name}")
                            elif len(cols) >= 2 and (any('MATERIAL' in c for c in cols_up) or any('MATERIÁL' in c for c in cols_up)):
                                save_to_db(temp_df, 'raw_manual')
                                st.success(f"✅ Uloženo jako Ruční Master Data: {file.name}")
                            else:
                                st.warning(f"⚠️ Soubor '{file.name}' nebyl rozpoznán! Zkontrolujte názvy sloupců.")
                            
                        except Exception as e:
                            st.error(f"❌ Chyba u souboru {file.name}: {e}")
                            
                    st.cache_data.clear()
                    time.sleep(2.0)
                    st.rerun()

    # --- ZDE BYL CHYBNÝ INDENT (ODSAZENÍ), NYNÍ ZCELA OPRAVENO ---
    with st.spinner("🔄 Načítám data z databáze..."):
        data_dict = fetch_and_prep_data()

    if data_dict is None:
        st.warning("🗄️ Databáze je zatím prázdná. Otevřete levé menu 'Admin Zóna', zadejte heslo 'admin123' a nahrajte Pick Report a další soubory.")
        return

    df_pick = data_dict['df_pick']
    st.session_state['auto_voll_hus'] = data_dict['auto_voll_hus']

    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
    st.sidebar.divider()
    date_mode = st.sidebar.radio("Filtr období:", ['Celé období', 'Podle měsíce'], label_visibility="collapsed")
    if date_mode == 'Podle měsíce':
        df_pick = df_pick[df_pick['Month'] == st.sidebar.selectbox("Vyberte měsíc:", options=sorted(df_pick['Month'].unique()))].copy()

    tt, te, tm = fast_compute_moves(df_pick['Qty'].values, df_pick['Queue'].values, df_pick['Removal of total SU'].values, df_pick['Box_Sizes_List'].values, df_pick['Piece_Weight_KG'].values, df_pick['Piece_Max_Dim_CM'].values, limit_vahy, limit_rozmeru, kusy_na_hmat)
    df_pick['Pohyby_Rukou'], df_pick['Pohyby_Exact'], df_pick['Pohyby_Loose_Miss'] = tt, te, tm
    df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

    tabs = st.tabs([t('tab_dashboard'), t('tab_pallets'), t('tab_fu'), t('tab_top'), t('tab_billing'), t('tab_packing'), t('tab_audit')])

    with tabs[0]: display_q = render_dashboard(df_pick, data_dict['queue_count_col'])
    with tabs[1]: render_pallets(df_pick)
    with tabs[2]: render_fu(df_pick, data_dict['queue_count_col'])
    with tabs[3]: render_top(df_pick)
    with tabs[4]: billing_df = render_billing(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_cats'], data_dict['queue_count_col'], data_dict['aus_data'])
    with tabs[5]: render_packing(billing_df if 'billing_df' in locals() else pd.DataFrame(), data_dict['df_oe'])
    with tabs[6]: render_audit(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_oe'], data_dict['queue_count_col'], billing_df if 'billing_df' in locals() else pd.DataFrame(), data_dict['manual_boxes'], data_dict['weight_dict'], data_dict['dim_dict'], data_dict['box_dict'], limit_vahy, limit_rozmeru, kusy_na_hmat)

    # --- EXPORT DO EXCELU ---
    st.divider()
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame({"Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"], "Value": [f"{limit_vahy} kg", f"{limit_rozmeru} cm", f"{kusy_na_hmat} pcs", data_dict['num_removed_admins']]}).to_excel(writer, index=False, sheet_name='Settings')
        if display_q is not None and not display_q.empty: display_q.to_excel(writer, index=False, sheet_name='Queue_Analysis')
        df_pal_exp = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].groupby('Delivery').agg(num_materials=('Material', 'nunique'), material=('Material', 'first'), total_qty=('Qty', 'sum'), celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'), pohyby_miss=('Pohyby_Loose_Miss', 'sum'), vaha_zakazky=('Celkova_Vaha_KG', 'sum'), max_rozmer=('Piece_Max_Dim_CM', 'first'))
        df_pal_single = df_pal_exp[df_pal_exp['num_materials'] == 1].copy()
        if not df_pal_single.empty: df_pal_single[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer']].rename(columns={'material': t('col_mat'), 'total_qty': t('col_qty'), 'celkem_pohybu': t('col_mov'), 'pohyby_exact': t('col_mov_exact'), 'pohyby_miss': t('col_mov_miss'), 'vaha_zakazky': t('col_wgt'), 'max_rozmer': t('col_max_dim')}).to_excel(writer, index=True, sheet_name='Single_Mat_Orders')
        df_pick.groupby('Material').agg(Moves=('Pohyby_Rukou', 'sum'), Qty=('Qty', 'sum'), Exact=('Pohyby_Exact', 'sum'), Estimates=('Pohyby_Loose_Miss', 'sum'), Lines=('Material', 'count')).reset_index().sort_values('Moves', ascending=False).to_excel(writer, index=False, sheet_name='Material_Totals')

    st.download_button(label=t('btn_download'), data=buffer.getvalue(), file_name=f"Warehouse_Control_Tower_{time.strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

if __name__ == "__main__":
    main()
