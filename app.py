import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import time

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

BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

TEXTS = {
    'cs': {
        'switch_lang': "🇬🇧 Switch to English",
        'title': "📦 Analýza pickování",
        'desc': "Nástroj pro modelování fyzické zátěže pickování",
        'upload_title': "📁 Nahrání vstupních dat (Klikněte pro sbalení/rozbalení)",
        'upload_help': "Nahrajte Pick report, MARM report, TO details (Queue), VEKP (Balení), Kategorie zakázek (Deliveries) a volitelně ruční ověření.",
        'file_status_title': "📋 Stav detekce souborů:",
        'file_pick': "Pick report",
        'file_marm': "MARM",
        'file_queue': "Queue (TO)",
        'file_vekp': "VEKP",
        'file_cats': "Deliveries",
        'file_manual': "Ruční ověření",
        'info_users': "💡 Vyloučeno **{} systémových řádků** (UIDJ5089, UIH25501).",
        'info_clean': "💡 Započítán 1 pohyb pro **{} řádků** 'X' (Platí POUZE pro Queue: PI_PL_FU, PI_PL_FUOE).",
        'info_manual': "✅ Načteno ruční ověření pro **{} unikátních materiálů**.",
        'sidebar_title': "⚙️ Konfigurace algoritmů",
        'weight_label': "Hranice pro nošení po 1 ks (kg)",
        'dim_label': "Hranice rozměru pro 1 ks (cm)",
        'hmat_label': "Max ks lehkých dílů do hrsti",
        'exclude_label': "Vyloučit materiály z výpočtů:",
        'filter_global_title': "📅 Období dat",
        'filter_all': "Celé období",
        'filter_month': "Podle měsíce",
        'filter_range': "Vlastní rozsah",
        'filter_month_sel': "Vyberte měsíc:",
        'filter_range_sel': "Od - Do:",
        'sec_ratio': "🎯 Spolehlivost dat a zdroj výpočtů",
        'ratio_desc': "Z jakých podkladů aplikace vycházela (Ukazatel kvality dat ze SAPu):",
        'logic_explain_title': "ℹ️ Podrobná metodika: Jak aplikace vypočítává výsledná data?",
        'logic_explain_text': """Tento analytický model detailně simuluje fyzickou zátěž skladníka podle následujícího postupu:

**1. Vstupní soubory:**
* **Pick report:** Hlavní soubor se seznamem vychystaných položek.
* **MARM report:** Kmenová data o materiálech ze SAPu (jednotky AEK, CAR, ASK, BLO...).
* **TO details (Queue):** Dodává informace o frontě a datu potvrzení úkolů.
* **VEKP:** Dodává informace o zabalených jednotkách (HU) pro korelaci s účtováním zákazníkovi.
* **Deliveries:** Mapuje zakázky do kategorií (N Sortenrein, N Misch atd.).
* **Ruční ověření (volitelně):** Excel pro ruční přepis velikosti balení (formát K-XXks).

**2. Dekompozice na celá balení (Krabice)**
Systém matematicky rozdělí množství na plné krabice od největší. Co krabice, to **1 fyzický pohyb**.

**3. Analýza volných kusů (Limity)**
Zbylé rozbalené kusy podléhají kontrole ergonomických limitů. Každý těžký/velký kus = **1 pohyb**, lehké kusy se berou do hrsti.

**4. Bezpečnostní odhady (Chybějící data)**
Pokud v SAPu ani ručním ověření chybí data o balení, systém aplikuje bezpečnostní odhad na základě váhy a rozměru.""",
        'ratio_moves': "Podíl z celkového počtu POHYBŮ:",
        'ratio_exact': "Přesně (Krabice / Palety / Volné)",
        'ratio_miss': "Odhady (Chybí balení)",
        'exp_missing_data': "Materiály s chybějícími daty o balení (Žebříček odhadů)",
        'sec_queue_title': "📊 Průměrná náročnost dle typu pickování (Queue)",
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
        'tab_fu': "🏭 Celé palety (FU)",
        'tab_top': "🏆 TOP Materiály",
        'tab_billing': "💰 Účtování a balení (VEKP)",
        'tab_audit': "🔍 Nástroje & Audit",
        'b_title': "💰 Korelace mezi Pickováním a Účtováním",
        'b_desc': "Zákazník platí podle počtu výsledných balících jednotek (HU). Zde vidíte náročnost vytvoření těchto zpoplatněných jednotek napříč fakturačními kategoriemi.",
        'b_del_count': "Počet Deliveries",
        'b_to_count': "Pickovacích TO celkem",
        'b_hu_count': "Celkem balících HU (VEKP)",
        'b_mov_per_hu': "Pohybů na 1 zabalenou HU",
        'b_cat_title': "📊 Souhrn nákladnosti podle Kategorií (Type of HU)",
        'b_col_type': "Kategorie (Typ HU)",
        'b_col_hu': "Počet HU",
        'b_col_loc_hu': "Prům. lokací na HU",
        'b_col_mov_loc': "Prům. pohybů / lok.",
        'b_col_pct_ex': "% Přesně",
        'b_col_pct_ms': "% Odhad",
        'b_table_del': "Delivery",
        'b_table_cat': "Kategorie",
        'b_table_to': "Počet TO",
        'b_table_mov': "Pohyby celkem",
        'b_table_hu': "Počet HU",
        'b_table_mph': "Pohybů na 1 HU",
        'b_missing_vekp': "⚠️ Pro zobrazení těchto dat nahrajte soubor VEKP.",
        'b_imbalance_orders': "Zakázky s nerovnováhou",
        'b_of_all': "ze všech",
        'b_unpaid_to': "Nepokrytá TO",
        'b_unpaid_to_help': "TO bez odpovídající HU",
        'b_imbalance_title': "⚠️ Zakázky kde pickujete víc, než dostanete zaplaceno (TO > HU)",
        'b_imbalance_desc': "Toto jsou zakázky, kde počet pickovacích úkolů (TO) převyšuje počet fakturovaných zásilek (HU). Zákazník za tuto extra práci neplatí.",
        'b_col_mov_hu': "Pohybů / HU",
        'b_col_wgt_hu': "Kg / HU",
        'b_col_wgt_total': "Celk. hmotnost (kg)",
        'b_col_carton': "Typ krabice",
        'b_col_locs': "Lokací",
        'b_col_deliveries': "Deliveries",
        'b_col_unpaid_to': "Nepokr. TO",
        'b_imb_avg_mov_hu': "Prům. pohybů / HU",
        'b_imb_overall_avg': "celkový průměr",
        'b_imb_total_moves': "Pohybů celkem",
        'b_imb_total_weight': "Celk. hmotnost",
        'b_imb_avg_loc': "Prům. lokací / HU",
        'b_no_imbalance': "Žádné zakázky s nerovnováhou TO > HU!",
        'col_lines': "Řádky",
        'btn_download': "📥 Stáhnout kompletní report (Excel)",
        'err_pick': "❌ Chyba: Pick report nebyl nalezen. Zkontrolujte, zda soubor obsahuje sloupce 'Delivery' a 'Act.qty (dest)'.",
        'no_orders': "Nenalezeny žádné zakázky pro zobrazení.",
        'audit_su_x': "➡️ Celá paleta (X) ve frontě {}. -> **1 pohyb.**",
        'audit_su_ign': "*(Značka 'X' ignorována — fronta {} nevozí celé palety)*",
        'audit_box': "➡️ Odebráno **{}x Krabice** (po {} ks)",
        'audit_lim': "➡️ Zbylých {} ks překračuje limit ({}) → **{} pohybů** (po 1 ks)",
        'audit_grab': "➡️ Zbylých {} ks do hrsti → **{} pohybů** (po {} ks)",
        'ovr_found': "✅ Ruční ověření nalezeno: balení **{} ks**.",
        'ovr_not_found': "ℹ️ Žádné ruční ověření.",
        'marm_weight': "Váha / ks (MARM)",
        'marm_dim': "Max. rozměr (MARM)",
        'marm_boxes': "Krabicové jednotky (MARM)",
        'box_missing': "Chybí",
        'uncategorized': "Bez kategorie",
        'all_data_exact': "✅ Všechna data o baleních jsou k dispozici — žádné odhady!",
        'detail_breakdown': "**Detailní rozpad podle Delivery:**",
        'box_sizes': "Krabice (ks)",
        'source_pick_date': "Datum (z Pick)",
        'source_to_date': "Datum (z TO)",
        'loading': "🔄 Načítám soubory...",
        'processing': "⚙️ Zpracovávám master data...",
        'fu_title': "Analýza front PI_PL_FU a PI_PL_FUOE",
        'fu_desc': "Rozpad picků podle typu skladovací jednotky (Storage Unit Type).",
        'fu_col_cat': "Typ balení",
        'fu_col_su': "Kód jednotky",
        'fu_col_lines': "Počet picků (Řádky)",
        'fu_col_to': "Počet TO",
        'fu_col_qty': "Kusů celkem",
        'b_aus_title': "Analýza zásilkových dat (Auswertung)",
        'b_aus_desc': "Data ze zákazníkova souboru — kategorizace, typy HU a váhy počítány stejnou logikou jako v Excelu.",
        'b_aus_upload_hint': "Pro tuto sekci nahrajte zákazníkův soubor Auswertung_Outbound_HWL.xlsx (nebo soubor s auswertung v názvu).",
        'b_aus_no_vekp': "Soubor neobsahuje list VEKP/VEPO — nelze vypočítat typy HU.",
        'b_aus_kat_title': "Kategorie zásilek (E / N / O / OE)",
        'b_aus_kat_desc': "Kategorie = kombinace Order Type (Versandstelle + T031) + KEP příznak dopravce (SDSHP_AM2).",
        'b_aus_kat': "Kategorie",
        'b_aus_popis': "Popis",
        'b_aus_lief': "Lieferungen",
        'b_aus_hu': "HU celkem",
        'b_aus_packst': "Prům. HU / zásilka",
        'b_aus_avg_vaha': "Prům. váha HU (kg)",
        'b_aus_avg_ladung': "Prům. obsah HU (kg)",
        'b_aus_vaha_total': "Váha celkem (kg)",
        'b_aus_total_lief': "Zásilky celkem",
        'b_aus_total_hu': "HU celkem",
        'b_aus_avg_hu_lief': "Prům. HU / zásilka",
        'b_aus_total_vaha': "Celk. hmotnost (kg)",
        'b_aus_pct_kep': "Zásilek přes KEP",
        'b_aus_art_title': "Typy HU (Sortenrein / Misch / Vollpalette)",
        'b_aus_art_desc': "Vollpalette = Přímé pohyby celých palet zaznamenané v tabulce T023. Sortenrein = 1 materiál / 1 zakázka. Misch = víc materiálů nebo zakázek.",
        'b_aus_carton_title': "Typy kartonů (Packmittel) — rozměry a váhy",
        'b_aus_carton': "Typ krabice",
        'b_aus_pocet': "Počet HU",
        'b_aus_delka': "Délka (cm)",
        'b_aus_sirka': "Šířka (cm)",
        'b_aus_vyska': "Výška (cm)",
        'b_aus_detail_exp': "Detailní tabulka zásilek (rozbalit)",
        'b_aus_sped_title': "Dopravci (Spediteur) — KEP / non-KEP",
        'b_aus_kep_count': "KEP dopravci",
        'b_aus_nonkep_count': "Non-KEP dopravci",
        'b_aus_sped': "Spediteur",
        'b_aus_kep_flag': "KEP",
        'b_aus_max_gew': "Max. hmotnost (kg)",
        'b_aus_ladezeit': "Čas nakládky",
        'b_aus_zone': "Zóna přípravy",
        'b_aus_voll_title': "Vollpalette — přímé pohyby (T023)",
        'b_aus_voll_count': "Pohybů celých palet",
        'audit_b_title': "💰 Ověření korelací (Pick vs. VEKP)",
        'audit_b_sel': "Zadejte nebo vyberte Delivery pro ověření:",
        'audit_b_pick_det': "**Detail pickování (Kusy a Pohyby):**",
        'audit_b_vekp_det': "**Detail balení z VEKP (Seznam HU):**",
        'audit_b_no_vekp': "⚠️ Pro tuto zakázku nebyly ve VEKP nalezeny žádné HU.",
    },

    'en': {
        'switch_lang': "🇨🇿 Přepnout do češtiny",
        'title': "📦 Picking Analysis",
        'desc': "Tool for modeling physical picking workload.",
        'upload_title': "📁 Upload Input Data (Click to expand/collapse)",
        'upload_help': "Upload Pick report, MARM report, TO details (Queue), VEKP (Packing), Deliveries Categories, and optional Manual Override.",
        'file_status_title': "📋 File Detection Status:",
        'file_pick': "Pick report",
        'file_marm': "MARM",
        'file_queue': "Queue (TO)",
        'file_vekp': "VEKP",
        'file_cats': "Deliveries",
        'file_manual': "Manual Override",
        'info_users': "💡 Excluded **{} system lines** (UIDJ5089, UIH25501).",
        'info_clean': "💡 1 move counted for **{} lines** with 'X' (Only for PI_PL_FU, PI_PL_FUOE).",
        'info_manual': "✅ Loaded manual packaging for **{} unique materials**.",
        'sidebar_title': "⚙️ Algorithm Configuration",
        'weight_label': "Weight limit for 1-by-1 pick (kg)",
        'dim_label': "Dimension limit for 1-by-1 (cm)",
        'hmat_label': "Max pieces per grab",
        'exclude_label': "Exclude materials:",
        'filter_global_title': "📅 Date Range",
        'filter_all': "All time",
        'filter_month': "By month",
        'filter_range': "Custom range",
        'filter_month_sel': "Select month:",
        'filter_range_sel': "From - To:",
        'sec_ratio': "🎯 Data Reliability & Source",
        'ratio_desc': "Data foundation (SAP Data Quality indicator):",
        'logic_explain_title': "ℹ️ Detailed Methodology: How does the app calculate results?",
        'logic_explain_text': """This analytical model meticulously simulates the picker's physical workload:

**1. Input Files:**
* **Pick report:** Main file with picked items.
* **MARM report:** SAP master data (units AEK, CAR, ASK, BLO...).
* **TO details (Queue):** Provides Queue and confirmation dates.
* **VEKP:** Packed Handling Units (HUs) for billing correlation.
* **Deliveries:** Maps deliveries to billing categories.
* **Manual Override (optional):** Excel for manual packaging sizes (K-XXpcs format).

**2. Decomposition into Full Boxes**
Quantities are split into full boxes from largest first. Each box = **1 physical move**.

**3. Loose Pieces Analysis**
Remaining pieces are checked against ergonomic limits. Heavy/large = **1 move each**, light pieces are grabbed together.

**4. Safety Estimates (Missing Data)**
If SAP and manual override both lack packaging data, a safety estimate is applied.""",
        'ratio_moves': "Share of total MOVEMENTS:",
        'ratio_exact': "Exact (Boxes / Pallets / Loose)",
        'ratio_miss': "Estimates (Missing packaging)",
        'exp_missing_data': "Materials with missing box data (Estimates leaderboard)",
        'sec_queue_title': "📊 Average Workload by Queue",
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
        'sec_queue_top_title': "🏆 TOP 100 Materials by Queue",
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
        'search_label': "Check specific material:",
        'tab_dashboard': "📊 Dashboard & Queue",
        'tab_pallets': "📦 Pallet Orders",
        'tab_fu': "🏭 Full Pallets (FU)",
        'tab_top': "🏆 TOP Materials",
        'tab_billing': "💰 Billing & Packing (VEKP)",
        'tab_audit': "🔍 Tools & Audit",
        'b_title': "💰 Correlation Between Picking and Billing",
        'b_desc': "The customer pays based on packed Handling Units (HUs). Here you see the effort to create these billed units across categories.",
        'b_del_count': "Delivery Count",
        'b_to_count': "Total TOs Picked",
        'b_hu_count': "Total Packed HUs (VEKP)",
        'b_mov_per_hu': "Moves per Packed HU",
        'b_cat_title': "📊 Workload Summary by Categories (Type of HU)",
        'b_col_type': "Type of HU",
        'b_col_hu': "Total HUs",
        'b_col_loc_hu': "Avg Locs per HU",
        'b_col_mov_loc': "Avg Moves / Loc",
        'b_col_pct_ex': "% Exact",
        'b_col_pct_ms': "% Estimate",
        'b_table_del': "Delivery",
        'b_table_cat': "Category",
        'b_table_to': "TO Count",
        'b_table_mov': "Total Moves",
        'b_table_hu': "HU Count",
        'b_table_mph': "Moves per HU",
        'b_missing_vekp': "⚠️ Please upload the VEKP file to display billing data.",
        'b_imbalance_orders': "Imbalanced Orders",
        'b_of_all': "of all",
        'b_unpaid_to': "Unpaid TOs",
        'b_unpaid_to_help': "TOs without matching HU",
        'b_imbalance_title': "⚠️ Orders where you pick more than you get paid for (TO > HU)",
        'b_imbalance_desc': "These are orders where the number of picking tasks (TOs) exceeds the number of billed shipments (HUs). The customer does not pay for this extra work.",
        'b_col_mov_hu': "Moves / HU",
        'b_col_wgt_hu': "Kg / HU",
        'b_col_wgt_total': "Total Weight (kg)",
        'b_col_carton': "Carton Type",
        'b_col_locs': "Locations",
        'b_col_deliveries': "Deliveries",
        'b_col_unpaid_to': "Unpaid TOs",
        'b_imb_avg_mov_hu': "Avg Moves / HU",
        'b_imb_overall_avg': "overall avg",
        'b_imb_total_moves': "Total Moves",
        'b_imb_total_weight': "Total Weight",
        'b_imb_avg_loc': "Avg Locs / HU",
        'b_no_imbalance': "No orders with TO > HU imbalance found!",
        'col_lines': "Lines",
        'btn_download': "📥 Download Comprehensive Report (Excel)",
        'err_pick': "❌ Error: Pick report not found. Make sure the file contains 'Delivery' and 'Act.qty (dest)' columns.",
        'no_orders': "No orders found.",
        'audit_su_x': "➡️ Full unit (X) in queue {}. -> **1 move.**",
        'audit_su_ign': "*(Ignored 'X' marker — queue {} is not a Full Pallet queue)*",
        'audit_box': "➡️ **{}x Box** (of {} pcs each)",
        'audit_lim': "➡️ Remaining {} pcs over limit ({}) → **{} moves** (1 by 1)",
        'audit_grab': "➡️ Remaining {} pcs grabbed → **{} moves** ({} pcs/grab)",
        'ovr_found': "✅ Manual override found: packaging of **{} pcs**.",
        'ovr_not_found': "ℹ️ No manual override found.",
        'marm_weight': "Weight / pc (MARM)",
        'marm_dim': "Max Dim (MARM)",
        'marm_boxes': "Box units (MARM)",
        'box_missing': "Missing",
        'uncategorized': "Uncategorized",
        'all_data_exact': "✅ All packaging data available — no estimates!",
        'detail_breakdown': "**Detailed breakdown by Delivery:**",
        'box_sizes': "Box sizes (pcs)",
        'source_pick_date': "Date (from Pick)",
        'source_to_date': "Date (from TO)",
        'loading': "🔄 Loading files...",
        'processing': "⚙️ Processing master data...",
        'fu_title': "Analysis of PI_PL_FU and PI_PL_FUOE",
        'fu_desc': "Breakdown of picks by Storage Unit Type.",
        'fu_col_cat': "Packaging Type",
        'fu_col_su': "SU Code",
        'fu_col_lines': "Pick Lines",
        'fu_col_to': "TO Count",
        'fu_col_qty': "Total Pieces",
        'b_aus_title': "Shipment Data Analysis (Auswertung)",
        'b_aus_desc': "Data from customer file — categorization, HU types and weights calculated using the same logic as the Excel file.",
        'b_aus_upload_hint': "For this section upload the customer file Auswertung_Outbound_HWL.xlsx (or any file with auswertung in the name).",
        'b_aus_no_vekp': "File does not contain VEKP/VEPO sheet — cannot calculate HU types.",
        'b_aus_kat_title': "Shipment Categories (E / N / O / OE)",
        'b_aus_kat_desc': "Category = Order Type (Versandstelle + T031) + KEP carrier flag (SDSHP_AM2).",
        'b_aus_kat': "Category",
        'b_aus_popis': "Description",
        'b_aus_lief': "Deliveries",
        'b_aus_hu': "Total HUs",
        'b_aus_packst': "Avg HU / delivery",
        'b_aus_avg_vaha': "Avg HU weight (kg)",
        'b_aus_avg_ladung': "Avg HU content (kg)",
        'b_aus_vaha_total': "Total weight (kg)",
        'b_aus_total_lief': "Total deliveries",
        'b_aus_total_hu': "Total HUs",
        'b_aus_avg_hu_lief': "Avg HU / delivery",
        'b_aus_pct_kep': "Via KEP carrier",
        'b_aus_art_title': "HU Types (Sortenrein / Misch / Vollpalette)",
        'b_aus_art_desc': "Vollpalette = Direct movements of full pallets as recorded in T023 table. Sortenrein = 1 material / 1 order. Misch = multiple materials or orders.",
        'b_aus_carton_title': "Carton Types (Packmittel) — dimensions and weights",
        'b_aus_carton': "Carton type",
        'b_aus_pocet': "HU count",
        'b_aus_delka': "Length (cm)",
        'b_aus_sirka': "Width (cm)",
        'b_aus_vyska': "Height (cm)",
        'b_aus_detail_exp': "Detailed delivery table (expand)",
        'b_aus_sped_title': "Carriers (Spediteur) — KEP / non-KEP",
        'b_aus_kep_count': "KEP carriers",
        'b_aus_nonkep_count': "Non-KEP carriers",
        'b_aus_sped': "Spediteur",
        'b_aus_kep_flag': "KEP",
        'b_aus_max_gew': "Max weight (kg)",
        'b_aus_ladezeit': "Loading time",
        'b_aus_zone': "Staging zone",
        'b_aus_voll_title': "Vollpalette — direct movements (T023)",
        'b_aus_voll_count': "Full pallet movements",
        'audit_b_title': "💰 Billing Correlation Audit (Pick vs. VEKP)",
        'audit_b_sel': "Select Delivery to audit:",
        'audit_b_pick_det': "**Picking Detail (Qty & Moves):**",
        'audit_b_vekp_det': "**Packing Detail from VEKP (HU List):**",
        'audit_b_no_vekp': "⚠️ No HUs found in VEKP for this delivery.",
    }
}

