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

    st.markdown(f"<div class='section-header'><h3>⚖️ {_t('Detailní porovnání: Fyzický proces (Skener) vs Fakturace (SAP)', 'Detailed Comparison: Physical Process vs Billing')}</h3><p>{_t('Tato záložka podrobně vysvětluje, proč nesedí čísla ze skeneru (fronty PI_PL_FU) s konečnou fakturací, a jak Fakturační mozek zachraňuje přelepené palety.', 'This tab explains the differences between Scanner Data and Billing Data, and how the algorithm saves relabeled pallets.')}</p></div>", unsafe_allow_html=True)

    if billing_df is None or billing_df.empty or not voll_set:
        st.warning(_t("⚠️ Nejdříve navštivte záložku **Fakturace**, aby se provedly výpočty.", "⚠️ Please visit the **Billing** tab first to perform calculations."))
        return

    df_p = df_pick.copy()
    df_p['Clean_Del'] = df_p['Delivery'].apply(safe_del)
    df_p['Source_HU'] = df_p['Source storage unit'].apply(safe_hu)
    df_p['Dest_HU'] = df_p['Handling Unit'].apply(safe_hu)

    # Identifikace podle Skeneru
    df_p['Is_FU_Queue'] = df_p['Queue'].astype(str).str.upper().isin(['PI_PL_FU', 'PI_PL_FUOE'])
    df_p['Is_Untouched'] = (df_p['Source_HU'] == df_p['Dest_HU']) & (df_p['Source_HU'] != '')

    # Identifikace podle Fakturace (Zda to mozek zařadil do Vollpalet)
    def check_voll(row):
        d = row['Clean_Del']
        if (d, row['Dest_HU']) in voll_set or (d, row['Source_HU']) in voll_set: return True
        return False

    df_p['Is_Voll_Billed'] = df_p.apply(check_voll, axis=1)

    # Seskupení na úroveň konkrétního Úkolu (TO)
    to_agg = df_p.groupby(queue_count_col).agg(
        Delivery=('Clean_Del', 'first'),
        Queue=('Queue', 'first'),
        Is_FU_Queue=('Is_FU_Queue', 'max'),
        Is_Untouched=('Is_Untouched', 'min'),
        Is_Voll_Billed=('Is_Voll_Billed', 'max'),
        Source_HU=('Source_HU', 'first'),
        Dest_HU=('Dest_HU', 'first'),
        Material=('Material', 'first')
    ).reset_index()

    fu_scanner = to_agg['Is_FU_Queue'].sum()
    fu_untouched = to_agg[(to_agg['Is_FU_Queue']) & (to_agg['Is_Untouched'])].shape[0]

    # Zúčtované Vollpalety přímo z výsledků Fakturace
    billed_voll = billing_df[billing_df['Category_Full'].str.contains('Vollpalette', na=False)]['pocet_hu'].sum()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(_t("1. Skener: Úkoly PI_PL_FU", "1. Scanner: PI_PL_FU Tasks"), int(fu_scanner), help=_t("Skladník dostal úkol 'běž pro celou paletu'.", "Worker got task to pick full pallet."))
    with c2:
        st.metric(_t("2. Skener: Nepřebalováno", "2. Scanner: Untouched"), int(fu_untouched), help=_t("Skladník pípnul na chlup stejný štítek.", "Worker scanned exactly the same HU label."))
    with c3:
        st.metric(_t("3. SAP Fakturace: Vollpalette", "3. SAP Billing: Vollpalette"), int(billed_voll), help=_t("Skutečně vyfakturované palety u zákazníka.", "Actually billed pallets for the customer."))

    st.divider()
    st.markdown(f"### 🌉 {_t('Kde vznikají rozdíly? (Rozpad kategorií)', 'Where do differences come from? (Category Breakdown)')}")

    cat_a = to_agg[(to_agg['Is_FU_Queue']) & (to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_b = to_agg[(to_agg['Is_FU_Queue']) & (~to_agg['Is_Untouched']) & (to_agg['Is_Voll_Billed'])].copy()
    cat_c = to_agg[(to_agg['Is_FU_Queue']) & (~to_agg['Is_Voll_Billed'])].copy()
    cat_d = to_agg[(~to_agg['Is_FU_Queue']) & (to_agg['Is_Voll_Billed'])].copy()

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.info(f"**A. {_t('Ideální palety', 'Ideal Pallets')} ({len(cat_a)})**\n\n{_t('Fronta FU + Nepřelepeno + Vyfakturováno.', 'FU Queue + Unchanged + Billed.')}")
    cc2.success(f"**B. {_t('Zachráněné palety', 'Saved Pallets')} ({len(cat_b)})**\n\n{_t('Fronta FU + PŘELEPENO + Vyfakturováno.', 'FU Queue + RELABELED + Billed.')}")
    cc3.error(f"**C. {_t('Ztracené palety', 'Lost Pallets')} ({len(cat_c)})**\n\n{_t('Fronta FU + Nevyfakturováno.', 'FU Queue + Not Billed.')}")
    cc4.warning(f"**D. {_t('Bonusové palety', 'Bonus Pallets')} ({len(cat_d)})**\n\n{_t('Obyčejná fronta + Vyfakturováno.', 'Normal Queue + Billed.')}")

    st.divider()

    t1, t2, t3 = st.tabs([
        f"🟢 {_t('Zachráněné palety (Přelepené)', 'Saved Pallets (Relabeled)')}", 
        f"🔴 {_t('Ztracené palety (Zrušené/Rozbalené)', 'Lost Pallets (Cancelled/Unpacked)')}", 
        f"🟡 {_t('Bonusové palety (Z jiných front)', 'Bonus Pallets (From other queues)')}"
    ])

    with t1:
        st.markdown(_t("Tyto úkoly poslal skener jako **PI_PL_FU**, ale skladník vytvořil nové číslo palety (Dest HU se neshoduje se Source HU). Záložka 'Celé palety' je proto vyřadila. **Ale Fakturační mozek je ve VEKP našel a zachránil je pro fakturaci!**", "These tasks were PI_PL_FU, but the worker created a new HU. The Billing engine found them in VEKP and saved them!"))
        st.dataframe(cat_b, use_container_width=True, hide_index=True)
    with t2:
        st.markdown(_t("Skener hlásil **PI_PL_FU**, ale v systému VEKP chybí jako Vollpalette. Zakázka byla stornována, odjela v jiný den, nebo ji balírna fyzicky rozbalila.", "Scanner reported PI_PL_FU, but it is missing in VEKP as Vollpalette. Cancelled, moved, or unpacked."))
        st.dataframe(cat_c, use_container_width=True, hide_index=True)
    with t3:
        st.markdown(_t("Tyto úkoly byly normální pickování (např. **PI_PL**), ale aplikace zjistila, že jste do balení (VEKP) už nic nepřidali a expedovalo se to jako jeden kus. Zákazník to zaplatí jako Vollpaletu.", "These tasks were normal picking (e.g. PI_PL), but the app detected it shipped as one piece. Customer pays for Vollpalette."))
        st.dataframe(cat_d, use_container_width=True, hide_index=True)
