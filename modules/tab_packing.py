import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import re
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

# Pomocná funkce pro vyčištění a sjednocení názvů obalů
def clean_pkg_name(name):
    name = str(name).strip().upper()
    if name in ['NAN', 'NONE', '']: return ''
    # Odstraní počty kusů v závorce, např. " (1X)", "(2x)"
    name = re.sub(r'\s*\(\d+X\)', '', name)
    # Odstraní slovo KARTON a pomlčky kolem něj
    name = re.sub(r'-?\s*KARTON\s*', '', name)
    return name.strip()

def render_packing(billing_df, df_oe):
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>📦 {_t('Analýza balícího procesu (OE-Times)', 'Packing Process Analysis (OE-Times)')}</h3><p>{_t('Komplexní propojení času u balícího stolu s konkrétními zákazníky, materiály a použitými obaly.', 'Comprehensive connection of packing station time with specific customers, materials, and used packaging.')}</p></div>", unsafe_allow_html=True)

    if df_oe is None or df_oe.empty:
        st.info(_t("Pro tuto záložku je nutné nahrát soubor OE-Times v Admin zóně.", "Upload the OE-Times file in Admin Zone to use this tab."))
        return

    if billing_df is None or billing_df.empty:
        st.warning(_t("Pro propojení chybí data z Fakturace (VEKP). Aplikace nejprve potřebuje načíst data z předchozích záložek.", "Billing data (VEKP) missing for correlation. App needs data from previous tabs first."))
        return

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

    # Výpočet efektivity
    valid_time_df['Min_per_HU'] = np.where(valid_time_df['pocet_hu'] > 0, valid_time_df['Process_Time_Min'] / valid_time_df['pocet_hu'], valid_time_df['Process_Time_Min'])
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
    tab_cust, tab_mat, tab_pkg, tab_detail, tab_complex = st.tabs([
        f"🏢 {_t('Podle zákazníka & Kategorie', 'By Customer & Category')}",
        f"⚙️ {_t('Podle materiálu & složitosti', 'By Material & Complexity')}",
        f"📦 {_t('Spotřeba a analýza obalů', 'Packaging Analysis')}",
        f"🔍 {_t('Detailní E2E Report', 'Detailed E2E Report')}",
        f"🧠 {_t('Komplexní Matice', 'Complex Matrix')}"
    ])

    # ==========================================
    # ZÁLOŽKA 1: ZÁKAZNÍCI A KATEGORIE
    # ==========================================
    with tab_cust:
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.markdown(f"**🏢 {_t('Náročnost balení podle Zákazníků', 'Packing Effort by Customer')}**")
            if 'CUSTOMER' in valid_time_df.columns:
                cust_df = valid_time_df.groupby('CUSTOMER').agg(
                    Orders=('Clean_Del', 'nunique'),
                    Total_Time=('Process_Time_Min', 'sum'),
                    Total_HU=('pocet_hu', 'sum')
                ).reset_index()
                
                cust_df['Avg_Min_Order'] = np.where(cust_df['Orders'] > 0, cust_df['Total_Time'] / cust_df['Orders'], 0)
                cust_df['Avg_Min_HU'] = np.where(cust_df['Total_HU'] > 0, cust_df['Total_Time'] / cust_df['Total_HU'], 0)
                
                # Seřazení podle počtu zakázek (Orders)
                cust_df = cust_df.sort_values('Orders', ascending=False)
                
                disp_cust = cust_df[['CUSTOMER', 'Orders', 'Avg_Min_Order', 'Avg_Min_HU', 'Total_Time']].copy()
                disp_cust.columns = [_t("Zákazník", "Customer"), _t("Počet zakázek", "Orders"), _t("Prům. čas na zakázku", "Avg Time/Order"), _t("Prům. čas na 1 HU", "Avg Time/HU"), _t("Celkový čas (Min)", "Total Time (Min)")]
                st.dataframe(disp_cust.style.format({_t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}", _t("Prům. čas na zakázku", "Avg Time/Order"): "{:.1f}", _t("Prům. čas na 1 HU", "Avg Time/HU"): "{:.1f}"}), hide_index=True, use_container_width=True)
                
                fig_cust = go.Figure(go.Bar(
                    x=cust_df['Orders'].head(15), 
                    y=cust_df['CUSTOMER'].head(15), 
                    orientation='h', marker_color='#8b5cf6', 
                    text=cust_df['Orders'].head(15), textposition='auto'
                ))
                fig_cust.update_layout(**CHART_LAYOUT)
                fig_cust.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), title=_t("TOP 15 Zákazníků (dle počtu zakázek)", "TOP 15 Customers (by orders)"))
                st.plotly_chart(fig_cust, use_container_width=True)
            else:
                st.info(_t("Sloupec 'CUSTOMER' není v datech k dispozici.", "Column 'CUSTOMER' not available in data."))

        with col_c2:
            st.markdown(f"**🏷️ {_t('Náročnost balení podle Kategorií (E/OE/N)', 'Packing Effort by Categories (E/OE/N)')}**")
            cat_df = valid_time_df.groupby('Category_Full').agg(
                Orders=('Clean_Del', 'nunique'),
                Total_Time=('Process_Time_Min', 'sum'),
                Total_HU=('pocet_hu', 'sum')
            ).reset_index()
            
            cat_df['Avg_Min_Order'] = np.where(cat_df['Orders'] > 0, cat_df['Total_Time'] / cat_df['Orders'], 0)
            cat_df['Avg_Min_HU'] = np.where(cat_df['Total_HU'] > 0, cat_df['Total_Time'] / cat_df['Total_HU'], 0)
            cat_df = cat_df.sort_values('Orders', ascending=False)
            
            disp_cat = cat_df[['Category_Full', 'Orders', 'Avg_Min_Order', 'Avg_Min_HU', 'Total_Time']].copy()
            disp_cat.columns = [_t("Kategorie", "Category"), _t("Počet zakázek", "Orders"), _t("Prům. čas na zakázku", "Avg Time/Order"), _t("Prům. čas na 1 HU", "Avg Time/HU"), _t("Celkový čas (Min)", "Total Time (Min)")]
            st.dataframe(disp_cat.style.format({_t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}", _t("Prům. čas na zakázku", "Avg Time/Order"): "{:.1f}", _t("Prům. čas na 1 HU", "Avg Time/HU"): "{:.1f}"}), hide_index=True, use_container_width=True)

            fig_cat = go.Figure(go.Bar(
                x=cat_df['Orders'], 
                y=cat_df['Category_Full'], 
                orientation='h', marker_color='#3b82f6', 
                text=cat_df['Orders'], textposition='auto'
            ))
            fig_cat.update_layout(**CHART_LAYOUT)
            fig_cat.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), title=_t("Kategorie (dle počtu zakázek)", "Categories (by orders)"))
            st.plotly_chart(fig_cat, use_container_width=True)

    # ==========================================
    # ZÁLOŽKA 2: MATERIÁLY A SLOŽITOST
    # ==========================================
    with tab_mat:
        st.markdown(f"**⚙️ {_t('Nejnáročnější materiály na balení (Dle průměrného času)', 'Most demanding materials for packing (By Avg Time)')}**")
        
        if mat_col in valid_time_df.columns:
            mat_df = valid_time_df.groupby(mat_col).agg(
                Orders=('Clean_Del', 'nunique'),
                Avg_Time=('Process_Time_Min', 'mean'),
                Total_Time=('Process_Time_Min', 'sum')
            ).reset_index()
            # Filtrujeme jen materiály, co se dělaly aspoň 2x
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

    # ==========================================
    # ZÁLOŽKA 3: OBALY (PACKAGING)
    # ==========================================
    with tab_pkg:
        st.markdown(f"**📦 {_t('Sjednocená analytika spotřeby obalů a časové náročnosti', 'Unified analytics of packaging usage and time effort')}**")
        st.caption(_t("Data jsou automaticky očištěna (sloučeny názvy jako 'CARTON-05' a 'CARTON-05-KARTON (1x)').", "Data is automatically cleaned (merging names like 'CARTON-05' and 'CARTON-05-KARTON (1x)')."))
        
        # Super-funkce pro výpočet statistik obalů
        def get_pkg_stats(df, col_name):
            if col_name not in df.columns: return pd.DataFrame()
            
            # Explode řádků (pokud má zakázka více obalů oddělených středníkem)
            temp_df = df[['Clean_Del', 'Process_Time_Min', 'pocet_hu', 'pocet_to', col_name]].copy()
            temp_df[col_name] = temp_df[col_name].astype(str).str.split(';')
            exploded = temp_df.explode(col_name)
            
            # Vyčištění názvů
            exploded[col_name] = exploded[col_name].apply(clean_pkg_name)
            exploded = exploded[exploded[col_name] != '']
            
            if exploded.empty: return pd.DataFrame()
            
            # Agregace dat pro daný vyčištěný obal
            stats = exploded.groupby(col_name).agg(
                Pouzito_Zakazek=('Clean_Del', 'nunique'),
                Total_Time=('Process_Time_Min', 'sum'),
                Total_HU=('pocet_hu', 'sum'),
                Total_Pcs=('pocet_to', 'sum') # Používáme počet picků (TO) jako proxy pro kusy materiálu
            ).reset_index()
            
            stats['Avg_Time_Order'] = np.where(stats['Pouzito_Zakazek'] > 0, stats['Total_Time'] / stats['Pouzito_Zakazek'], 0)
            stats['Avg_Time_HU'] = np.where(stats['Total_HU'] > 0, stats['Total_Time'] / stats['Total_HU'], 0)
            stats['Avg_Pcs'] = np.where(stats['Pouzito_Zakazek'] > 0, stats['Total_Pcs'] / stats['Pouzito_Zakazek'], 0)
            
            return stats.sort_values('Pouzito_Zakazek', ascending=False)

        def render_pkg_section(title, col_name, color):
            st.markdown(f"##### {title}")
            pkg_df = get_pkg_stats(valid_time_df, col_name)
            
            if not pkg_df.empty:
                col_pt, col_pg = st.columns([1.5, 1])
                with col_pt:
                    disp = pkg_df[[col_name, 'Pouzito_Zakazek', 'Avg_Time_Order', 'Avg_Time_HU', 'Avg_Pcs']].copy()
                    disp.columns = [_t("Vyčištěný název obalu", "Clean Packaging Name"), _t("Použito (Zakázek)", "Used (Orders)"), _t("Prům. čas na zakázku (Min)", "Avg Time/Order (Min)"), _t("Prům. čas na HU (Min)", "Avg Time/HU (Min)"), _t("Prům. ks materiálu (TO)", "Avg Mat Pcs (TO)")]
                    st.dataframe(disp.style.format({
                        _t("Prům. čas na zakázku (Min)", "Avg Time/Order (Min)"): "{:.1f}",
                        _t("Prům. čas na HU (Min)", "Avg Time/HU (Min)"): "{:.1f}",
                        _t("Prům. ks materiálu (TO)", "Avg Mat Pcs (TO)"): "{:.1f}"
                    }), hide_index=True, use_container_width=True)
                with col_pg:
                    fig = go.Figure(go.Bar(
                        x=pkg_df['Pouzito_Zakazek'].head(10), 
                        y=pkg_df[col_name].head(10), 
                        orientation='h', marker_color=color, 
                        text=pkg_df['Pouzito_Zakazek'].head(10), textposition='auto'
                    ))
                    fig.update_layout(**CHART_LAYOUT)
                    fig.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), margin=dict(t=0, b=0, l=0, r=0), height=300)
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(_t("Žádná data pro tento typ obalu.", "No data for this packaging type."))

        render_pkg_section(f"🗃️ {_t('Krabice (Cartons)', 'Cartons')}", 'Cartons', '#f59e0b')
        st.divider()
        render_pkg_section(f"🟦 {_t('KLT boxy', 'KLT Boxes')}", 'KLT', '#3b82f6')
        st.divider()
        render_pkg_section(f"🏭 {_t('Palety', 'Pallets')}", 'Palety', '#10b981')

    # ==========================================
    # ZÁLOŽKA 4: DETAILNÍ E2E REPORT
    # ==========================================
    with tab_detail:
        st.markdown(f"**🔍 {_t('Surová E2E data (Od regálu až k balícímu stolu)', 'Raw E2E data (From shelf to packing desk)')}**")
        
        # Výběr sloupců k zobrazení
        disp_cols = ['Clean_Del', 'Category_Full', 'Month', 'hlavni_fronta', 'pocet_lokaci']
        if 'CUSTOMER' in valid_time_df.columns: disp_cols.append('CUSTOMER')
        if mat_col in valid_time_df.columns: disp_cols.append(mat_col)
        
        disp_cols.extend(['pocet_to', 'pohyby_celkem', 'pocet_hu', 'Process_Time_Min', 'Min_per_HU'])
        
        if 'Shift' in valid_time_df.columns: disp_cols.append('Shift')
        
        disp_pack = valid_time_df[disp_cols].copy()
        disp_pack = disp_pack.sort_values('Process_Time_Min', ascending=False)
        
        # Přejmenování dynamicky
        rename_dict = {
            'Clean_Del': _t("Zakázka", "Order"),
            'Category_Full': _t("Kategorie", "Category"),
            'Month': _t("Měsíc", "Month"),
            'hlavni_fronta': _t("Hlavní fronta", "Main Queue"),
            'pocet_lokaci': _t("Navštívené lokace", "Visited Locations"),
            'CUSTOMER': _t("Zákazník", "Customer"),
            mat_col: _t("Hlavní materiál", "Main Material"),
            'pocet_to': _t("Pickováno TO", "Picked TOs"),
            'pohyby_celkem': _t("Fyzické pohyby", "Physical Moves"),
            'pocet_hu': _t("Vyfakturováno HU", "Billed HUs"),
            'Process_Time_Min': _t("Čas balení (Min)", "Packing Time (Min)"),
            'Min_per_HU': _t("Minut na 1 HU", "Minutes per 1 HU"),
            'Shift': _t("Směna", "Shift")
        }
        
        disp_pack.rename(columns=rename_dict, inplace=True)
        
        st.dataframe(disp_pack.style.format({
            _t("Čas balení (Min)", "Packing Time (Min)"): "{:.1f}", 
            _t("Minut na 1 HU", "Minutes per 1 HU"): "{:.1f}"
        }), hide_index=True, use_container_width=True)

    # ==========================================
    # ZÁLOŽKA 5: KOMPLEXNÍ MATICE (Data Science)
    # ==========================================
    with tab_complex:
        st.markdown(f"**🧠 {_t('Komplexní pohled: Zákazník -> Kategorie -> Balení', 'Complex View: Customer -> Category -> Packing')}**")
        st.caption(_t("Multidimenzionální Treemap graf. Velikost obdélníku ukazuje celkový strávený čas, barva ukazuje efektivitu (červená = velmi pomalé balení, zelená = rychlé). Kliknutím na obdélníky se můžete zanořit hlouběji.", "Multidimensional Treemap. Size represents total time spent, color represents efficiency (Red = very slow, Green = fast). Click to drill down."))
        
        if 'CUSTOMER' in valid_time_df.columns:
            # Příprava dat pro Treemap
            tree_df = valid_time_df.groupby(['CUSTOMER', 'Category_Full']).agg(
                Total_Time=('Process_Time_Min', 'sum'),
                Orders=('Clean_Del', 'nunique'),
                Total_HU=('pocet_hu', 'sum')
            ).reset_index()
            
            tree_df['Avg_Time'] = np.where(tree_df['Total_HU'] > 0, tree_df['Total_Time'] / tree_df['Total_HU'], 0)
            tree_df['Path'] = 'Vše'
            
            fig_tree = px.treemap(
                tree_df, 
                path=[px.Constant(_t("Všichni zákazníci", "All Customers")), 'CUSTOMER', 'Category_Full'],
                values='Total_Time',
                color='Avg_Time',
                color_continuous_scale='RdYlGn_r', # Převrácená škála: Zelená=nízký čas, Červená=vysoký čas
                hover_data=['Orders', 'Avg_Time']
            )
            fig_tree.update_layout(margin=dict(t=30, l=0, r=0, b=0), height=500)
            st.plotly_chart(fig_tree, use_container_width=True)
            
            st.markdown(f"**📊 {_t('Kontingenční tabulka (Pivot) Zákazníků a Kategorií', 'Pivot Table of Customers and Categories')}**")
            pivot_df = valid_time_df.pivot_table(
                index='CUSTOMER', 
                columns='Category_Full', 
                values='Process_Time_Min', 
                aggfunc='sum', 
                fill_value=0
            )
            
            # Formátování tabulky
            def color_gradient(val):
                if val == 0: return 'color: transparent'
                return ''
                
            st.dataframe(pivot_df.style.map(color_gradient).background_gradient(cmap='Blues', axis=None).format("{:.0f} min"), use_container_width=True)
        else:
            st.info(_t("Pro vykreslení komplexní matice chybí sloupec 'CUSTOMER'.", "Column 'CUSTOMER' missing to render complex matrix."))
