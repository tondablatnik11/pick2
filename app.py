import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import time
from openpyxl.chart import BarChart, Reference

# ==========================================
# 1. NASTAVENÍ STRÁNKY A CSS STYLING
# ==========================================
st.set_page_config(
    page_title="Analýza pickování", 
    page_icon="📦", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border: 1px solid #e0e0e0;
        padding: 5% 5% 5% 10%;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    .stProgress > div > div > div > div {
        background-color: #1f77b4;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        margin-bottom: 2rem;
    }
    </style>
""", unsafe_allow_html=True)

if 'lang' not in st.session_state:
    st.session_state.lang = 'cs'

# ==========================================
# 2. SLOVNÍKY A LOKALIZACE
# ==========================================
QUEUE_DESC = {
    'PI_PL (Mix)': 'Mix Pallet',
    'PI_PL (Total)': 'Mix Pallet',
    'PI_PL (Single)': 'Mix Pallet',
    'PI_PL_OE (Mix)': 'Mix Pallet OE',
    'PI_PA_OE': 'Parcel OE',
    'PI_PL_OE (Total)': 'Mix Pallet OE',
    'PI_PL_OE (Single)': 'Mix Pallet OE',
    'PI_PA': 'Parcel',
    'PI_PA_RU': 'Parcel Express',
    'PI_PL_FU': 'Full Pallet',
    'PI_PL_FUOE': 'Full Pallet OE'
}

TEXTS = {
    'cs': {
        'switch_lang': "🇬🇧 Switch to English",
        'title': "📦 Analýza pickování",
        'desc': "Nástroj pro modelování fyzické zátěže pickování",
        'upload_title': "📁 Nahrání vstupních dat (Klikněte pro sbalení/rozbalení)",
        'upload_help': "Nahrajte Pick report, MARM report, TO details (Queue), VEKP (Balení), Kategorie zakázek (Deliveries) a volitelně ruční ověření.",
        'info_users': "💡 Vyloučeno **{} systémových řádků** (UIDJ5089, UIH25501).",
        'info_clean': "💡 Započítán 1 pohyb pro **{} řádků** 'X' (Platí POUZE pro Queue: PI_PL_FU, PI_PL_FUOE).",
        'info_manual': "✅ Načteno ruční ověření pro **{} unikátních materiálů**.",
        'sidebar_title': "⚙️ Konfigurace algoritmů",
        'weight_label': "Hranice pro nošení po 1 ks (kg)",
        'dim_label': "Hranice rozměru pro 1 ks (cm)",
        'hmat_label': "Max ks lehkých dílů do hrsti",
        'exclude_label': "Vyloučit materiály z výpočtů:",
        'sec_ratio': "🎯 Spolehlivost dat a zdroj výpočtů",
        'ratio_desc': "Z jakých podkladů aplikace vycházela (Ukazatel kvality dat ze SAPu):",
        'logic_explain_title': "ℹ️ Podrobná metodika: Jak aplikace vypočítává výsledná data?",
        'logic_explain_text': """Tento analytický model detailně simuluje fyzickou zátěž skladníka podle následujícího postupu:

**1. Vstupní soubory:**
* **Pick report:** Hlavní soubor se seznamem vychystaných položek (obsahuje Delivery, Material, Qty, atd.).
* **MARM report:** Kmenová data o materiálech ze SAPu (váhy, rozměry a velikosti balení/krabic).
* **TO details (Queue):** Dodává informace o frontě (Queue) a datu vytvoření/potvrzení pro jednotlivé úkoly.
* **VEKP:** Dodává informace o zabalených jednotkách (HU) pro korelaci fyzické zátěže s účtováním zákazníkovi.
* **Deliveries:** Externí soubor mapující zakázky do kategorií (N Sortenrein, N Misch atd.).
* **Ruční ověření (volitelně):** Externí Excel pro ruční přepis velikosti balení.

**2. Dekompozice na celá balení (Krabice)**
Systém se automaticky dotazuje do kmenových dat (MARM) nebo do ručního ceníku. Vychystávané množství matematicky rozdělí na plné krabice. Co krabice, to **1 fyzický pohyb**.

**3. Analýza volných kusů (Limity)**
Zbylé rozbalené kusy podléhají kontrole ergonomických limitů. Každý volný kus se bere samostatně a počítá se jako **1 fyzický pohyb**.

**4. Bezpečnostní odhady (Chybějící data)**
Pokud v SAPu chybí u materiálu jakákoliv data o balení a není nahráno ani ruční ověření, systém aplikuje bezpečnostní odhad.""",
        'ratio_moves': "Podíl z celkového počtu POHYBŮ:",
        'ratio_exact': "Přesně (Krabice / Palety / Volné)",
        'ratio_miss': "Odhady (Chybí balení)",
        'exp_missing_data': "🔍 Zobrazit materiály s chybějícími daty o balení (Žebříček 'odhadů')",
        'sec_queue_title': "📊 Průměrná náročnost dle typu pickování (Queue)",
        'filter_month': "📅 Filtrovat podle měsíce:",
        'all_months': "Všechny měsíce",
        'all_queues': "Všechny Queue dohromady",
        'unknown': "Neznámé",
        'q_col_queue': "Queue",
        'q_col_desc': "Popis",
        'q_col_to': "Počet TO",
        'q_col_orders': "Zakázky",
        'q_col_loc': "Prům. lokací",
        'q_col_pcs': "Prům. kusů",
        'q_col_mov_loc': "Prům. pohybů na lokaci",
        'q_col_exact_loc': "Prům. přesně na lokaci",
        'q_pct_exact': "% Přesně",
        'q_col_miss_loc': "Prům. odhad na lokaci",
        'q_pct_miss': "% Odhad",
        'sec_queue_top_title': "🏆 TOP 100 materiálů podle Queue",
        'q_select': "Zobrazit TOP 100 pro:",
        'sec1_title': "🎯 Analýza paletových zakázek (Mix Pallet)",
        'pallets_clean_info': "*(Počítáno výhradně z front PI_PL a PI_PL_OE)*",
        'm_orders': "Počet zakázek",
        'm_qty': "Prům. kusů / zakázku",
        'm_pos': "Prům. pozic / zakázku",
        'm_mov_loc': "Prům. fyz. pohybů na lokaci",
        'exp_detail_title': "Zobrazit tabulku zakázek (1 materiál)",
        'col_mat': "Materiál",
        'col_qty': "Kusů celkem",
        'col_mov': "Celkem pohybů",
        'col_mov_exact': "Pohyby (Přesně)",
        'col_mov_miss': "Pohyby (Odhady)",
        'col_wgt': "Hmotnost (kg)",
        'col_max_dim': "Rozměr (cm)",
        'col_cert': "Certifikát",
        'audit_title': "🎲 Detailní Auditní Report (Náhodné vzorky)",
        'audit_phys_moves': "Fyzických pohybů",
        'audit_gen_btn': "🔄 Vygenerovat nové vzorky",
        'sec3_title': "🔍 Prohlížeč Master Dat",
        'search_label': "Zkontrolujte si konkrétní materiál:",
        'tab_dashboard': "📊 Dashboard & Queue",
        'tab_pallets': "📦 Paletové zakázky",
        'tab_top': "🏆 TOP Materiály",
        'tab_billing': "💰 Účtování a balení (VEKP)",
        'tab_audit': "🔍 Nástroje & Audit",
        'b_title': "💰 Korelace mezi Pickováním a Účtováním",
        'b_desc': "Zákazník platí podle počtu výsledných balících jednotek (HU - palet/balíků). Zde vidíte, kolik reálné pickovací námahy bylo potřeba na vytvoření těchto zpoplatněných jednotek.",
        'b_del_count': "Počet Deliveries",
        'b_to_count': "Pickovacích TO celkem",
        'b_hu_count': "Celkem balících HU (VEKP)",
        'b_mov_per_hu': "Pohybů na 1 zabalenou HU celkem",
        'b_cat_title': "📊 Souhrn nákladnosti podle Kategorií",
        'b_table_cat': "Kategorie (Art)",
        'b_table_del': "Delivery",
        'b_table_to': "Počet TO",
        'b_table_mov': "Pohyby celkem",
        'b_table_hu': "Počet HU",
        'b_table_mph': "Pohybů na 1 HU",
        'b_missing_vekp': "⚠️ Pro zobrazení těchto dat nahrajte soubor VEKP.",
        'col_lines': "Řádky",
        'btn_download': "📥 Stáhnout kompletní report (Excel)",
        'err_pick': "Chyba: Pick report nebyl nalezen ve vstupech.",
        'no_orders': "Nenalezeny žádné zakázky pro zobrazení.",
        'audit_su_x': "➡️ Celá paleta (X) ve frontě {}. -> **1 pohyb.**",
        'audit_su_ign': "*(Značka 'X' ignorována, fronta {} nevozí celé palety)*",
        'audit_box': "➡️ Odebráno **{}x Krabice** (po {} ks)",
        'audit_lim': "➡️ Zbylých {} ks překračuje limit -> **{} pohybů**.",
        'audit_grab': "➡️ Zbylých {} ks do hrsti -> **{} pohybů**.",
        'ovr_found': "✅ Ruční ověření: **{} ks**.",
        'ovr_not_found': "ℹ️ Žádné ruční ověření.",
        'marm_weight': "Váha (MARM)",
        'marm_dim': "Rozměr (MARM)",
        'box_missing': "Chybí"
    },
    'en': {
        'switch_lang': "🇨🇿 Přepnout do češtiny",
        'title': "📦 Picking Analysis",
        'desc': "Tool for modeling physical picking workload.",
        'upload_title': "📁 Upload Input Data (Click to expand/collapse)",
        'upload_help': "Upload Pick report, MARM report, TO details (Queue), VEKP (Packing), Deliveries Categories, and optional Manual Override.",
        'info_users': "💡 Excluded **{} system lines** (UIDJ5089, UIH25501).",
        'info_clean': "💡 1 move counted for **{} lines** of 'X' (Applies ONLY to PI_PL_FU, PI_PL_FUOE).",
        'info_manual': "✅ Loaded manual packaging for **{} unique materials**.",
        'sidebar_title': "⚙️ Algorithm Configuration",
        'weight_label': "Weight limit for 1-by-1 pick (kg)",
        'dim_label': "Dimension limit for 1-by-1 (cm)",
        'hmat_label': "Max pieces per grab",
        'exclude_label': "Exclude materials:",
        'sec_ratio': "🎯 Data Reliability & Source",
        'ratio_desc': "Data foundation (SAP Data Quality indicator):",
        'logic_explain_title': "ℹ️ Detailed Methodology: How does the app calculate the resulting data?",
        'logic_explain_text': """This analytical model meticulously simulates the picker's physical workload using the following procedure:

**1. Input Files:**
* **Pick report:** Main file with the list of picked items.
* **MARM report:** Master data for materials from SAP.
* **TO details (Queue):** Provides Queue information and task confirmation dates.
* **VEKP:** Provides data about packed Handling Units (HUs) to correlate physical effort with customer billing.
* **Deliveries:** External file mapping deliveries to specific billing categories (e.g. N Sortenrein).
* **Manual Override (optional):** An external Excel file to manually set packaging sizes.

**2. Decomposition into Full Boxes (Packaging)**
Quantities are mathematically broken down into full boxes. Each box equals **1 physical move**.

**3. Loose Pieces Analysis (Limits)**
Remaining unpacked pieces are checked against ergonomic limits. Every loose piece is handled individually, meaning each piece equals **1 physical move**.

**4. Safety Estimates (Missing Data)**
If SAP lacks packaging data for a material, the system applies a safety estimate directly based on the weight and dimensions of each individual piece.""",
        'ratio_moves': "Share of total MOVEMENTS:",
        'ratio_exact': "Exact (Boxes / Pallets / Loose)",
        'ratio_miss': "Estimates (Missing packaging)",
        'exp_missing_data': "🔍 Show materials with missing box data (Estimates Leaderboard)",
        'sec_queue_title': "📊 Average Workload by Queue",
        'filter_month': "📅 Filter by month:",
        'all_months': "All months",
        'all_queues': "All Queues combined",
        'unknown': "Unknown",
        'q_col_queue': "Queue",
        'q_col_desc': "Description",
        'q_col_to': "TO Count",
        'q_col_orders': "Orders",
        'q_col_loc': "Avg Locs",
        'q_col_pcs': "Avg Pieces",
        'q_col_mov_loc': "Avg Moves per Loc",
        'q_col_exact_loc': "Avg Exact per Loc",
        'q_pct_exact': "% Exact",
        'q_col_miss_loc': "Avg Estimate per Loc",
        'q_pct_miss': "% Estimate",
        'sec_queue_top_title': "🏆 TOP 100 Materials",
        'q_select': "Show TOP 100 for:",
        'sec1_title': "🎯 Pallet Order Analysis (Mix Pallet)",
        'pallets_clean_info': "*(Calculated strictly from PI_PL and PI_PL_OE queues)*",
        'm_orders': "Orders",
        'm_qty': "Avg Pcs / Order",
        'm_pos': "Avg Bins / Order",
        'm_mov_loc': "Avg Physical Moves per Loc",
        'exp_detail_title': "Show Orders Table (1 Material)",
        'col_mat': "Material",
        'col_qty': "Total Pieces",
        'col_mov': "Total Moves",
        'col_mov_exact': "Moves (Exact)",
        'col_mov_miss': "Moves (Estimates)",
        'col_wgt': "Weight (kg)",
        'col_max_dim': "Max Dim (cm)",
        'col_cert': "Certificate",
        'audit_title': "🎲 Detailed Logic Audit (Random samples)",
        'audit_phys_moves': "Physical moves",
        'audit_gen_btn': "🔄 Generate New Samples",
        'sec3_title': "🔍 Master Data Viewer",
        'search_label': "Check specific material data:",
        'tab_dashboard': "📊 Dashboard & Queue",
        'tab_pallets': "📦 Pallet Orders",
        'tab_top': "🏆 TOP Materials",
        'tab_billing': "💰 Billing & Packing (VEKP)",
        'tab_audit': "🔍 Tools & Audit",
        'b_title': "💰 Correlation Between Picking and Billing",
        'b_desc': "The customer pays based on the number of packed Handling Units (HUs). Here you can see how much real picking effort was required to create these billed units.",
        'b_del_count': "Delivery Count",
        'b_to_count': "Total TOs Picked",
        'b_hu_count': "Total Packed HUs (VEKP)",
        'b_mov_per_hu': "Avg Moves per Packed HU",
        'b_cat_title': "📊 Workload Summary by Categories",
        'b_table_cat': "Category (Type)",
        'b_table_del': "Delivery",
        'b_table_to': "TO Count",
        'b_table_mov': "Total Moves",
        'b_table_hu': "HU Count",
        'b_table_mph': "Moves per HU",
        'b_missing_vekp': "⚠️ Please upload the VEKP file to display billing data.",
        'col_lines': "Lines",
        'btn_download': "📥 Download Comprehensive Report (Excel)",
        'err_pick': "Error: Pick report not found in uploads.",
        'no_orders': "No orders found.",
        'audit_su_x': "➡️ Full unit (X) in {}. -> **1 move.**",
        'audit_su_ign': "*(Ignored 'X' marker because queue {} is not Full Pallet...)*",
        'audit_box': "➡️ **{}x Box** (per {} pcs)",
        'audit_lim': "➡️ Remaining {} pcs over limit -> **{} moves**.",
        'audit_grab': "➡️ Remaining {} pcs grabbed -> **{} moves**.",
        'ovr_found': "✅ Master Data Override: **{} pcs**.",
        'ovr_not_found': "ℹ️ No override found.",
        'marm_weight': "Weight (MARM)",
        'marm_dim': "Max Dim (MARM)",
        'box_missing': "Missing"
    }
}

# --- POMOCNÉ FUNKCE ---
def t(key):
    return TEXTS[st.session_state.lang][key]

def get_match_key(val):
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit():
        return v.rstrip('0').rstrip('.')
    return v

def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list, v_lim, d_lim, h_lim):
    """Blesková vektorizovaná kalkulace pro okamžitý chod po pohybu posuvníků."""
    res_total, res_exact, res_miss = [], [], []
    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list, box_list, w_list, d_list):
        if qty <= 0:
            res_total.append(0); res_exact.append(0); res_miss.append(0)
            continue
            
        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1); res_exact.append(1); res_miss.append(0)
            continue
            
        pb = pok = pmiss = 0
        zbytek = qty
        
        if boxes:
            for b in boxes:
                if b > 1 and zbytek >= b:
                    m = int(zbytek // b)
                    pb += m
                    zbytek %= b
                    
        if zbytek > 0:
            if w >= v_lim or d >= d_lim:
                p = int(zbytek) 
            else:
                p = int(np.ceil(zbytek / h_lim))
                
            if not boxes:
                pmiss += p  
            else:
                pok += p    
                
        res_total.append(pb + pok + pmiss)
        res_exact.append(pb + pok)
        res_miss.append(pmiss)
        
    return res_total, res_exact, res_miss

# ==========================================
# 3. HLAVNÍ APLIKACE A SESSION STATE LOGIKA
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

    st.sidebar.header(t('sidebar_title'))
    limit_vahy = st.sidebar.number_input(t('weight_label'), min_value=0.1, max_value=20.0, value=2.0, step=0.5)
    limit_rozmeru = st.sidebar.number_input(t('dim_label'), min_value=1.0, max_value=200.0, value=15.0, step=1.0)
    kusy_na_hmat = st.sidebar.slider(t('hmat_label'), min_value=1, max_value=20, value=1, step=1)
    
    with st.expander(t('upload_title'), expanded=True):
        st.markdown(f"**{t('upload_help')}**")
        uploaded_files = st.file_uploader("UploadFiles", label_visibility="collapsed", type=['csv', 'xlsx'], accept_multiple_files=True, key="main_uploader")

    if uploaded_files:
        current_files_hash = "".join([f"{f.name}{f.size}" for f in uploaded_files])
        
        # --- CACHING A PARSOVÁNÍ SOUBORŮ ---
        if st.session_state.get('last_files_hash') != current_files_hash:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            df_pick_raw, df_marm_raw, df_manual_raw, df_queue_raw, df_vekp_raw, df_cats_raw = None, None, None, None, None, None

            status_text.markdown("**🔄 Načítání a čtení vstupních souborů...**" if st.session_state.lang == 'cs' else "**🔄 Loading files...**")
            progress_bar.progress(20)

            for file in uploaded_files:
                fname = file.name.lower()
                temp_df = pd.read_csv(file, dtype=str) if fname.endswith('.csv') else pd.read_excel(file, dtype=str)
                
                if 'Delivery' in temp_df.columns and 'Act.qty (dest)' in temp_df.columns:
                    df_pick_raw = temp_df
                elif 'Numerator' in temp_df.columns and 'Alternative Unit of Measure' in temp_df.columns:
                    df_marm_raw = temp_df
                elif 'Handling Unit' in temp_df.columns and 'Generated delivery' in temp_df.columns:
                    df_vekp_raw = temp_df
                elif 'Lieferung' in temp_df.columns and 'Kategorie' in temp_df.columns:
                    df_cats_raw = temp_df
                elif 'Queue' in temp_df.columns and ('Transfer Order Number' in temp_df.columns or 'SD Document' in temp_df.columns):
                    df_queue_raw = temp_df
                elif len(temp_df.columns) >= 2:
                    df_manual_raw = temp_df

            if df_pick_raw is None:
                st.error(t('err_pick'))
                progress_bar.empty()
                status_text.empty()
                return

            status_text.markdown("**⚙️ Zpracování Master Dat a systémových filtrů...**" if st.session_state.lang == 'cs' else "**⚙️ Processing Master Data...**")
            progress_bar.progress(50)
            
            df_pick = df_pick_raw.copy()
            df_pick['Material'] = df_pick['Material'].astype(str).str.strip()
            df_pick['Match_Key'] = df_pick['Material'].apply(get_match_key)
            df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
            df_pick['Source Storage Bin'] = df_pick.get('Source Storage Bin', df_pick.get('Storage Bin', ''))
            df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip()
            
            num_removed_admins = 0
            if 'User' in df_pick.columns:
                mask_admins = df_pick['User'].isin(['UIDJ5089', 'UIH25501'])
                num_removed_admins = mask_admins.sum()
                df_pick = df_pick[~mask_admins].copy()
                
            df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()

            queue_count_col = 'Delivery'
            if df_queue_raw is not None:
                if 'Transfer Order Number' in df_pick.columns and 'Transfer Order Number' in df_queue_raw.columns:
                    q_map = df_queue_raw.dropna(subset=['Transfer Order Number', 'Queue']).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')['Queue'].to_dict()
                    df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map)
                    queue_count_col = 'Transfer Order Number'
                    
                    for d_col in ['Confirmation Date', 'Creation Date']:
                        if d_col in df_queue_raw.columns:
                            d_map = df_queue_raw.dropna(subset=['Transfer Order Number', d_col]).drop_duplicates('Transfer Order Number').set_index('Transfer Order Number')[d_col].to_dict()
                            df_pick['Date'] = df_pick['Transfer Order Number'].map(d_map)
                            break
                elif 'SD Document' in df_queue_raw.columns:
                    q_map = df_queue_raw.dropna(subset=['SD Document', 'Queue']).drop_duplicates('SD Document').set_index('SD Document')['Queue'].to_dict()
                    df_pick['Queue'] = df_pick['Delivery'].map(q_map)
                    for d_col in ['Confirmation Date', 'Creation Date']:
                        if d_col in df_queue_raw.columns:
                            d_map = df_queue_raw.dropna(subset=['SD Document', d_col]).drop_duplicates('SD Document').set_index('SD Document')[d_col].to_dict()
                            df_pick['Date'] = df_pick['Delivery'].map(d_map)
                            break
                            
                if 'Queue' in df_pick.columns:
                    df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()
            else:
                df_pick['Queue'], df_pick['Date'] = 'N/A', np.nan

            df_pick['Removal of total SU'] = df_pick['Removal of total SU'].fillna('').astype(str).str.strip().str.upper()

            manual_boxes = {}
            if df_manual_raw is not None and not df_manual_raw.empty:
                c_mat, c_pkg = df_manual_raw.columns[0], df_manual_raw.columns[1]
                for _, row in df_manual_raw.iterrows():
                    if pd.isna(row[c_mat]) or str(row[c_mat]).upper() in ['NAN', 'NONE', '']: continue
                    mat_key = get_match_key(str(row[c_mat]))
                    pkg = str(row[c_pkg])
                    nums = re.findall(r'(\d+)\s*(?:ks|kus|pcs)|\bK-(\d+)\b|(?:pytl[íi]k|pytel|role|balen[íi]|krabice|karton|box)[^\d]*(\d+)', pkg, flags=re.IGNORECASE)
                    ext = sorted(list(set([int(g) for m in nums for g in m if g])), reverse=True)
                    if not ext and 'po kusech' in pkg.lower():
                        ext = [1]
                    if ext: manual_boxes[mat_key] = ext

            box_dict, weight_dict, dim_dict = {}, {}, {}
            if df_marm_raw is not None:
                df_marm_raw['Match_Key'] = df_marm_raw['Material'].apply(get_match_key)
                df_boxes = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(['AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO'])].copy()
                df_boxes['Numerator'] = pd.to_numeric(df_boxes['Numerator'], errors='coerce').fillna(0)
                box_dict = df_boxes.groupby('Match_Key')['Numerator'].apply(lambda g: sorted([int(x) for x in g if x > 1], reverse=True)).to_dict()

                df_st = df_marm_raw[df_marm_raw['Alternative Unit of Measure'].isin(['ST', 'PCE', 'KS'])].copy()
                df_st['Gross Weight'] = pd.to_numeric(df_st['Gross Weight'], errors='coerce').fillna(0)
                df_st['Weight_KG'] = np.where(df_st['Unit of Weight'].astype(str).str.upper() == 'G', df_st['Gross Weight']/1000.0, df_st['Gross Weight'])
                weight_dict = df_st.groupby('Match_Key')['Weight_KG'].first().to_dict()

                def to_cm(val, unit):
                    try:
                        v, u = float(val), str(unit).upper().strip()
                        if u == 'MM': return v / 10.0
                        if u == 'M': return v * 100.0
                        return v 
                    except: return 0.0

                for dim in ['Length', 'Width', 'Height']:
                    df_st[dim[0]] = df_st.apply(lambda r: to_cm(r[dim], r['Unit of Dimension']), axis=1)
                dim_dict = df_st.set_index('Match_Key')[['L', 'W', 'H']].max(axis=1).to_dict()

            df_pick['Box_Sizes_List'] = df_pick['Match_Key'].apply(lambda m: manual_boxes.get(m, box_dict.get(m, [])))
            df_pick['Piece_Weight_KG'] = df_pick['Match_Key'].map(weight_dict).fillna(0.0)
            df_pick['Piece_Max_Dim_CM'] = df_pick['Match_Key'].map(dim_dict).fillna(0.0)

            if df_vekp_raw is not None:
                df_vekp_raw['Generated delivery'] = df_vekp_raw['Generated delivery'].astype(str).str.strip()
                
            if df_cats_raw is not None:
                df_cats_raw['Lieferung'] = df_cats_raw['Lieferung'].astype(str).str.strip()
                df_cats_raw['Category_Full'] = df_cats_raw['Kategorie'].astype(str).str.strip() + " " + df_cats_raw['Art'].astype(str).str.strip()
                df_cats_raw = df_cats_raw.drop_duplicates('Lieferung')

            st.session_state['last_files_hash'] = current_files_hash
            st.session_state['df_pick_prep'] = df_pick
            st.session_state['queue_count_col'] = queue_count_col
            st.session_state['num_removed_admins'] = num_removed_admins
            st.session_state['manual_boxes'] = manual_boxes
            st.session_state['weight_dict'] = weight_dict
            st.session_state['dim_dict'] = dim_dict
            st.session_state['box_dict'] = box_dict
            st.session_state['df_vekp'] = df_vekp_raw
            st.session_state['df_cats'] = df_cats_raw
            
            progress_bar.progress(100)
            time.sleep(0.3)
            progress_bar.empty()
            status_text.empty()

    else:
        if 'last_files_hash' in st.session_state: del st.session_state['last_files_hash']
        if 'df_pick_prep' in st.session_state: del st.session_state['df_pick_prep']
        if 'df_vekp' in st.session_state: del st.session_state['df_vekp']
        if 'df_cats' in st.session_state: del st.session_state['df_cats']

    # ==========================================
    # --- VÝPOČTY (PROVÁDÍ SE VŽDY PRO ÚPRAVU POSUVNÍKŮ) ---
    # ==========================================
    if 'df_pick_prep' in st.session_state and st.session_state['df_pick_prep'] is not None:
        
        df_pick = st.session_state['df_pick_prep'].copy()
        queue_count_col = st.session_state['queue_count_col']
        num_removed_admins = st.session_state['num_removed_admins']
        manual_boxes = st.session_state['manual_boxes']
        weight_dict = st.session_state['weight_dict']
        dim_dict = st.session_state['dim_dict']
        box_dict = st.session_state['box_dict']
        df_vekp = st.session_state.get('df_vekp', None)
        df_cats = st.session_state.get('df_cats', None)

        df_pick['Month'] = pd.to_datetime(df_pick.get('Date', np.nan), errors='coerce').dt.to_period('M').astype(str).replace('NaT', t('unknown'))

        excluded_materials = st.sidebar.multiselect(t('exclude_label'), options=sorted(df_pick['Material'].unique()), default=[])
        if excluded_materials:
            df_pick = df_pick[~df_pick['Material'].isin(excluded_materials)]

        t_total, t_exact, t_miss = fast_compute_moves(
            qty_list=df_pick['Qty'].values, queue_list=df_pick['Queue'].values, su_list=df_pick['Removal of total SU'].values,
            box_list=df_pick['Box_Sizes_List'].values, w_list=df_pick['Piece_Weight_KG'].values, d_list=df_pick['Piece_Max_Dim_CM'].values,
            v_lim=limit_vahy, d_lim=limit_rozmeru, h_lim=kusy_na_hmat
        )
        
        df_pick['Pohyby_Rukou'] = t_total
        df_pick['Pohyby_Exact'] = t_exact
        df_pick['Pohyby_Loose_Miss'] = t_miss
        df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

        c_i1, c_i2, c_i3 = st.columns(3)
        if num_removed_admins > 0: c_i1.info(t('info_users').format(num_removed_admins))
        x_c = ((df_pick['Removal of total SU'] == 'X') & (df_pick['Queue'].str.contains('FU', na=False))).sum()
        if x_c > 0: c_i2.warning(t('info_clean').format(x_c))
        if manual_boxes: c_i3.success(t('info_manual').format(len(manual_boxes)))

        tab_dash, tab_pallets, tab_top, tab_billing, tab_audit = st.tabs([t('tab_dashboard'), t('tab_pallets'), t('tab_top'), t('tab_billing'), t('tab_audit')])

        # --- TAB 1: DASHBOARD ---
        with tab_dash:
            tot_mov = df_pick['Pohyby_Rukou'].sum()
            if tot_mov > 0:
                st.subheader(t('sec_ratio'))
                st.write(t('ratio_desc'))
                st.markdown(f"**{t('ratio_moves')}**")
                
                c_r1, c_r2 = st.columns(2)
                c_r1.metric(t('ratio_exact'), f"{(df_pick['Pohyby_Exact'].sum() / tot_mov * 100):.1f} %", f"{df_pick['Pohyby_Exact'].sum():,.0f} {t('audit_phys_moves').lower()}")
                c_r2.metric(t('ratio_miss'), f"{(df_pick['Pohyby_Loose_Miss'].sum() / tot_mov * 100):.1f} %", f"{df_pick['Pohyby_Loose_Miss'].sum():,.0f} {t('audit_phys_moves').lower()}", delta_color="inverse")
                
                with st.expander(t('logic_explain_title')):
                    st.info(t('logic_explain_text'))

            if 'Queue' in df_pick.columns and df_pick['Queue'].notna().any() and df_pick['Queue'].nunique() > 1:
                st.divider()
                st.subheader(t('sec_queue_title'))
                
                months_opts = [t('all_months')] + sorted([m for m in df_pick['Month'].unique() if m != t('unknown')])
                if t('unknown') in df_pick['Month'].unique(): months_opts.append(t('unknown'))
                    
                sel_month = st.selectbox(t('filter_month'), options=months_opts)
                df_q_filter = df_pick[df_pick['Month'] == sel_month] if sel_month != t('all_months') else df_pick.copy()

                if not df_q_filter.empty:
                    queue_agg_raw = df_q_filter.groupby([queue_count_col, 'Queue']).agg(
                        celkem_pohybu=('Pohyby_Rukou', 'sum'), pohyby_exact=('Pohyby_Exact', 'sum'),
                        pohyby_miss=('Pohyby_Loose_Miss', 'sum'), total_qty=('Qty', 'sum'), 
                        num_materials=('Material', 'nunique'), pocet_lokaci=('Source Storage Bin', 'nunique'), 
                        delivery=('Delivery', 'first')
                    ).reset_index()
                    
                    def adjust_queue_name(row):
                        if str(row['Queue']).upper() in ['PI_PL', 'PI_PL_OE']:
                            return row['Queue'] + (' (Single)' if row['num_materials'] == 1 else ' (Mix)')
                        return row['Queue']

                    totals_rows = queue_agg_raw[queue_agg_raw['Queue'].str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
                    totals_rows['Queue'] += ' (Total)'
                    queue_agg_raw['Queue'] = queue_agg_raw.apply(adjust_queue_name, axis=1)
                    queue_agg_final = pd.concat([queue_agg_raw, totals_rows], ignore_index=True)
                    
                    q_sum = queue_agg_final.groupby('Queue').agg(
                        pocet_zakazek=('delivery', 'nunique'), prum_lokaci=('pocet_lokaci', 'mean'),
                        prum_kusu=('total_qty', 'mean'), prum_pohybu=('celkem_pohybu', 'mean'),
                        lokaci_sum=('pocet_lokaci', 'sum'), pohybu_sum=('celkem_pohybu', 'sum'),
                        exact_sum=('pohyby_exact', 'sum'), miss_sum=('pohyby_miss', 'sum')
                    )
                    
                    q_sum['pocet_TO'] = queue_agg_final.groupby('Queue')[queue_count_col].nunique() if queue_count_col == 'Transfer Order Number' else q_sum['pocet_zakazek']
                    
                    q_sum['prum_pohybu_lokace'] = np.where(q_sum['lokaci_sum'] > 0, q_sum['pohybu_sum'] / q_sum['lokaci_sum'], 0)
                    q_sum['prum_exact_lokace'] = np.where(q_sum['lokaci_sum'] > 0, q_sum['exact_sum'] / q_sum['lokaci_sum'], 0)
                    q_sum['prum_miss_lokace'] = np.where(q_sum['lokaci_sum'] > 0, q_sum['miss_sum'] / q_sum['lokaci_sum'], 0)
                    
                    q_sum['pct_exact'] = np.where(q_sum['pohybu_sum'] > 0, (q_sum['exact_sum'] / q_sum['pohybu_sum']) * 100, 0)
                    q_sum['pct_miss'] = np.where(q_sum['pohybu_sum'] > 0, (q_sum['miss_sum'] / q_sum['pohybu_sum']) * 100, 0)
                    
                    q_sum = q_sum.reset_index().sort_values('prum_pohybu_lokace', ascending=False)
                    q_sum['Popis'] = q_sum['Queue'].map(QUEUE_DESC).fillna('')
                    
                    display_q = q_sum[['Queue', 'Popis', 'pocet_TO', 'pocet_zakazek', 'prum_lokaci', 'prum_kusu', 
                                       'prum_pohybu_lokace', 'prum_exact_lokace', 'pct_exact', 'prum_miss_lokace', 'pct_miss']].copy()
                    
                    display_q.columns = [t('q_col_queue'), t('q_col_desc'), t('q_col_to'), t('q_col_orders'), t('q_col_loc'), t('q_col_pcs'), 
                                         t('q_col_mov_loc'), t('q_col_exact_loc'), t('q_pct_exact'), t('q_col_miss_loc'), t('q_pct_miss')]
                    
                    styled_q = display_q.style.format({c: "{:.1f}" for c in display_q.columns if 'Prům' in c or 'Avg' in c or 'Pohyb' in c or 'Loc' in c} | {c: "{:.1f} %" for c in display_q.columns if '%' in c})\
                        .set_properties(subset=[t('q_col_queue'), t('q_col_mov_loc')], **{'font-weight': 'bold', 'color': '#1f77b4', 'background-color': 'rgba(31, 119, 180, 0.05)'})
                    
                    col_qt1, col_qt2 = st.columns([2.5, 1])
                    with col_qt1:
                        st.dataframe(styled_q, use_container_width=True, hide_index=True)
                    with col_qt2:
                        st.bar_chart(q_sum.set_index('Queue')['prum_pohybu_lokace'])

        # --- TAB 2: PALETOVÉ ZAKÁZKY ---
        with tab_pallets:
            st.subheader(t('sec1_title'))
            st.markdown(t('pallets_clean_info'))
            
            allowed_q = ['PI_PL (Mix)', 'PI_PL (Total)', 'PI_PL (Single)', 'PI_PL_OE (Mix)', 'PI_PL_OE (Total)', 'PI_PL_OE (Single)']
            df_pallets_clean = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
            
            if not df_pallets_clean.empty:
                grouped_orders = df_pallets_clean.groupby('Delivery').agg(
                    num_materials=('Material', 'nunique'), 
                    material=('Material', 'first'),
                    certs=('Certificate Number', lambda x: ", ".join(x.dropna().unique().astype(str))) if 'Certificate Number' in df_pallets_clean.columns else ('Material', lambda x: ""),
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
                    filtered_orders['mov_per_loc'] = np.where(filtered_orders['num_positions'] > 0, filtered_orders['celkem_pohybu'] / filtered_orders['num_positions'], 0)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(t('m_orders'), f"{len(filtered_orders):,}".replace(',', ' '))
                    c2.metric(t('m_qty'), f"{filtered_orders['total_qty'].mean():.1f}")
                    c3.metric(t('m_pos'), f"{filtered_orders['num_positions'].mean():.2f}")
                    c4.metric(t('m_mov_loc'), f"{filtered_orders['mov_per_loc'].mean():.1f}")

                    tot_p_pal = filtered_orders['celkem_pohybu'].sum()
                    if tot_p_pal > 0:
                        st.markdown(f"**{t('ratio_moves')}**")
                        c_p1, c_p2 = st.columns(2)
                        c_p1.metric(t('ratio_exact'), f"{(filtered_orders['pohyby_exact'].sum() / tot_p_pal * 100):.1f} %")
                        c_p2.metric(t('ratio_miss'), f"{(filtered_orders['pohyby_miss'].sum() / tot_p_pal * 100):.1f} %", delta_color="inverse")

                    with st.expander(t('exp_detail_title')):
                        display_df = filtered_orders[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer', 'certs']].copy()
                        display_df.columns = [t('col_mat'), t('col_qty'), t('col_mov'), t('col_mov_exact'), t('col_mov_miss'), t('col_wgt'), t('col_max_dim'), t('col_cert')]
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.warning(t('no_orders'))
            else:
                st.warning(t('no_orders'))

        # --- TAB 3: TOP MATERIÁLY ---
        with tab_top:
            st.subheader(t('sec_queue_top_title'))
            q_options = [t('all_queues')] + sorted(df_pick['Queue'].dropna().unique().tolist())
            selected_queue_disp = st.selectbox(t('q_select'), options=q_options)
            
            df_top_filter = df_pick if selected_queue_disp == t('all_queues') else df_pick[df_pick['Queue'] == selected_queue_disp]

            if not df_top_filter.empty:
                agg = df_top_filter.groupby('Material').agg(
                    pocet_picku=('Material', 'count'), 
                    celkove_mnozstvi=('Qty', 'sum'),
                    celkem_pohybu=('Pohyby_Rukou', 'sum'), 
                    pohyby_exact=('Pohyby_Exact', 'sum'),
                    pohyby_miss=('Pohyby_Loose_Miss', 'sum'),
                    celkova_natacena_vaha=('Celkova_Vaha_KG', 'sum')
                ).reset_index()

                agg.rename(columns={
                    'Material': t('col_mat'), 'pocet_picku': t('col_lines'),
                    'celkem_pohybu': t('col_mov'), 'pohyby_exact': t('col_mov_exact'),
                    'pohyby_miss': t('col_mov_miss'), 'celkove_mnozstvi': t('col_qty'), 
                    'celkova_natacena_vaha': t('col_wgt')
                }, inplace=True)

                top_100_df = agg.sort_values(by=t('col_mov'), ascending=False).head(100)[[t('col_mat'), t('col_lines'), t('col_qty'), t('col_wgt'), t('col_mov_exact'), t('col_mov_miss'), t('col_mov')]]

                col_q1, col_q2 = st.columns([1.5, 1])
                with col_q1:
                    st.dataframe(top_100_df.style.format({t('col_wgt'): "{:.1f}"} | {c: "{:.0f}" for c in top_100_df.columns if 'Pohyb' in c or 'Move' in c}), use_container_width=True, hide_index=True)
                with col_q2:
                    st.bar_chart(top_100_df.set_index(t('col_mat'))[t('col_mov')])

            st.divider()
            st.subheader(t('exp_missing_data').replace('🔍 ', ''))
            all_mat_agg = df_pick.groupby('Material').agg(lines=('Material', 'count'), qty=('Qty', 'sum'), miss=('Pohyby_Loose_Miss', 'sum'), mov=('Pohyby_Rukou', 'sum')).reset_index()
            all_mat_agg.columns = [t('col_mat'), t('col_lines'), t('col_qty'), t('col_mov_miss'), t('col_mov')]
            miss_df = all_mat_agg[all_mat_agg[t('col_mov_miss')] > 0].sort_values(by=t('col_mov_miss'), ascending=False).head(100)
            
            if not miss_df.empty:
                st.dataframe(miss_df.style.format({c: "{:.0f}" for c in [t('col_mov_miss'), t('col_mov')]}), use_container_width=True, hide_index=True)
            else:
                st.success("Všechna data o baleních jsou k dispozici, žádné odhady!" if st.session_state.lang == 'cs' else "All packaging data is available, no estimates!")

        # --- TAB 4: ÚČTOVÁNÍ A BALENÍ (VEKP + KATEGORIE ZAKÁZEK) ---
        with tab_billing:
            st.subheader(t('b_title'))
            st.markdown(t('b_desc'))
            
            if df_vekp is not None and not df_vekp.empty:
                vekp_clean = df_vekp.dropna(subset=['Handling Unit', 'Generated delivery']).copy()
                valid_deliveries = df_pick['Delivery'].dropna().unique()
                vekp_filtered = vekp_clean[vekp_clean['Generated delivery'].isin(valid_deliveries)]
                
                total_deliveries = len(valid_deliveries)
                total_hus = vekp_filtered['Handling Unit'].nunique()
                total_pick_moves = df_pick['Pohyby_Rukou'].sum()
                total_tos = df_pick[queue_count_col].nunique()
                
                moves_per_hu = total_pick_moves / total_hus if total_hus > 0 else 0
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric(t('b_del_count'), f"{total_deliveries:,}".replace(',', ' '))
                c2.metric(t('b_to_count'), f"{total_tos:,}".replace(',', ' '))
                c3.metric(t('b_hu_count'), f"{total_hus:,}".replace(',', ' '))
                c4.metric(t('b_mov_per_hu'), f"{moves_per_hu:.1f}")
                
                # Propojení s kategoriemi (deliveries.xlsx)
                pick_agg = df_pick.groupby('Delivery').agg(
                    pocet_to=(queue_count_col, 'nunique'),
                    pohyby_celkem=('Pohyby_Rukou', 'sum')
                ).reset_index()
                
                hu_agg = vekp_filtered.groupby('Generated delivery').agg(
                    pocet_hu=('Handling Unit', 'nunique')
                ).reset_index()
                
                billing_df = pd.merge(pick_agg, hu_agg, left_on='Delivery', right_on='Generated delivery', how='left')
                billing_df['pocet_hu'] = billing_df['pocet_hu'].fillna(0).astype(int)
                
                if df_cats is not None:
                    billing_df = pd.merge(billing_df, df_cats[['Lieferung', 'Category_Full']], left_on='Delivery', right_on='Lieferung', how='left')
                    billing_df['Category_Full'] = billing_df['Category_Full'].fillna('Bez kategorie' if st.session_state.lang == 'cs' else 'Uncategorized')
                else:
                    billing_df['Category_Full'] = 'N/A'
                
                billing_df['pohybu_na_hu'] = np.where(billing_df['pocet_hu'] > 0, billing_df['pohyby_celkem'] / billing_df['pocet_hu'], 0)
                
                # --- NOVÁ SOUHRNNÁ TABULKA DLE KATEGORIÍ ---
                st.divider()
                st.subheader(t('b_cat_title'))
                
                cat_summary = billing_df.groupby('Category_Full').agg(
                    pocet_deliveries=('Delivery', 'nunique'),
                    pocet_to=('pocet_to', 'sum'),
                    pohyby_celkem=('pohyby_celkem', 'sum'),
                    pocet_hu=('pocet_hu', 'sum')
                ).reset_index()
                cat_summary['pohybu_na_hu'] = np.where(cat_summary['pocet_hu'] > 0, cat_summary['pohyby_celkem'] / cat_summary['pocet_hu'], 0)
                cat_summary = cat_summary.sort_values('pohybu_na_hu', ascending=False)
                
                cat_disp = cat_summary.copy()
                cat_disp.columns = [t('b_table_cat'), t('b_del_count'), t('b_table_to'), t('b_table_mov'), t('b_table_hu'), t('b_table_mph')]
                
                styled_cat = cat_disp.style.format({t('b_table_mph'): "{:.1f}"})\
                    .set_properties(subset=[t('b_table_cat'), t('b_table_mph')], **{'font-weight': 'bold', 'color': '#d62728', 'background-color': 'rgba(214, 39, 40, 0.05)'})
                
                col_bc1, col_bc2 = st.columns([2, 1])
                with col_bc1:
                    st.dataframe(styled_cat, use_container_width=True, hide_index=True)
                with col_bc2:
                    st.bar_chart(cat_summary.set_index('Category_Full')['pohybu_na_hu'])

                # --- DETAILNÍ TABULKA ---
                st.divider()
                st.markdown("**Detailní rozpad podle Delivery:**" if st.session_state.lang == 'cs' else "**Detailed breakdown by Delivery:**")
                
                det_df = billing_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'pohybu_na_hu']].sort_values('pohyby_celkem', ascending=False)
                det_df.columns = [t('b_table_del'), t('b_table_cat'), t('b_table_to'), t('b_table_mov'), t('b_table_hu'), t('b_table_mph')]
                st.dataframe(det_df.style.format({t('b_table_mph'): "{:.1f}"}), use_container_width=True, hide_index=True)
            else:
                st.warning(t('b_missing_vekp'))

        # --- TAB 5: NÁSTROJE A AUDIT ---
        with tab_audit:
            col_au1, col_au2 = st.columns([3, 2])
            with col_au1:
                st.subheader(t('audit_title'))
                
                if 'audit_samples' not in st.session_state or st.session_state.get('last_audit_hash') != st.session_state.get('last_files_hash'):
                    audit_samples = {}
                    valid_queues = sorted([q for q in df_pick['Queue'].dropna().unique() if q != 'N/A'])
                    for q in valid_queues:
                        q_data = df_pick[df_pick['Queue'] == q]
                        unique_tos = q_data[queue_count_col].dropna().unique()
                        if len(unique_tos) > 0:
                            audit_samples[q] = np.random.choice(unique_tos, min(5, len(unique_tos)), replace=False)
                    st.session_state['audit_samples'] = audit_samples
                    st.session_state['last_audit_hash'] = st.session_state.get('last_files_hash')
                
                if st.button(t('audit_gen_btn'), type="primary"):
                    audit_samples = {}
                    valid_queues = sorted([q for q in df_pick['Queue'].dropna().unique() if q != 'N/A'])
                    for q in valid_queues:
                        q_data = df_pick[df_pick['Queue'] == q]
                        unique_tos = q_data[queue_count_col].dropna().unique()
                        if len(unique_tos) > 0:
                            audit_samples[q] = np.random.choice(unique_tos, min(5, len(unique_tos)), replace=False)
                    st.session_state['audit_samples'] = audit_samples

                if 'audit_samples' in st.session_state:
                    for q, tos in st.session_state['audit_samples'].items():
                        with st.expander(f"📁 Queue: {q} ({len(tos)} TOs)", expanded=False):
                            for i, r_to in enumerate(tos, 1):
                                st.markdown(f"#### {i}. TO: **`{r_to}`**")
                                to_data = df_pick[df_pick[queue_count_col] == r_to]
                                
                                for _, row in to_data.iterrows():
                                    mat = row['Material']
                                    qty = row['Qty']
                                    boxes = row.get('Box_Sizes_List', [])
                                    w = row.get('Piece_Weight_KG', 0)
                                    d = row.get('Piece_Max_Dim_CM', 0)
                                    su = row.get('Removal of total SU', '')
                                    src_bin = row.get('Source Storage Bin', 'Unknown')
                                    queue_str = str(row.get('Queue', '')).upper()
                                    
                                    boxes_str = str(boxes) if boxes else f"*{t('box_missing')}*"
                                    st.markdown(f"**Mat:** `{mat}` | **Bin:** `{src_bin}` | **Qty:** {qty} | **Box:** {boxes_str} | **Wgt:** {w:.3f} kg | **Dim:** {d:.1f} cm")
                                    
                                    if su == 'X' and queue_str in ['PI_PL_FU', 'PI_PL_FUOE']:
                                        st.info(t('audit_su_x').format(queue_str))
                                    else:
                                        if su == 'X':
                                            st.caption(t('audit_su_ign').format(queue_str))
                                        
                                        zbytek = qty
                                        if boxes:
                                            for b in boxes:
                                                if b > 1 and zbytek >= b:
                                                    m = zbytek // b
                                                    st.write(t('audit_box').format(int(m), b))
                                                    zbytek %= b
                                                    
                                        if zbytek > 0:
                                            if w >= limit_vahy or d >= limit_rozmeru:
                                                st.warning(t('audit_lim').format(zbytek, zbytek))
                                            else:
                                                hmaty = int(np.ceil(zbytek / kusy_na_hmat))
                                                st.success(t('audit_grab').format(zbytek, hmaty))
                                    
                                    st.markdown(f"> **{t('audit_phys_moves')}: `{row.get('Pohyby_Rukou', 0)}`**")
                                    st.write("---")

            with col_au2:
                st.subheader(t('sec3_title'))
                mat_search = st.selectbox(t('search_label'), options=[""] + sorted(df_pick['Material'].unique().tolist()))
                
                if mat_search:
                    search_key = get_match_key(mat_search)
                    if search_key in manual_boxes:
                        st.success(t('ovr_found').format(manual_boxes[search_key]))
                    else:
                        st.info(t('ovr_not_found'))
                    
                    c_info1, c_info2 = st.columns(2)
                    c_info1.metric(t('marm_weight'), f"{weight_dict.get(search_key, 0):.3f} kg")
                    c_info2.metric(t('marm_dim'), f"{dim_dict.get(search_key, 0):.1f} cm")

            # ------------------------------------------
            # EXPORT DO EXCELU
            # ------------------------------------------
            st.divider()
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                pd.DataFrame({
                    "Parameter": ["Weight Limit", "Dim Limit", "Grab limit", "Admins Excluded"], 
                    "Value": [f"{limit_vahy} kg", f"{limit_rozmeru} cm", f"{kusy_na_hmat} pcs", num_removed_admins]
                }).to_excel(writer, index=False, sheet_name='Settings')
                
                if 'display_q' in locals():
                    display_q.to_excel(writer, index=False, sheet_name='Queue_Analysis')
                    
                if 'filtered_orders' in locals() and not filtered_orders.empty:
                    ex_df = filtered_orders[['material', 'total_qty', 'celkem_pohybu', 'pohyby_exact', 'pohyby_miss', 'vaha_zakazky', 'max_rozmer', 'certs']].copy()
                    ex_df.columns = [t('col_mat'), t('col_qty'), t('col_mov'), t('col_mov_exact'), t('col_mov_miss'), t('col_wgt'), t('col_max_dim'), t('col_cert')]
                    ex_df.to_excel(writer, index=True, sheet_name='Single_Mat_Orders')
                    
                df_pick.groupby('Material').agg(Moves=('Pohyby_Rukou', 'sum'), Qty=('Qty', 'sum')).reset_index().to_excel(writer, index=False, sheet_name='Raw_Data_Totals')
                
            st.download_button(
                label=t('btn_download'), 
                data=buffer.getvalue(), 
                file_name=f"Warehouse_Analysis_{time.strftime('%Y%m%d')}.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                type="primary"
            )

if __name__ == "__main__":
    main()