# ==========================================
# 3. POMOCNÉ FUNKCE
# ==========================================

def t(key):
    return TEXTS[st.session_state.lang][key]


def get_match_key_vectorized(series):
    s = series.astype(str).str.strip().str.upper()
    mask_decimal = s.str.match(r'^\d+\.\d+$')
    s = s.copy()
    s[mask_decimal] = s[mask_decimal].str.rstrip('0').str.rstrip('.')
    mask_numeric = s.str.match(r'^0+\d+$')
    s[mask_numeric] = s[mask_numeric].str.lstrip('0')
    return s


def get_match_key(val):
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit():
        v = v.rstrip('0').rstrip('.')
    if v.isdigit():
        v = v.lstrip('0') or '0'
    return v


def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list,
                       v_lim, d_lim, h_lim):
    res_total, res_exact, res_miss = [], [], []

    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list,
                                        box_list, w_list, d_list):
        if qty <= 0:
            res_total.append(0); res_exact.append(0); res_miss.append(0)
            continue

        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1); res_exact.append(1); res_miss.append(0)
            continue

        if not isinstance(boxes, list):
            boxes = []

        data_known = len(boxes) > 0
        real_boxes = [b for b in boxes if b > 1]

        pb = pok = pmiss = 0
        zbytek = qty

        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b)
                pb += m
                zbytek = zbytek % b

        if zbytek > 0:
            over_limit = (w >= v_lim) or (d >= d_lim)
            if over_limit:
                p = int(zbytek)
            else:
                p = int(np.ceil(zbytek / h_lim))

            if data_known:
                pok += p
            else:
                pmiss += p

        res_total.append(pb + pok + pmiss)
        res_exact.append(pb + pok)
        res_miss.append(pmiss)

    return res_total, res_exact, res_miss


