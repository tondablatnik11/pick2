import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

# Globální nastavení grafů pro jednotný vzhled
CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)', 
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#f8fafc', size=12, family="Inter, sans-serif"),
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified"
)

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

def render_packing(billing_df, df_oe):
    # Chytrý lokální překladač
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>📦 {_t('Analýza balícího procesu (OE-Times)', 'Packing Process Analysis (OE-Times)')}</h3><p>{_t('Komplexní propojení času u balícího stolu s konkrétními zákazníky, materiály a použitými obaly.', 'Comprehensive connection of packing station time with specific customers, materials, and used packaging.')}</p></div>", unsafe_allow_html=True)

    if df_oe is None or df_oe.empty:
        st.info(_t("Pro tuto záložku je nutné nahrát soubor OE-Times v Admin zóně.", "Upload the OE-Times file in Admin Zone to use this tab."))
        return

    if billing_df is None or billing_df.empty:
        st.warning(_t("Pro propojení chybí data z Fakturace (VEKP). Aplikace nejprve potřebuje načíst data z předchozích záložek.", "Billing data (VEKP) missing for correlation. App needs data from previous tabs first."))
        return

    # OBRANA PROTI UNBOUND LOCAL ERROR
    e2e_df = pd.DataFrame()
    valid_time_df = pd.DataFrame()

    # Příprava dat pro čisté párování
    df_oe_clean = df_oe.copy()
    df_oe_clean['Clean_Del'] = df_oe_clean['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    
    bill_clean = billing_df.copy()
    bill_clean['Clean_Del'] = bill_clean['Clean_Del_Merge'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')

    # Spojení fakturačních dat a časů balení (Inner Join)
    pack_df = pd.merge(bill_clean, df_oe_clean, on='Clean_Del', how='inner')

    if pack_df.empty:
        st.error(_t("Nepodařilo se spárovat žádné zakázky z OE-Times s daty ze skladu/fakturace (Zkontrolujte formát čísel Delivery).", "Failed to match any orders from OE-Times with warehouse/billing data."))
        return

    # Očištění dat od nesmyslných časů (např. 0 minut)
    valid_time_df = pack_df[pack_df['Process_Time_Min'] > 0].copy()

    if valid_time_df.empty:
         st.warning(_t("Data se sice spojila, ale u žádné zakázky není zaznamenán platný procesní čas (> 0 min).", "Data matched, but no valid process time (> 0 min) found."))
         return

    # Výpočet efektivity (Minut na 1 HU)
    valid_time_df['Min_per_HU'] = np.where(valid_time_df['pocet_hu'] > 0, valid_time_df['Process_Time_Min'] / valid_time_df['pocet_hu'], valid_time_df['Process_Time_Min'])
    
    # Detekce konfliktů názvů po merge (Materiál z picku vs Materiál z OE)
    mat_col = 'Material_y' if 'Material_y' in valid_time_df.columns else 'Material'
    
    # --- HLAVNÍ METRIKY ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True): st.metric(_t("Spárovaných zakázek", "Matched Orders"), f"{len(valid_time_df):,}")
    with c2:
        with st.container(border=True): st.metric(_t("Celkový čas balení", "Total Packing Time"), f"{valid_time_df['Process_Time_Min'].sum() / 60:.1f} h")
    with c3:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 zakázku", "Avg Time per Order"), f"{valid_time_df['Process_Time_Min'].mean():.1f} min")
    with c4:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 Billed HU", "Avg Time per Billed HU"), f"{valid_time_df['Min_per_HU'].mean():.1f} min")

    st.divider()

    # --- PŘEPÍNAČE POHLEDŮ (TABS) ---
    tab_cust, tab_mat, tab_pkg, tab_detail = st.tabs([
        f"🏢 {_t('Podle zákazníka', 'By Customer')}",
        f"⚙️ {_t('Podle materiálu & složitosti', 'By Material & Complexity')}",
        f"📦 {_t('Spotřeba obalů', 'Packaging Usage')}",
        f"🔍 {_t('Detailní E2E Report', 'Detailed E2E Report')}"
    ])

    # ==========================================
    # ZÁLOŽKA 1: ZÁKAZNÍCI
    # ==========================================
    with tab_cust:
        if 'CUSTOMER' in valid_time_df.columns:
            st.markdown(f"**🏢 {_t('Náročnost balení podle zákazníků (Customer Profitability)', 'Packing Effort by Customer (Profitability)')}**")
            st.caption(_t("Ukazuje, kteří zákazníci vyžadují nejvíce procesního času na vytvoření jedné fakturační jednotky.", "Shows which customers require the most process time to create a single billing unit."))
            
            cust_df = valid_time_df.groupby('CUSTOMER').agg(
                Orders=('Clean_Del', 'nunique'),
                Total_Time=('Process_Time_Min', 'sum'),
                Total_HU=('pocet_hu', 'sum'),
                Total_TO=('pocet_to', 'sum')
            ).reset_index()
            
            cust_df['Avg_Min_Order'] = np.where(cust_df['Orders'] > 0, cust_df['Total_Time'] / cust_df['Orders'], 0)
            cust_df['Avg_Min_HU'] = np.where(cust_df['Total_HU'] > 0, cust_df['Total_Time'] / cust_df['Total_HU'], 0)
            cust_df = cust_df.sort_values('Avg_Min_HU', ascending=False)
            
            col_c1, col_c2 = st.columns([1, 1.2])
            with col_c1:
                disp_cust = cust_df[['CUSTOMER', 'Orders', 'Total_Time', 'Avg_Min_HU']].copy()
                disp_cust.columns = [_t("Zákazník", "Customer"), _t("Zakázek", "Orders"), _t("Celkový čas (Min)", "Total Time (Min)"), _t("Minut na 1 HU", "Min per 1 HU")]
                st.dataframe(disp_cust.style.format({_t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}", _t("Minut na 1 HU", "Min per 1 HU"): "{:.1f}"}), hide_index=True, use_container_width=True)
                
            with col_c2:
                fig_cust = go.Figure(go.Bar(
                    x=cust_df['Avg_Min_HU'].head(15), 
                    y=cust_df['CUSTOMER'].head(15), 
                    orientation='h', marker_color='#8b5cf6', 
                    text=cust_df['Avg_Min_HU'].head(15).round(1).astype(str) + ' min', textposition='auto'
                ))
                fig_cust.update_layout(**CHART_LAYOUT)
                fig_cust.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Průměrně minut na 1 vyfakturovanou HU", "Avg minutes per 1 billed HU"))
                st.plotly_chart(fig_cust, use_container_width=True)
        else:
            st.info(_t("Sloupec 'CUSTOMER' není v datech k dispozici.", "Column 'CUSTOMER' not available in data."))

    # ==========================================
    # ZÁLOŽKA 2: MATERIÁLY A SLOŽITOST
    # ==========================================
    with tab_mat:
        st.markdown(f"**⚙️ {_t('Nejnáročnější materiály na balení', 'Most demanding materials for packing')}**")
        
        if mat_col in valid_time_df.columns:
            mat_df = valid_time_df.groupby(mat_col).agg(
                Orders=('Clean_Del', 'nunique'),
                Avg_Time=('Process_Time_Min', 'mean'),
                Total_Time=('Process_Time_Min', 'sum')
            ).reset_index()
            # Filtrujeme jen materiály, co se dělaly aspoň 2x, aby průměr měl smysl
            mat_df = mat_df[mat_df['Orders'] > 1].sort_values('Avg_Time', ascending=False).head(20)
            
            col_m1, col_m2 = st.columns([1, 1.2])
            with col_m1:
                disp_mat = mat_df.copy()
                disp_mat.columns = [_t("Materiál", "Material"), _t("Frekvence (Zakázek)", "Frequency (Orders)"), _t("Prům. čas (Min)", "Avg Time (Min)"), _t("Celkový čas (Min)", "Total Time (Min)")]
                st.dataframe(disp_mat.style.format({_t("Prům. čas (Min)", "Avg Time (Min)"): "{:.1f}", _t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}"}), hide_index=True, use_container_width=True)
            
            with col_m2:
                fig_mat = go.Figure(go.Bar(
                    x=mat_df['Avg_Time'], y=mat_df[mat_col].astype(str), 
                    orientation='h', marker_color='#f43f5e', 
                    text=mat_df['Avg_Time'].round(1).astype(str) + ' min', textposition='auto'
                ))
                fig_mat.update_layout(**CHART_LAYOUT)
                fig_mat.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Průměrný čas balení materiálu", "Avg packing time of material"))
                st.plotly_chart(fig_mat, use_container_width=True)

        st.divider()
        st.markdown(f"**🔴 {_t('Faktory zvyšující složitost balení (Skenování / KLT)', 'Factors increasing packing complexity (Scanning / KLT)')}**")
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            if 'Scanning serial numbers' in valid_time_df.columns:
                valid_time_df['Has_Scan'] = valid_time_df['Scanning serial numbers'].astype(str).str.upper().isin(['X', 'YES', 'ANO', '1'])
                scan_df = valid_time_df.groupby('Has_Scan')['Process_Time_Min'].mean().reset_index()
                
                scan_yes = scan_df[scan_df['Has_Scan'] == True]['Process_Time_Min'].mean()
                scan_no = scan_df[scan_df['Has_Scan'] == False]['Process_Time_Min'].mean()
                if pd.isna(scan_yes): scan_yes = 0
                if pd.isna(scan_no): scan_no = 0
                
                st.metric(_t("Vliv skenování sériových čísel", "Impact of serial number scanning"), f"{scan_yes:.1f} min", f"{scan_yes - scan_no:.1f} min {_t('navíc oproti normálu', 'extra vs normal')}", delta_color="inverse")
                
        with col_f2:
            if 'Difficult KLTs' in valid_time_df.columns:
                valid_time_df['Has_Diff'] = valid_time_df['Difficult KLTs'].astype(str).str.upper().isin(['X', 'YES', 'ANO', '1'])
                diff_df = valid_time_df.groupby('Has_Diff')['Process_Time_Min'].mean().reset_index()
                
                diff_yes = diff_df[diff_df['Has_Diff'] == True]['Process_Time_Min'].mean()
                diff_no = diff_df[diff_df['Has_Diff'] == False]['Process_Time_Min'].mean()
                if pd.isna(diff_yes): diff_yes = 0
                if pd.isna(diff_no): diff_no = 0
                
                st.metric(_t("Vliv 'Složitých KLT'", "Impact of 'Difficult KLTs'"), f"{diff_yes:.1f} min", f"{diff_yes - diff_no:.1f} min {_t('navíc oproti normálu', 'extra vs normal')}", delta_color="inverse")

    # ==========================================
    # ZÁLOŽKA 3: OBALY (PACKAGING)
    # ==========================================
    with tab_pkg:
        st.markdown(f"**📦 {_t('Četnost použití jednotlivých typů obalů (Dle záznamů z OE-Times)', 'Usage frequency of individual packaging types (per OE-Times)')}**")
        st.caption(_t("Analýza sloupců Cartons, KLT a Palety rozpadlá na jednotlivé položky.", "Analysis of Cartons, KLT, and Pallets columns broken down into individual items."))
        
        def get_packaging_counts(df, col_name):
            if col_name not in df.columns: return pd.DataFrame()
            all_items = df[col_name].dropna().astype(str).str.split(';').explode().str.strip()
            all_items = all_items[all_items != '']
            if all_items.empty: return pd.DataFrame()
            counts = all_items.value_counts().reset_index()
            counts.columns = [_t('Typ obalu', 'Packaging Type'), _t('Záznamů', 'Entries')]
            return counts

        p_col1, p_col2, p_col3 = st.columns(3)
        
        with p_col1:
            st.markdown(f"##### 🗃️ {_t('Krabice (Cartons)', 'Cartons')}")
            carton_counts = get_packaging_counts(valid_time_df, 'Cartons')
            if not carton_counts.empty: st.dataframe(carton_counts, hide_index=True, use_container_width=True)
            else: st.info(_t("Žádná data.", "No data."))
            
        with p_col2:
            st.markdown(f"##### 🟦 {_t('KLT boxy', 'KLT Boxes')}")
            klt_counts = get_packaging_counts(valid_time_df, 'KLT')
            if not klt_counts.empty: st.dataframe(klt_counts, hide_index=True, use_container_width=True)
            else: st.info(_t("Žádná data.", "No data."))
            
        with p_col3:
            st.markdown(f"##### 🏭 {_t('Palety', 'Pallets')}")
            pal_counts = get_packaging_counts(valid_time_df, 'Palety')
            if not pal_counts.empty: st.dataframe(pal_counts, hide_index=True, use_container_width=True)
            else: st.info(_t("Žádná data.", "No data."))

    # ==========================================
    # ZÁLOŽKA 4: DETAILNÍ DATA (TABULKA)
    # ==========================================
    with tab_detail:
        st.markdown(f"**🔍 {_t('Surová data a nejdelší procesy (Worst Offenders)', 'Raw data and longest processes (Worst Offenders)')}**")
        
        disp_pack = valid_time_df[['Clean_Del', 'CUSTOMER' if 'CUSTOMER' in valid_time_df.columns else mat_col, 'Category_Full', 'Process_Time_Min', 'pocet_to', 'pocet_hu', 'Min_per_HU']].copy()
        disp_pack = disp_pack.sort_values('Process_Time_Min', ascending=False).head(200)
        
        disp_pack.columns = [
            _t("Zakázka", "Order"), 
            _t("Zákazník / Mat.", "Customer / Mat."), 
            _t("Kategorie", "Category"), 
            _t("Celkem Čas (Min)", "Total Time (Min)"),
            _t("Počet TO (Sklad)", "TO Count (WH)"), 
            _t("Zabaleno HU", "Packed HU"), 
            _t("Čas na 1 HU", "Time per 1 HU")
        ]
        
        st.dataframe(disp_pack.style.format({
            _t("Celkem Čas (Min)", "Total Time (Min)"): "{:.1f}", 
            _t("Čas na 1 HU", "Time per 1 HU"): "{:.1f}"
        }), hide_index=True, use_container_width=True)
