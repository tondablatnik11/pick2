import streamlit as st
import pandas as pd
from modules.utils import t, safe_hu, safe_del

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@fast_render
def render_fu_compare(df_pick, billing_df, voll_set, queue_count_col):
    def _t(cs, en): return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>⚖️ {_t('Detailní porovnání: Fyzický proces (Skener) vs Fakturace (SAP)', 'Detailed Comparison: Physical Process vs Billing')}</h3><p>{_t('Tato záložka podrobně vysvětluje, proč nesedí čísla ze skeneru (fronty PI_PL_FU a PI_PL_FUOE) s konečnou fakturací, a jak Fakturační mozek zachraňuje přelepené palety.', 'This tab explains the differences between Scanner Data and Billing Data, and how the algorithm saves relabeled pallets.')}</p></div>", unsafe_allow_html=True)

    if billing_df is None or billing_df.empty or not voll_set:
        st.warning(_t("⚠️ Nejdříve navštivte záložku **Fakturace**, aby se provedly výpočty.", "⚠️ Please visit the **Billing** tab first to perform calculations."))
        return

    df_p = df_pick.copy()
    df_p['Clean_Del'] = df_p['Delivery'].apply(safe_del)
    df_p['Source_HU'] = df_p['Source storage unit'].apply(safe_hu)
    df_p['Dest_HU'] = df_p['Handling Unit'].apply(safe_hu)

    # Identifikace KLT obalů, které se nemají počítat jako celé palety
    c_su = 'Storage Unit Type' if 'Storage Unit Type' in df_p.columns else ('Type' if 'Type' in df_p.columns else None)
    if c_su:
        df_p['Is_KLT'] = df_p[c_su].astype(str).str.upper().isin(['K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'])
    else:
        df_p['Is_KLT'] = False

    # Identifikace podle Skeneru - odfiltrování KLT boxů
    df_p['Queue_UPPER'] = df_p['Queue'].astype(str).str.upper()
    df_p['Is_FU'] = (df_p['Queue_UPPER'] == 'PI_PL_FU') & (~df_p['Is_KLT'])
    df_p['Is_FUOE'] = (df_p['Queue_UPPER'] == 'PI_PL_FUOE') & (~df_p['Is_KLT'])
    df_p['Is_FU_Any'] = df_p['Is_FU'] | df_p['Is_FUOE']
    
    df_p['Is_Untouched'] = (df_p['Source_HU'] == df_p['Dest_HU']) & (df_p['Source_HU'] != '')

    # Identifikace podle Fakturace (Zda to mozek zařadil do Vollpalet)
    def check_voll(row):
        d = row['Clean_Del']
        return (d, row['Dest_HU']) in voll_set or (d, row['Source_HU']) in voll_set

    df_p['Is_Voll_Billed'] = df_p.apply(check_voll, axis=1)

    # Seskupení na úroveň konkrétního Úkolu (TO)
    to_agg = df_p.groupby(queue_count_col).agg(
        Delivery=('Clean_Del', 'first'),
        Queue=('Queue', 'first'),
        Queue_UPPER=('Queue_UPPER', 'first'),
        Storage_Unit_Type=(c_su, 'first') if c_su else ('Queue', 'first'),
        Is_FU_Any=('Is_FU_Any', 'max'),
        Is_Untouched=('Is_Untouched', 'min'),
        Is_Voll_Billed=('Is_Voll_Billed', 'max'),
        Source_HU=('Source_HU', 'first'),
        Dest_HU=('Dest_HU', 'first'),
        Material=('Material', 'first')
    ).reset_index()

    # Výpočty pro horní statistiky
    fu_tasks = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FU') & (to_agg['Is_FU_Any'])].shape[0]
    fu_untouched = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FU') & (to_agg['Is_FU_Any']) & (to_agg['Is_Untouched'])].shape[0]

    fuoe_tasks = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FUOE') & (to_agg['Is_FU_Any'])].shape[0]
    fuoe_untouched = to_agg[(to_agg['Queue_UPPER'] == 'PI_PL_FUOE') & (to_agg['Is_FU_Any']) & (to_agg['Is_Untouched'])].shape[0]

    billed_n_voll = billing_df[billing_df['Category_Full'] == 'N Vollpalette']['pocet_hu'].sum()
    billed_o_voll = billing_df[billing_df['Category_Full'].isin(['O Vollpalette', 'OE Vollpalette'])]['pocet_hu'].sum()

    st.markdown("### 📊 Souhrnná čísla ze Skeneru a Fakturace")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(_t("PI_PL_FU (Celkem úkolů na skeneru)", "PI_PL_FU (Total Scanner Tasks)"), int(fu_tasks))
        st.metric(_t("PI_PL_FUOE (Celkem úkolů na skeneru)", "PI_PL_FUOE (Total Scanner Tasks)"), int(fuoe_tasks))
    with c2:
        st.metric(_t("PI_PL_FU (Nepřebalováno)", "PI_PL_FU (Untouched)"), int(fu_untouched))
        st.metric(_t("PI_PL_FUOE (Nepřebalováno)", "PI_PL_FUOE (Untouched)"), int(fuoe_untouched))
    with c3:
        st.metric(_t("Fakturace: N Vollpalette", "Billing: N Vollpalette"), int(billed_n_voll))
        st.metric(_t("Fakturace: O/OE Vollpalette", "Billing: O/OE Vollpalette"), int(billed_o_voll))

    st.divider()
    st.markdown(f"### 🌉 {_t('Kde vznikají rozdíly? (Rozpad kategorií)', 'Where do differences come from? (Category Breakdown)')}")

    cat_a = to_agg[(to_agg['Is_FU_Any']) & (to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_b = to_agg[(to_agg['Is_FU_Any']) & (~to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_c = to_agg[(to_agg['Is_FU_Any']) & (~to_agg['Is_Voll_Billed'])].copy()
    cat_d = to_agg[(~to_agg['Is_FU_Any']) & (to_agg['Is_Voll_Billed'])].copy()

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.info(f"**🔵 {_t('Ideální palety', 'Ideal Pallets')} ({len(cat_a)})**\n\n{_t('Fronta FU/FUOE + Nepřelepeno + Vyfakturováno.', 'FU/FUOE Queue + Unchanged + Billed.')}")
    cc2.success(f"**🟢 {_t('Zachráněné palety', 'Saved Pallets')} ({len(cat_b)})**\n\n{_t('Fronta FU/FUOE + PŘELEPENO + Vyfakturováno.', 'FU/FUOE Queue + RELABELED + Billed.')}")
    cc3.error(f"**🔴 {_t('Ztracené palety', 'Lost Pallets')} ({len(cat_c)})**\n\n{_t('Fronta FU/FUOE + Nevyfakturováno.', 'FU/FUOE Queue + Not Billed.')}")
    cc4.warning(f"**🟡 {_t('Bonusové palety', 'Bonus Pallets')} ({len(cat_d)})**\n\n{_t('Obyčejná fronta + Vyfakturováno.', 'Normal Queue + Billed.')}")

    st.divider()

    t1, t2, t3, t4 = st.tabs([
        f"🔵 {_t('Ideální palety', 'Ideal Pallets')}",
        f"🟢 {_t('Zachráněné palety (Přelepené)', 'Saved Pallets (Relabeled)')}", 
        f"🔴 {_t('Ztracené palety (Zrušené/Rozbalené)', 'Lost Pallets (Cancelled/Unpacked)')}", 
        f"🟡 {_t('Bonusové palety (Z jiných front)', 'Bonus Pallets (From other queues)')}"
    ])

    cols_to_drop = ['Is_FU_Any', 'Queue_UPPER', 'Is_Untouched', 'Is_Voll_Billed']

    with t1:
        st.markdown(_t("Ideální proces: Skladník dostal úkol jít pro celou paletu, potvrdil původní štítek a v SAPu to bezpečně prošlo fakturací jako Vollpalette.", "Ideal process: Worker picked a full pallet, kept the label, and it was billed successfully."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU (Tuzemsko)")
            st.dataframe(cat_a[cat_a['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE (Export)")
            st.dataframe(cat_a[cat_a['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t2:
        st.markdown(_t("Skladník vytvořil u balení nové číslo palety (Dest HU se neshoduje se Source HU). Záložka 'Celé palety' by si myslela, že je to přebalené. **Fakturační mozek ale ve VEKP zjistil, že se obsah nezměnil a zachránil ji!**", "Worker relabeled the pallet. Basic tracking thinks it was unpacked, but the Billing engine confirmed unchanged content and saved it!"))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU (Tuzemsko)")
            st.dataframe(cat_b[cat_b['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE (Export)")
            st.dataframe(cat_b[cat_b['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t3:
        st.markdown(_t("Skener hlásil **PI_PL_FU / PI_PL_FUOE**, ale v systému VEKP chybí jako Vollpalette. Důvody: Zakázka byla stornována, odjela v jiný den, nebo ji balírna fyzicky rozbalila a smíchala s něčím jiným.", "Scanner reported FU, but it is missing in VEKP as Vollpalette. Cancelled, moved to another day, or physically unpacked."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### PI_PL_FU (Tuzemsko)")
            st.dataframe(cat_c[cat_c['Queue_UPPER'] == 'PI_PL_FU'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### PI_PL_FUOE (Export)")
            st.dataframe(cat_c[cat_c['Queue_UPPER'] == 'PI_PL_FUOE'].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)

    with t4:
        st.markdown(_t("Tyto úkoly byly odeslány jako normální pickování, ale aplikace zjistila, že jste do balení (VEKP) už nic nepřidali a expedovalo se to jako jeden kus. **Zákazník to tudíž zaplatí jako Vollpaletu.**", "These tasks were normal picking, but the app detected it shipped as one piece. Customer will be billed for a Vollpalette."))
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Běžné fronty (PI_PL, atd.)")
            st.dataframe(cat_d[~cat_d['Queue_UPPER'].isin(['PI_PL_OE', 'PI_PA_OE'])].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
        with col2:
            st.markdown("#### Exportní fronty (PI_PL_OE, atd.)")
            st.dataframe(cat_d[cat_d['Queue_UPPER'].isin(['PI_PL_OE', 'PI_PA_OE'])].drop(columns=cols_to_drop, errors='ignore'), use_container_width=True, hide_index=True)
