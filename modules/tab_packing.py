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

    st.markdown(f"<div class='section-header'><h3>📦 {_t('Analýza balícího procesu (OE-Times)', 'Packing Process Analysis (OE-Times)')}</h3><p>{_t('Srovnání času stráveného u balícího stolu s počtem a typem vyfakturovaných jednotek.', 'Comparison of time spent at the packing station with the number and type of billed units.')}</p></div>", unsafe_allow_html=True)

    if df_oe is None or df_oe.empty:
        st.info(_t("Pro tuto záložku je nutné nahrát soubor OE-Times v Admin zóně.", "Upload the OE-Times file in Admin Zone to use this tab."))
        return

    if billing_df is None or billing_df.empty:
        st.warning(_t("Pro propojení chybí data z Fakturace (VEKP). Aplikace nejprve potřebuje načíst data z předchozích záložek.", "Billing data (VEKP) missing for correlation. App needs data from previous tabs first."))
        return

    # OBRANA PROTI UNBOUND LOCAL ERROR: Bezpečná inicializace prázdných tabulek
    e2e_df = pd.DataFrame()
    valid_time_df = pd.DataFrame()

    # Příprava dat pro čisté párování
    df_oe_clean = df_oe.copy()
    df_oe_clean['Clean_Del'] = df_oe_clean['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    
    bill_clean = billing_df.copy()
    bill_clean['Clean_Del'] = bill_clean['Clean_Del_Merge'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')

    # Spojení fakturačních dat a časů balení
    pack_df = pd.merge(bill_clean, df_oe_clean, on='Clean_Del', how='inner')
    e2e_df = pack_df.copy() # Uložení pro jistotu

    if pack_df.empty:
        st.error(_t("Nepodařilo se spárovat žádné zakázky z OE-Times s daty ze skladu/fakturace (Zkontrolujte formát čísel Delivery).", "Failed to match any orders from OE-Times with warehouse/billing data."))
        return

    # Očištění dat od nesmyslných časů (např. 0 minut nebo chyby zápisu)
    valid_time_df = pack_df[pack_df['Process_Time_Min'] > 0].copy()

    if valid_time_df.empty:
         st.warning(_t("Data se sice spojila, ale u žádné zakázky není zaznamenán platný procesní čas (> 0 min).", "Data matched, but no valid process time (> 0 min) found."))
         return

    # Výpočet efektivity (Minut na 1 HU)
    valid_time_df['Min_per_HU'] = np.where(valid_time_df['pocet_hu'] > 0, valid_time_df['Process_Time_Min'] / valid_time_df['pocet_hu'], valid_time_df['Process_Time_Min'])
    
    # --- METRIKY ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True): st.metric(_t("Spárovaných zakázek", "Matched Orders"), f"{len(valid_time_df):,}")
    with c2:
        with st.container(border=True): st.metric(_t("Celkový čas balení", "Total Packing Time"), f"{valid_time_df['Process_Time_Min'].sum() / 60:.1f} h")
    with c3:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 zakázku", "Avg Time per Order"), f"{valid_time_df['Process_Time_Min'].mean():.1f} min")
    with c4:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 HU", "Avg Time per HU"), f"{valid_time_df['Min_per_HU'].mean():.1f} min")

    st.divider()

    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.markdown(f"**⏱️ {_t('Náročnost balení dle kategorie (Minut na 1 vyfakturovanou HU)', 'Packing Effort by Category (Minutes per 1 billed HU)')}**")
        cat_time = valid_time_df.groupby('Category_Full').agg(
            total_time=('Process_Time_Min', 'sum'),
            total_hu=('pocet_hu', 'sum'),
            zakazek=('Clean_Del', 'count')
        ).reset_index()
        
        cat_time['Avg_Min_HU'] = np.where(cat_time['total_hu'] > 0, cat_time['total_time'] / cat_time['total_hu'], 0)
        
        # Odstraníme nuly a seřadíme (Nejpomalejší nahoře)
        cat_time = cat_time[cat_time['Avg_Min_HU'] > 0].sort_values('Avg_Min_HU', ascending=True)

        if not cat_time.empty:
            fig_time = go.Figure(go.Bar(
                x=cat_time['Avg_Min_HU'], 
                y=cat_time['Category_Full'], 
                orientation='h',
                marker_color='#f59e0b', 
                text=cat_time['Avg_Min_HU'].round(1).astype(str) + ' min', 
                textposition='auto'
            ))
            fig_time.update_layout(**CHART_LAYOUT)
            fig_time.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Minut na 1 HU", "Minutes per 1 HU"))
            st.plotly_chart(fig_time, use_container_width=True)

    with col_g2:
        # Zobrazit trend v čase (pokud máme data o měsících ze SAPu)
        if 'Month' in valid_time_df.columns:
            st.markdown(f"**📈 {_t('Měsíční trend průměrného času balení', 'Monthly Trend of Average Packing Time')}**")
            trend_time = valid_time_df.groupby('Month').agg(
                avg_time_order=('Process_Time_Min', 'mean'),
                avg_time_hu=('Min_per_HU', 'mean')
            ).reset_index().sort_values('Month')

            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(
                x=trend_time['Month'], y=trend_time['avg_time_order'], 
                name=_t('Na zakázku (Min)', 'Per Order (Min)'), 
                mode='lines+markers+text', text=trend_time['avg_time_order'].round(1), textposition='top center',
                line=dict(color='#3b82f6', width=3), marker=dict(size=8)
            ))
            fig_trend.add_trace(go.Scatter(
                x=trend_time['Month'], y=trend_time['avg_time_hu'], 
                name=_t('Na 1 HU (Min)', 'Per 1 HU (Min)'), 
                mode='lines+markers+text', text=trend_time['avg_time_hu'].round(1), textposition='bottom center',
                line=dict(color='#10b981', width=3), marker=dict(size=8)
            ))
            fig_trend.update_layout(**CHART_LAYOUT)
            fig_trend.update_layout(yaxis_title=_t("Minuty", "Minutes"))
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            # Alternativa: Pokud není měsíc, ukážeme aspoň spotřebu krabic
            st.markdown(f"**📦 {_t('Krabice použité na balení (Dle OE-Times)', 'Boxes Used for Packing (per OE-Times)')}**")
            if 'Cartons' in valid_time_df.columns:
                all_cartons = valid_time_df['Cartons'].dropna().astype(str).str.split(';').explode().str.strip()
                carton_counts = all_cartons[all_cartons != ''].value_counts().head(10).reset_index()
                carton_counts.columns = [_t('Obal', 'Packaging'), _t('Použito (ks)', 'Used (pcs)')]
                st.dataframe(carton_counts, hide_index=True, use_container_width=True)
            else:
                st.info(_t("Detailní data o použitých obalech (Cartons) nejsou v datech k dispozici.", "Detailed packaging data (Cartons) not available in data."))

    # --- TABULKA DETAILŮ ---
    st.divider()
    st.markdown(f"**🔍 {_t('Detailní report balení (Nejpomalejší zakázky u stolu)', 'Detailed Packing Report (Slowest Orders at Desk)')}**")
    
    disp_pack = valid_time_df[['Clean_Del', 'Category_Full', 'Process_Time_Min', 'pocet_to', 'pocet_hu', 'Min_per_HU']].copy()
    disp_pack = disp_pack.sort_values('Process_Time_Min', ascending=False).head(100)
    disp_pack.columns = [
        _t("Zakázka", "Order"), 
        _t("Kategorie", "Category"), 
        _t("Čas (Min)", "Time (Min)"),
        _t("Počet TO (Ze skladu)", "TO Count (From WH)"), 
        _t("Vyfakturováno HU", "Billed HU"), 
        _t("Čas na 1 HU", "Time per 1 HU")
    ]
    
    st.dataframe(disp_pack.style.format({
        _t("Čas (Min)", "Time (Min)"): "{:.1f}", 
        _t("Čas na 1 HU", "Time per 1 HU"): "{:.1f}"
    }), hide_index=True, use_container_width=True)
