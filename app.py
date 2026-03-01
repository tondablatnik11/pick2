import streamlit as st
import pandas as pd
import numpy as np
import time

# Databáze a výpočty
from database import save_to_db, load_from_db
from modules.utils import fast_compute_moves

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
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0; padding: 1rem 1.5rem;
        border-radius: 0.75rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
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
    """Načte data z databáze a uloží je bleskově do paměti."""
    df_pick_raw = load_from_db('raw_pick')
    if df_pick_raw is None or df_pick_raw.empty: return None

    # Čištění pick reportu
    df_pick = df_pick_raw.copy()
    df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip().replace(['nan', 'NaN', 'None', ''], np.nan)
    df_pick['Material'] = df_pick['Material'].astype(str).str.strip().replace(['nan', 'NaN', 'None', ''], np.nan)
    df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()
    
    df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
    df_pick['Source Storage Bin'] = df_pick.get('Source Storage Bin', df_pick.get('Storage Bin', '')).fillna('').astype(str)
    df_pick['Removal of total SU'] = df_pick.get('Removal of total SU', '').fillna('').astype(str).str.strip().str.upper()
    df_pick['Date'] = pd.to_datetime(df_pick.get('Confirmation date', df_pick.get('Confirmation Date')), errors='coerce')
    
    # Automatická detekce Queue podle TO
    df_queue_raw = load_from_db('raw_queue')
    queue_count_col = 'Delivery'
    df_pick['Queue'] = 'N/A'
    if df_queue_raw is not None and not df_queue_raw.empty:
        if 'Transfer Order Number' in df_pick.columns and 'Transfer Order Number' in df_queue_raw.columns:
            q_map = df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue']).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')['Queue'].to_dict()
            df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
            queue_count_col = 'Transfer Order Number'

    # Zajištění bezpečných sloupců pro rozměry a obaly, pokud nejsou v DB
    for col in ['Piece_Weight_KG', 'Piece_Max_Dim_CM']:
        if col not in df_pick.columns: df_pick[col] = 0.0
    if 'Box_Sizes_List' not in df_pick.columns: df_pick['Box_Sizes_List'] = np.empty((len(df_pick), 0)).tolist()

    # Zpracování Vollpalet (auto_voll_hus)
    auto_voll_hus = set()
    mask_x = df_pick['Removal of total SU'] == 'X'
    if 'Handling Unit' in df_pick.columns: auto_voll_hus.update(df_pick.loc[mask_x, 'Handling Unit'].dropna().astype(str).str.strip())
    auto_voll_hus = {h for h in auto_voll_hus if h not in ["", "nan", "None"]}

    # Načtení Auswertung dat
    aus_data = {}
    for sheet in ["LIKP", "SDSHP_AM2", "T031", "VEKP", "VEPO", "LIPS", "T023"]:
        aus_df = load_from_db(f'aus_{sheet.lower()}')
        if aus_df is not None: aus_data[sheet] = aus_df

    return {
        'df_pick': df_pick, 'queue_count_col': queue_count_col, 'auto_voll_hus': auto_voll_hus,
        'df_vekp': load_from_db('raw_vekp'), 'df_vepo': load_from_db('raw_vepo'),
        'df_cats': load_from_db('raw_cats'), 'df_oe': load_from_db('raw_oe'), 'aus_data': aus_data
    }

# ==========================================
# 3. HLAVNÍ BĚH APLIKACE A ADMIN ZÓNA
# ==========================================
def main():
    st.markdown(f"<div class='main-header'>🏢 Warehouse Control Tower</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sub-header'>End-to-End analýza (Modulární architektura)</div>", unsafe_allow_html=True)

    # Parametry
    st.sidebar.header("⚙️ Konfigurace algoritmů")
    limit_vahy = st.sidebar.number_input("Hranice váhy (kg)", min_value=0.1, max_value=20.0, value=2.0, step=0.5)
    limit_rozmeru = st.sidebar.number_input("Hranice rozměru (cm)", min_value=1.0, max_value=200.0, value=15.0, step=1.0)
    kusy_na_hmat = st.sidebar.slider("Ks do hrsti", min_value=1, max_value=20, value=1, step=1)

    # Admin Zóna
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
                    st.cache_data.clear()
                    st.success("✅ Hotovo! Data jsou v databázi.")
                    time.sleep(1.5)
                    st.rerun()

    # Načtení z DB
    with st.spinner("🔄 Načítám data z databáze... (Díky cache to trvá jen zlomek sekundy)"):
        data_dict = fetch_and_prep_data()

    if data_dict is None:
        st.warning("🗄️ Databáze je zatím prázdná. Otevřete levé menu 'Admin Zóna', zadejte heslo 'admin123' a nahrajte Pick Report a další soubory.")
        return

    df_pick = data_dict['df_pick']
    st.session_state['auto_voll_hus'] = data_dict['auto_voll_hus']

    # Datumový filtr
    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', 'Neznámé')
    st.sidebar.divider()
    date_mode = st.sidebar.radio("Filtr období:", ['Celé období', 'Podle měsíce'], label_visibility="collapsed")
    if date_mode == 'Podle měsíce':
        df_pick = df_pick[df_pick['Month'] == st.sidebar.selectbox("Vyberte měsíc:", options=sorted(df_pick['Month'].unique()))].copy()

    # Přepočet fyzických pohybů
    tt, te, tm = fast_compute_moves(df_pick['Qty'].values, df_pick['Queue'].values, df_pick['Removal of total SU'].values, df_pick['Box_Sizes_List'].values, df_pick['Piece_Weight_KG'].values, df_pick['Piece_Max_Dim_CM'].values, limit_vahy, limit_rozmeru, kusy_na_hmat)
    df_pick['Pohyby_Rukou'], df_pick['Pohyby_Exact'], df_pick['Pohyby_Loose_Miss'] = tt, te, tm

    # ==========================================
    # VYKRESLENÍ ZÁLOŽEK Z MODULŮ
    # ==========================================
    tabs = st.tabs(["📊 Dashboard & Queue", "📦 Palety", "🏭 Celé palety (FU)", "🏆 TOP Materiály", "💰 Fakturace (VEKP)", "⏱️ Časy Balení (OE)", "🔍 Detailní Audit"])

    with tabs[0]: render_dashboard(df_pick, data_dict['queue_count_col'])
    with tabs[1]: render_pallets(df_pick)
    with tabs[2]: render_fu(df_pick, data_dict['queue_count_col'])
    with tabs[3]: render_top(df_pick)
    
    with tabs[4]: 
        billing_df = render_billing(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_cats'], data_dict['queue_count_col'], data_dict['aus_data'])
    
    with tabs[5]: 
        render_packing(billing_df if 'billing_df' in locals() else pd.DataFrame(), data_dict['df_oe'])
    
    with tabs[6]: 
        render_audit(df_pick, data_dict['df_vekp'], data_dict['df_vepo'], data_dict['df_oe'], data_dict['queue_count_col'], billing_df if 'billing_df' in locals() else pd.DataFrame())

if __name__ == "__main__":
    main()