# ==========================================
# 4. HLAVNÍ APLIKACE
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
    limit_vahy = st.sidebar.number_input(t('weight_label'), min_value=0.1, max_value=20.0,
                                          value=2.0, step=0.5)
    limit_rozmeru = st.sidebar.number_input(t('dim_label'), min_value=1.0, max_value=200.0,
                                             value=15.0, step=1.0)
    kusy_na_hmat = st.sidebar.slider(t('hmat_label'), min_value=1, max_value=20, value=1, step=1)

    with st.expander(t('upload_title'), expanded=True):
        st.markdown(f"**{t('upload_help')}**")
        uploaded_files = st.file_uploader(
            "UploadFiles",
            label_visibility="collapsed",
            type=['csv', 'xlsx'],
            accept_multiple_files=True,
            key="main_uploader"
        )

    # ==========================================
    # PARSOVÁNÍ SOUBORŮ (jen při změně)
    # ==========================================
    if uploaded_files:
        current_files_hash = "".join([f"{f.name}{f.size}" for f in uploaded_files])

        if st.session_state.get('last_files_hash') != current_files_hash:
            progress_bar = st.progress(0)
            status_text = st.empty()
            status_text.markdown(f"**{t('loading')}**")
            progress_bar.progress(10)

            df_pick_raw = df_marm_raw = df_manual_raw = None
            df_queue_raw = df_vekp_raw = df_cats_raw = None

            for file in uploaded_files:
                fname = file.name.lower()

                if fname.endswith('.xlsx') and 'auswertung' in fname.lower():
                    try:
                        aus_xl = pd.ExcelFile(file)
                        aus_data = {}
                        for sn in aus_xl.sheet_names:
                            try:
                                aus_data[sn] = aus_xl.parse(sn, dtype=str)
                            except Exception:
                                pass
                        st.session_state['auswertung_raw'] = aus_data
                    except Exception as e:
                        st.warning(f"Nelze číst Auswertung soubor: {e}")
                    continue

                try:
                    temp_df = (pd.read_csv(file, dtype=str)
                               if fname.endswith('.csv')
                               else pd.read_excel(file, dtype=str))
                except Exception as e:
                    st.error(f"Chyba při čtení souboru {file.name}: {e}")
                    continue

                cols = set(temp_df.columns)

                if 'Delivery' in cols and 'Act.qty (dest)' in cols:
                    df_pick_raw = temp_df
                elif 'Numerator' in cols and 'Alternative Unit of Measure' in cols:
                    df_marm_raw = temp_df
                elif 'Handling Unit' in cols and 'Generated delivery' in cols:
                    df_vekp_raw = temp_df
                elif 'Lieferung' in cols and 'Kategorie' in cols:
                    df_cats_raw = temp_df
                elif 'Queue' in cols and (
                    'Transfer Order Number' in cols or 'SD Document' in cols
                ):
                    df_queue_raw = temp_df
                elif len(temp_df.columns) >= 2:
                    df_manual_raw = temp_df

            st.markdown(f"**{t('file_status_title')}**")
            file_status = {
                t('file_pick'): df_pick_raw is not None,
                t('file_marm'): df_marm_raw is not None,
                t('file_queue'): df_queue_raw is not None,
                t('file_vekp'): df_vekp_raw is not None,
                t('file_cats'): df_cats_raw is not None,
                t('file_manual'): df_manual_raw is not None,
            }
            s_cols = st.columns(6)
            for col, (fname_label, ok) in zip(s_cols, file_status.items()):
                col.metric(fname_label, "✅" if ok else "❌")

            if df_pick_raw is None:
                st.error(t('err_pick'))
                progress_bar.empty(); status_text.empty()
                return

            status_text.markdown(f"**{t('processing')}**")
            progress_bar.progress(40)

            df_pick = df_pick_raw.copy()
            df_pick['Material'] = df_pick['Material'].astype(str).str.strip()
            df_pick['Match_Key'] = get_match_key_vectorized(df_pick['Material'])
            df_pick['Qty'] = pd.to_numeric(df_pick['Act.qty (dest)'], errors='coerce').fillna(0)
            df_pick['Delivery'] = df_pick['Delivery'].astype(str).str.strip()

            if 'Source Storage Bin' in df_pick.columns:
                df_pick['Source Storage Bin'] = df_pick['Source Storage Bin'].fillna('').astype(str)
            elif 'Storage Bin' in df_pick.columns:
                df_pick['Source Storage Bin'] = df_pick['Storage Bin'].fillna('').astype(str)
            else:
                df_pick['Source Storage Bin'] = ''

            df_pick['Removal of total SU'] = (
                df_pick['Removal of total SU'].fillna('').astype(str).str.strip().str.upper()
                if 'Removal of total SU' in df_pick.columns
                else ''
            )

            if 'Confirmation date' in df_pick.columns:
                df_pick['Date'] = pd.to_datetime(df_pick['Confirmation date'], errors='coerce')
            elif 'Confirmation Date' in df_pick.columns:
                df_pick['Date'] = pd.to_datetime(df_pick['Confirmation Date'], errors='coerce')
            else:
                df_pick['Date'] = pd.NaT

            num_removed_admins = 0
            if 'User' in df_pick.columns:
                mask_admins = df_pick['User'].isin(['UIDJ5089', 'UIH25501'])
                num_removed_admins = int(mask_admins.sum())
                df_pick = df_pick[~mask_admins].copy()

            df_pick = df_pick.dropna(subset=['Delivery', 'Material']).copy()

            queue_count_col = 'Delivery'
            df_pick['Queue'] = 'N/A'

            if df_queue_raw is not None:
                if ('Transfer Order Number' in df_pick.columns
                        and 'Transfer Order Number' in df_queue_raw.columns):
                    q_map = (
                        df_queue_raw
                        .dropna(subset=['Transfer Order Number', 'Queue'])
                        .drop_duplicates('Transfer Order Number')
                        .set_index('Transfer Order Number')['Queue']
                        .to_dict()
                    )
                    df_pick['Queue'] = df_pick['Transfer Order Number'].map(q_map).fillna('N/A')
                    queue_count_col = 'Transfer Order Number'

                    for d_col in ['Confirmation Date', 'Creation Date']:
                        if d_col in df_queue_raw.columns:
                            d_map = (
                                df_queue_raw
                                .dropna(subset=['Transfer Order Number', d_col])
                                .drop_duplicates('Transfer Order Number')
                                .set_index('Transfer Order Number')[d_col]
                                .to_dict()
                            )
                            to_dates = df_pick['Transfer Order Number'].map(d_map)
                            df_pick['Date'] = df_pick['Date'].fillna(pd.to_datetime(to_dates, errors='coerce'))
                            break

                elif 'SD Document' in df_queue_raw.columns:
                    q_map = (
                        df_queue_raw
                        .dropna(subset=['SD Document', 'Queue'])
                        .drop_duplicates('SD Document')
                        .set_index('SD Document')['Queue']
                        .to_dict()
                    )
                    df_pick['Queue'] = df_pick['Delivery'].map(q_map).fillna('N/A')

                df_pick = df_pick[df_pick['Queue'].astype(str).str.upper() != 'CLEARANCE'].copy()

            manual_boxes = {}
            if df_manual_raw is not None and not df_manual_raw.empty:
                c_mat = df_manual_raw.columns[0]
                c_pkg = df_manual_raw.columns[1]
                for _, row in df_manual_raw.iterrows():
                    raw_mat = str(row[c_mat])
                    if raw_mat.upper() in ['NAN', 'NONE', '']:
                        continue
                    mat_key = get_match_key(raw_mat)
                    pkg = str(row[c_pkg])
                    nums = re.findall(
                        r'\bK-(\d+)ks?\b'
                        r'|(\d+)\s*ks\b'
                        r'|balen[íi]\s+po\s+(\d+)'
                        r'|krabice\s+(?:po\s+)?(\d+)'
                        r'|(?:role|pytl[íi]k|pytel)[^\d]*(\d+)',
                        pkg, flags=re.IGNORECASE
                    )
                    ext = sorted(list(set([int(g) for m in nums for g in m if g])), reverse=True)
                    if not ext and re.search(r'po\s*kusech', pkg, re.IGNORECASE):
                        ext = [1]
                    if ext:
                        manual_boxes[mat_key] = ext

            progress_bar.progress(60)

            box_dict = {}
            weight_dict = {}
            dim_dict = {}

            if df_marm_raw is not None:
                df_marm_raw['Match_Key'] = get_match_key_vectorized(df_marm_raw['Material'])

                df_boxes = df_marm_raw[
                    df_marm_raw['Alternative Unit of Measure'].isin(BOX_UNITS)
                ].copy()
                df_boxes['Numerator'] = pd.to_numeric(df_boxes['Numerator'], errors='coerce').fillna(0)
                box_dict = (
                    df_boxes.groupby('Match_Key')['Numerator']
                    .apply(lambda g: sorted([int(x) for x in g if x > 1], reverse=True))
                    .to_dict()
                )

                df_st = df_marm_raw[
                    df_marm_raw['Alternative Unit of Measure'].isin(['ST', 'PCE', 'KS', 'EA', 'PC'])
                ].copy()
                df_st['Gross Weight'] = pd.to_numeric(df_st['Gross Weight'], errors='coerce').fillna(0)
                df_st['Weight_KG'] = np.where(
                    df_st['Unit of Weight'].astype(str).str.upper() == 'G',
                    df_st['Gross Weight'] / 1000.0,
                    df_st['Gross Weight']
                )
                weight_dict = df_st.groupby('Match_Key')['Weight_KG'].first().to_dict()

                def to_cm(val, unit):
                    try:
                        v = float(val)
                        u = str(unit).upper().strip()
                        if u == 'MM': return v / 10.0
                        if u == 'M':  return v * 100.0
                        return v
                    except Exception:
                        return 0.0

                for dim_col, short in [('Length', 'L'), ('Width', 'W'), ('Height', 'H')]:
                    if dim_col in df_st.columns:
                        df_st[short] = df_st.apply(
                            lambda r, dc=dim_col: to_cm(r[dc], r.get('Unit of Dimension', 'CM')),
                            axis=1
                        )
                    else:
                        df_st[short] = 0.0

                dim_dict = df_st.set_index('Match_Key')[['L', 'W', 'H']].max(axis=1).to_dict()

            progress_bar.progress(80)

            df_pick['Box_Sizes_List'] = df_pick['Match_Key'].apply(
                lambda m: manual_boxes.get(m, box_dict.get(m, []))
            )
            df_pick['Piece_Weight_KG'] = df_pick['Match_Key'].map(weight_dict).fillna(0.0)
            df_pick['Piece_Max_Dim_CM'] = df_pick['Match_Key'].map(dim_dict).fillna(0.0)

            if df_vekp_raw is not None:
                df_vekp_raw['Generated delivery'] = df_vekp_raw['Generated delivery'].astype(str).str.strip()

            if df_cats_raw is not None:
                df_cats_raw['Lieferung'] = df_cats_raw['Lieferung'].astype(str).str.strip()
                df_cats_raw['Category_Full'] = (
                    df_cats_raw['Kategorie'].astype(str).str.strip()
                    + " "
                    + df_cats_raw['Art'].astype(str).str.strip()
                )
                df_cats_raw = df_cats_raw.drop_duplicates('Lieferung')

            st.session_state.update({
                'last_files_hash': current_files_hash,
                'df_pick_prep': df_pick,
                'queue_count_col': queue_count_col,
                'num_removed_admins': num_removed_admins,
                'manual_boxes': manual_boxes,
                'weight_dict': weight_dict,
                'dim_dict': dim_dict,
                'box_dict': box_dict,
                'df_vekp': df_vekp_raw,
                'df_cats': df_cats_raw,
            })

            progress_bar.progress(100)
            time.sleep(0.2)
            progress_bar.empty()
            status_text.empty()

    else:
        for key in ['last_files_hash', 'df_pick_prep', 'df_vekp', 'df_cats']:
            st.session_state.pop(key, None)

    if 'df_pick_prep' not in st.session_state or st.session_state['df_pick_prep'] is None:
        return

    df_pick = st.session_state['df_pick_prep'].copy()
    queue_count_col = st.session_state['queue_count_col']
    num_removed_admins = st.session_state['num_removed_admins']
    manual_boxes = st.session_state['manual_boxes']
    weight_dict = st.session_state['weight_dict']
    dim_dict = st.session_state['dim_dict']
    box_dict = st.session_state['box_dict']
    df_vekp = st.session_state.get('df_vekp')
    df_cats = st.session_state.get('df_cats')

    df_pick['Month'] = df_pick['Date'].dt.to_period('M').astype(str).replace('NaT', t('unknown'))

    # ==========================================
    # GLOBÁLNÍ FILTRACE OBDOBÍ PRO VŠECHNY TABULKY
    # ==========================================
    st.sidebar.divider()
    st.sidebar.header(t('filter_global_title'))
    date_mode = st.sidebar.radio("Filtr období:", [t('filter_all'), t('filter_month'), t('filter_range')], label_visibility="collapsed")
    
    if date_mode == t('filter_month'):
        known_months = sorted([m for m in df_pick['Month'].unique() if m not in [t('unknown'), 'NaT']])
        months_opts = known_months + [t('unknown')] if t('unknown') in df_pick['Month'].unique() else known_months
        sel_month = st.sidebar.selectbox(t('filter_month_sel'), options=months_opts)
        df_pick = df_pick[df_pick['Month'] == sel_month].copy()
    elif date_mode == t('filter_range'):
        valid_dates = df_pick['Date'].dropna()
        if not valid_dates.empty:
            min_d = valid_dates.min().date()
            max_d = valid_dates.max().date()
        else:
            min_d = pd.to_datetime('2020-01-01').date()
            max_d = pd.to_datetime('2030-01-01').date()
            
        date_range = st.sidebar.date_input(t('filter_range_sel'), [min_d, max_d], min_value=min_d, max_value=max_d)
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_d, end_d = date_range
            df_pick = df_pick[(df_pick['Date'].dt.date >= start_d) & (df_pick['Date'].dt.date <= end_d)].copy()

    # Vyloučení materiálů
    excluded_materials = st.sidebar.multiselect(
        t('exclude_label'),
        options=sorted(df_pick['Material'].unique()),
        default=[]
    )
    if excluded_materials:
        df_pick = df_pick[~df_pick['Material'].isin(excluded_materials)].copy()

    t_total, t_exact, t_miss = fast_compute_moves(
        qty_list=df_pick['Qty'].values,
        queue_list=df_pick['Queue'].values,
        su_list=df_pick['Removal of total SU'].values,
        box_list=df_pick['Box_Sizes_List'].values,
        w_list=df_pick['Piece_Weight_KG'].values,
        d_list=df_pick['Piece_Max_Dim_CM'].values,
        v_lim=limit_vahy,
        d_lim=limit_rozmeru,
        h_lim=kusy_na_hmat
    )

    df_pick['Pohyby_Rukou'] = t_total
    df_pick['Pohyby_Exact'] = t_exact
    df_pick['Pohyby_Loose_Miss'] = t_miss
    df_pick['Celkova_Vaha_KG'] = df_pick['Qty'] * df_pick['Piece_Weight_KG']

    c_i1, c_i2, c_i3 = st.columns(3)
    if num_removed_admins > 0:
        c_i1.info(t('info_users').format(num_removed_admins))
    x_c = (
        (df_pick['Removal of total SU'] == 'X')
        & (df_pick['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE']))
    ).sum()
    if x_c > 0:
        c_i2.warning(t('info_clean').format(x_c))
    if manual_boxes:
        c_i3.success(t('info_manual').format(len(manual_boxes)))

    tab_dash, tab_pallets, tab_fu, tab_top, tab_billing, tab_audit = st.tabs([
        t('tab_dashboard'), t('tab_pallets'), t('tab_fu'), t('tab_top'), t('tab_billing'), t('tab_audit')
    ])

    # ==========================================
    # TAB 1: DASHBOARD & QUEUE
    # ==========================================
    with tab_dash:
        display_q = None

        tot_mov = df_pick['Pohyby_Rukou'].sum()
        if tot_mov > 0:
            st.subheader(t('sec_ratio'))
            st.write(t('ratio_desc'))
            st.markdown(f"**{t('ratio_moves')}**")

            c_r1, c_r2 = st.columns(2)
            c_r1.metric(
                t('ratio_exact'),
                f"{df_pick['Pohyby_Exact'].sum() / tot_mov * 100:.1f} %",
                f"{df_pick['Pohyby_Exact'].sum():,.0f} {t('audit_phys_moves').lower()}"
            )
            c_r2.metric(
                t('ratio_miss'),
                f"{df_pick['Pohyby_Loose_Miss'].sum() / tot_mov * 100:.1f} %",
                f"{df_pick['Pohyby_Loose_Miss'].sum():,.0f} {t('audit_phys_moves').lower()}",
                delta_color="inverse"
            )
            with st.expander(t('logic_explain_title')):
                st.info(t('logic_explain_text'))

        if (df_pick['Queue'].notna().any() and df_pick['Queue'].nunique() > 1):
            st.divider()
            st.subheader(t('sec_queue_title'))

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
                col_qt1, col_qt2 = st.columns([2.5, 1])
                with col_qt1:
                    st.dataframe(styled_q, use_container_width=True, hide_index=True)
                with col_qt2:
                    chart_data = q_sum.drop_duplicates('Queue').set_index('Queue')['prum_pohybu_lokace']
                    st.bar_chart(chart_data)

    # ==========================================
    # TAB 2: PALETOVÉ ZAKÁZKY
    # ==========================================
    with tab_pallets:
        st.subheader(t('sec1_title'))
        st.markdown(t('pallets_clean_info'))

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
                c1.metric(t('m_orders'), f"{len(filtered_orders):,}".replace(',', ' '))
                c2.metric(t('m_qty'), f"{filtered_orders['total_qty'].mean():.1f}")
                c3.metric(t('m_pos'), f"{filtered_orders['num_positions'].mean():.2f}")
                c4.metric(t('m_mov_loc'), f"{filtered_orders['mov_per_loc'].mean():.1f}")

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
    with tab_fu:
        st.subheader(t('fu_title'))
        st.markdown(t('fu_desc'))

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
    with tab_top:
        st.subheader(t('sec_queue_top_title'))
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
    with tab_billing:
        
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
            vekp_filtered = vekp_clean[vekp_clean["Generated delivery"].isin(valid_deliveries)]

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

            hu_agg = vekp_filtered.groupby("Generated delivery").agg(
                pocet_hu=("Handling Unit", "nunique")
            ).reset_index()

            billing_df = pd.merge(pick_agg, hu_agg,
                                  left_on="Delivery", right_on="Generated delivery", how="left")
            billing_df["pocet_hu"] = billing_df["pocet_hu"].fillna(0).astype(int)
            billing_df["pohybu_na_hu"] = np.where(
                billing_df["pocet_hu"] > 0,
                billing_df["pohyby_celkem"] / billing_df["pocet_hu"], 0)
            billing_df["nepokryte_to"] = (
                billing_df["pocet_to"] - billing_df["pocet_hu"]).clip(lower=0).astype(int)
            billing_df["avg_mov_per_loc"] = np.where(
                billing_df["pocet_lokaci"] > 0,
                billing_df["pohyby_celkem"] / billing_df["pocet_lokaci"], 0)

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

        # ═══════════════════════════════════════════════════════════════
        # SEKCE A: PICK ↔ HU KORELACE
        # ═══════════════════════════════════════════════════════════════
        st.subheader(t("b_title"))
        st.markdown(t("b_desc"))

        if not billing_df.empty:
            total_deliveries = len(df_pick["Delivery"].dropna().unique())
            total_hus = vekp_filtered["Handling Unit"].nunique()
            total_pick_moves = int(df_pick["Pohyby_Rukou"].sum())
            total_tos = df_pick[queue_count_col].nunique()
            moves_per_hu = total_pick_moves / total_hus if total_hus > 0 else 0

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric(t("b_del_count"), f"{total_deliveries:,}".replace(",", " "))
            c2.metric(t("b_to_count"), f"{total_tos:,}".replace(",", " "))
            c3.metric(t("b_hu_count"), f"{total_hus:,}".replace(",", " "))
            c4.metric(t("b_mov_per_hu"), f"{moves_per_hu:.1f}")
            nerov_count = int((billing_df["nepokryte_to"] > 0).sum())
            nepokr_to_sum = int(billing_df["nepokryte_to"].sum())
            c5.metric(t("b_imbalance_orders"), f"{nerov_count:,}".replace(",", " "),
                      f"{nerov_count / len(billing_df) * 100:.1f} % {t('b_of_all')}",
                      delta_color="inverse")
            c6.metric(t("b_unpaid_to"), f"{nepokr_to_sum:,}".replace(",", " "),
                      t("b_unpaid_to_help"), delta_color="inverse")

            st.divider()
            st.subheader(t("b_cat_title"))
            cat_summary = billing_df.groupby("Category_Full").agg(
                pocet_hu=("pocet_hu", "sum"),
                pocet_lokaci=("pocet_lokaci", "sum"),
                pohyby_celkem=("pohyby_celkem", "sum"),
                pohyby_exact=("pohyby_exact", "sum"),
                pohyby_miss=("pohyby_miss", "sum"),
                nepokryte_to_sum=("nepokryte_to", "sum"),
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
                "Category_Full", "pocet_hu", "avg_loc_per_hu",
                "avg_mov_per_loc", "nepokryte_to_sum", "pct_exact", "pct_miss"]].copy()
            cat_disp.columns = [
                t("b_col_type"), t("b_col_hu"), t("b_col_loc_hu"),
                t("b_col_mov_loc"), t("b_col_unpaid_to"), t("b_col_pct_ex"), t("b_col_pct_ms")]
            fmt_cat = {c: "{:.1f} %" for c in cat_disp.columns if "%" in c}
            fmt_cat.update({c: "{:.1f}" for c in [t("b_col_loc_hu"), t("b_col_mov_loc")]})
            cb1, cb2 = st.columns([2.5, 1])
            with cb1:
                st.dataframe(cat_disp.style.format(fmt_cat).set_properties(
                    subset=[t("b_col_type"), t("b_col_mov_loc")], **{"font-weight": "bold"}),
                    use_container_width=True, hide_index=True)
            with cb2:
                chart_data = cat_summary[cat_summary["Category_Full"] != t("uncategorized")].set_index("Category_Full")["avg_mov_per_loc"]
                st.bar_chart(chart_data)

            st.divider()
            st.markdown(t("detail_breakdown"))
            det_df = billing_df[["Delivery", "Category_Full", "pocet_to",
                                  "pohyby_celkem", "pocet_hu", "nepokryte_to", "pohybu_na_hu"]
                                ].sort_values("pohyby_celkem", ascending=False).copy()
            det_df.columns = [t("b_table_del"), t("b_table_cat"), t("b_table_to"),
                               t("b_table_mov"), t("b_table_hu"), t("b_col_unpaid_to"), t("b_table_mph")]
            st.dataframe(det_df.style.format({t("b_table_mph"): "{:.1f}"}),
                         use_container_width=True, hide_index=True)
        else:
            st.warning(t("b_missing_vekp"))

        # ═══════════════════════════════════════════════════════════════════
        # SEKCE B: AUSWERTUNG — logiky ze zákazníkova souboru
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
                    vollpalette_lager = set(df_t023.iloc[:, 0].astype(str).str.strip())

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

                    col_map = {c_hu_int: "HU_intern", c_hu_ext: "Handling_Unit_Ext"}
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
                    metrics_cols[0].metric(t("b_aus_total_lief"), f"{tot_l:,}".replace(",", " "))
                    metrics_cols[1].metric(t("b_aus_total_hu"), f"{tot_h:,}".replace(",", " "))
                    metrics_cols[2].metric(t("b_aus_avg_hu_lief"), f"{avg_h:.2f}")
                    metrics_cols[3].metric(t("b_aus_total_vaha"), f"{tot_gew:,.0f} kg".replace(",", " "))
                    metrics_cols[4].metric(t("b_aus_pct_kep"), f"{pct_kep:.1f} %")
                    if has_pick:
                        avg_mpl_all = (aus_lief["pohyby_celkem"].sum() /
                                       aus_lief["pocet_lokaci"].sum()
                                       if aus_lief["pocet_lokaci"].sum() > 0 else 0)
                        metrics_cols[5].metric("Prům. pohybů / lokaci", f"{avg_mpl_all:.2f}")

                st.divider()
                st.subheader(t("b_aus_kat_title"))
                st.caption(t("b_aus_kat_desc"))

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
                st.subheader(t("b_aus_art_title"))
                st.caption(t("b_aus_art_desc"))

                if not df_vk.empty and "Art_HU" in df_vk.columns:
                    art_celk = df_vk["Art_HU"].value_counts()
                    art_sum = art_celk.sum()
                    ca1, ca2, ca3 = st.columns(3)
                    for col_m, label, icon in [(ca1, "Sortenrein", "📦"),
                                               (ca2, "Misch", "🔀"),
                                               (ca3, "Vollpalette", "🏭")]:
                        cnt = int(art_celk.get(label, 0))
                        pct = cnt / art_sum * 100 if art_sum > 0 else 0
                        col_m.metric(f"{icon} {label}", f"{cnt:,}".replace(",", " "), f"{pct:.1f} %")

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
                    st.subheader("⚖️ " + t("b_aus_art_title").replace("Typy HU", "Váhy HU")
                                 if "Typy HU" in t("b_aus_art_title")
                                 else "⚖️ Váhy HU (Gesamtgewicht = Eigengewicht + Ladungsgewicht)")
                    st.caption("Gesamtgewicht = Eigengewicht (prázdná krabice) + Ladungsgewicht (obsah). "
                               "Ověřeno 99.8% shodou na zákazníkových datech.")

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
                    st.subheader(t("b_aus_carton_title"))
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
                st.subheader(t("b_aus_sped_title"))
                kc1, kc2 = st.columns(2)
                kc1.metric(t("b_aus_kep_count"), str(len(kep_set)))
                kc2.metric(t("b_aus_nonkep_count"), str(len(df_sdshp) - len(kep_set) if not df_sdshp.empty else 0))
                if not sdshp_display.empty:
                    col_s0 = sdshp_display.columns[0]
                    sdshp_d2 = sdshp_display.copy()
                    sdshp_d2["Je KEP"] = sdshp_d2[col_s0].astype(str).str.strip().isin(kep_set).map(
                        {True: "✅ KEP", False: "—"})
                    with st.expander("Zobrazit tabulku dopravců (SDSHP_AM2)"):
                        st.dataframe(sdshp_d2, use_container_width=True, hide_index=True)

                st.divider()
                st.subheader(t("b_aus_voll_title"))
                vt1, vt2 = st.columns(2)
                vt1.metric(t("b_aus_voll_count"), f"{len(vollpalette_lager):,}".replace(",", " "))
                if not df_vk.empty and "Art_HU" in df_vk.columns:
                    vt2.metric("HU označených Vollpalette",
                               f"{int((df_vk['Art_HU'] == 'Vollpalette').sum()):,}".replace(",", " "))
                if not df_t023.empty:
                    with st.expander("Zobrazit T023 — přímé pohyby celých palet"):
                        t023_d = df_t023.copy()
                        t023_d.columns = (["Lagereinheit (HU)", "Transport Order č.", "Pozice TO"]
                                          + list(t023_d.columns[3:]))
                        st.dataframe(t023_d, use_container_width=True, hide_index=True)

                st.divider()
                with st.expander(t("b_aus_detail_exp"), expanded=False):
                    if not aus_lief.empty:
                        det_cols_s = ["Lieferung", "Kategorie"]
                        det_fmt    = {}
                        if "anzahl_hu" in aus_lief.columns:
                            det_cols_s.append("anzahl_hu")
                        if gew_col:
                            det_cols_s.append(gew_col); det_fmt[gew_col] = "{:.1f}"
                        for ac in art_cols_avail:
                            if ac in aus_lief.columns:
                                det_cols_s.append(ac)
                        if "avg_mov_per_loc" in aus_lief.columns:
                            det_cols_s.append("avg_mov_per_loc")
                            det_fmt["avg_mov_per_loc"] = "{:.2f}"
                        if "pm_typy" in aus_lief.columns:
                            det_cols_s.append("pm_typy")

                        det_aus = aus_lief[det_cols_s].copy()
                        det_aus["Popis"] = det_aus["Kategorie"].map(kat_desc_map).fillna(det_aus["Kategorie"])
                        sort_by = gew_col if (gew_col and gew_col in det_aus.columns) else "Lieferung"
                        det_aus = det_aus.sort_values(sort_by, ascending=False)

                        col_renames = {"Lieferung": "Delivery", "Kategorie": t("b_aus_kat"),
                                       "anzahl_hu": t("b_aus_hu"), "pm_typy": t("b_aus_carton"),
                                       "Popis": t("b_aus_popis"), "Brutto_kg": "Váha LIPS (kg)",
                                       "celk_gew": "Váha VEKP (kg)",
                                       "avg_mov_per_loc": "Prům. pohybů / lokaci"}
                        det_aus = det_aus.rename(columns={k: v for k, v in col_renames.items()
                                                           if k in det_aus.columns})
                        det_fmt_renamed = {col_renames.get(k, k): v for k, v in det_fmt.items()}
                        st.dataframe(det_aus.style.format(
                            {k: v for k, v in det_fmt_renamed.items() if k in det_aus.columns}),
                            use_container_width=True, hide_index=True)
                    else:
                        st.info("Žádná data zásilek k zobrazení.")

            except Exception as _e:
                import traceback
                st.error(f"Chyba při zpracování Auswertung: {_e}")
                with st.expander("Detail chyby (pro debugging)"):
                    st.code(traceback.format_exc())

    # TAB 6: NÁSTROJE & AUDIT
    # ==========================================
    with tab_audit:
        col_au1, col_au2 = st.columns([3, 2])

        with col_au1:
            st.subheader(t('audit_title'))

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
                                    limit_str = (f"{limit_vahy}kg" if w >= limit_vahy
                                                 else f"{limit_rozmeru}cm")
                                    if over_limit:
                                        st.warning(
                                            t('audit_lim').format(int(zbytek), limit_str, int(zbytek))
                                        )
                                    else:
                                        hmaty = int(np.ceil(zbytek / kusy_na_hmat))
                                        st.success(
                                            t('audit_grab').format(int(zbytek), hmaty, kusy_na_hmat)
                                        )

                            total_moves = int(row.get('Pohyby_Rukou', 0))
                            st.markdown(f"> **{t('audit_phys_moves')}: `{total_moves}`**")
                            st.write("---")

        with col_au2:
            st.subheader(t('sec3_title'))
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

        # --- NOVÝ AUDIT ÚČTOVÁNÍ (PICK vs VEKP) ---
        st.divider()
        st.subheader(t('audit_b_title'))
        avail_dels = sorted(df_pick['Delivery'].dropna().unique())
        sel_del = st.selectbox(t('audit_b_sel'), options=[""] + avail_dels)
        
        if sel_del:
            pick_del = df_pick[df_pick['Delivery'] == sel_del]
            to_count = pick_del[queue_count_col].nunique()
            moves_count = pick_del['Pohyby_Rukou'].sum()
            
            hu_count = 0
            vekp_del = pd.DataFrame()
            if df_vekp is not None and not df_vekp.empty:
                vekp_del = df_vekp[df_vekp['Generated delivery'] == sel_del]
                hu_count = vekp_del['Handling Unit'].nunique()
                
            c_a1, c_a2, c_a3, c_a4 = st.columns(4)
            c_a1.metric("Počet Pickovacích TO", to_count)
            c_a2.metric("Fyzických pohybů", f"{int(moves_count):,}")
            c_a3.metric("Zabalených HU (VEKP)", hu_count)
            c_a4.metric("Pohybů na 1 HU", f"{moves_count / hu_count:.2f}" if hu_count > 0 else "Chybí HU")
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.markdown(t('audit_b_pick_det'))
                disp_p = pick_del[[queue_count_col, 'Material', 'Qty', 'Pohyby_Rukou']].copy()
                st.dataframe(disp_p, hide_index=True, use_container_width=True)
            with col_d2:
                st.markdown(t('audit_b_vekp_det'))
                if not vekp_del.empty:
                    disp_v = vekp_del[['Handling Unit', 'Packaging materials', 'Total Weight']].copy()
                    st.dataframe(disp_v, hide_index=True, use_container_width=True)
                else:
                    st.warning(t('audit_b_no_vekp'))

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
            file_name=f"Warehouse_Analysis_{time.strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )


if __name__ == "__main__":
    main()
