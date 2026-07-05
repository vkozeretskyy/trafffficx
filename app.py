"""
Traffic Dashboard — Streamlit web app.
Аналіз гемблінг-трафіку з Binom CSV.
Запуск: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import sys
import os
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(__file__))

from utils.parser import parse_binom_csv, load_config, summarize_by_type, normalize_dataframe
from utils.metrics import (
    overall_summary,
    rank_campaigns,
    top_campaigns_for_scale,
    campaigns_to_kill,
    campaign_status
)
from utils.alerts import check_alerts, alert_summary
from utils.reporter import generate_tl_report, generate_action_plan
from utils.binom_api import BinomAPIClient


# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="🎰 Traffic Dashboard",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🎰 Gambling Traffic Analyzer")
st.caption("Binom CSV → Аналіз → Рекомендації")

# ============================================================
# Load config
# ============================================================
@st.cache_resource
def get_config():
    return load_config(os.path.join(os.path.dirname(__file__), 'config.yaml'))

config = get_config()

# ============================================================
# News fetcher
# ============================================================
def fetch_gambling_news() -> list[dict]:
    """
    Завантажує новини про гемблінг та арбітраж трафіку.
    Джерела: Google News RSS + прямі RSS фідів.
    """
    news = []

    # Ключові слова для пошуку
    queries = [
        ("gambling ads Facebook 2026", "Meta Ads"),
        ("arbitrage traffic gambling", "Арбітраж"),
        ("iGaming affiliate marketing", "Партнерки"),
        ("google play casino apps policy", "Google Play"),
        ("Turkey gambling market 2026", "Туреччина"),
    ]

    for query, topic in queries:
        try:
            url = f"https://news.google.com/rss/search?q={quote(query)}&hl=uk&gl=UA&ceid=UA:uk"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.text)
            for item in root.findall('.//item')[:3]:
                title = item.find('title')
                link = item.find('link')
                pubdate = item.find('pubDate')
                source = item.find('source')

                title_text = title.text if title is not None else ''
                link_text = link.text if link is not None else '#'
                date_text = pubdate.text if pubdate is not None else ''
                source_text = source.text if source is not None else 'Google News'

                # Спрощуємо дату
                if date_text:
                    try:
                        dt = datetime.strptime(date_text, '%a, %d %b %Y %H:%M:%S %Z')
                        date_text = dt.strftime('%d.%m %H:%M')
                    except:
                        pass

                news.append({
                    'title': title_text,
                    'link': link_text,
                    'date': date_text,
                    'source': source_text,
                    'topic': topic,
                })
        except Exception:
            continue

    # Прибираємо дублікати за заголовком
    seen = set()
    unique = []
    for n in news:
        if n['title'] not in seen:
            seen.add(n['title'])
            unique.append(n)

    return unique[:20]


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.header("📁 Дані")

    # --- CSV Upload ---
    uploaded = st.file_uploader(
        "Завантаж Binom CSV",
        type=['csv'],
        help="Експорт із Binom: усі кампанії за період"
    )

    # --- Binom API ---
    st.divider()
    st.subheader("🔌 Binom API")

    api_enabled = st.checkbox(
        "Використовувати API",
        value=False,
        help="Завантажувати дані напряму з Binom через API"
    )

    api_base_url = None
    api_key = None
    api_date_from = None
    api_date_to = None
    api_load_clicked = False
    api_data = None

    if api_enabled:
        binom_cfg = config.get('binom_api', {})
        api_base_url = st.text_input(
            "Base URL",
            value=binom_cfg.get('base_url', ''),
            placeholder="https://tracker.example.com",
            help="Адреса твого трекера Binom"
        )
        api_key = st.text_input(
            "API Key",
            type="password",
            value=binom_cfg.get('api_key', ''),
            placeholder="Введи API-ключ",
            help="Береться в Binom: Налаштування → API"
        )

        col1, col2 = st.columns(2)
        with col1:
            api_date_from = st.date_input(
                "З",
                value=date.today() - timedelta(days=7),
                help="Початок періоду"
            )
        with col2:
            api_date_to = st.date_input(
                "По",
                value=date.today(),
                help="Кінець періоду"
            )

        api_load_clicked = st.button(
            "📥 Завантажити з API",
            use_container_width=True
        )

    report_date = st.date_input(
        "Дата звіту",
        value=date.today(),
        help="Дата, за яку рахується звіт"
    )

    st.divider()

    st.header("⚙️ Пороги")

    cpa_max = st.number_input(
        "Макс CPA ($)",
        value=int(config['thresholds']['cpa_max']),
        min_value=10, max_value=1000, step=10,
        help="Кампанії з CPA вище будуть позначені червоним"
    )

    roi_min = st.number_input(
        "Мін ROI для цілі (%)",
        value=int(config['thresholds']['roi_min']),
        min_value=0, max_value=100, step=5,
        help="ROI нижче — жовтий алерт"
    )

    roi_scale = st.number_input(
        "ROI для масштабування (%)",
        value=int(config['scaling']['roi_scale_threshold']),
        min_value=10, max_value=100, step=5,
        help="ROI вище — кампанія у список на масштаб"
    )

    budget_mult = st.slider(
        "Множник бюджету",
        min_value=1.1, max_value=3.0, value=float(config['scaling']['budget_multiplier']),
        step=0.1,
        help="У скільки разів збільшити бюджет при масштабуванні"
    )

    st.divider()

    analyze = st.button("🔍 Аналізувати", type="primary", use_container_width=True)

    st.divider()

    st.caption("v1.0 · macOS · Локально")

# ============================================================
# Helper: override config with sidebar values
# ============================================================
def get_active_config():
    cfg = config.copy()
    cfg['thresholds'] = config['thresholds'].copy()
    cfg['scaling'] = config['scaling'].copy()

    cfg['thresholds']['cpa_max'] = cpa_max
    cfg['thresholds']['roi_min'] = roi_min
    cfg['scaling']['roi_scale_threshold'] = roi_scale
    cfg['scaling']['budget_multiplier'] = budget_mult

    return cfg

# ============================================================
# Main content
# ============================================================

data_source = None
df_raw = None

if api_enabled and api_load_clicked and api_base_url and api_key:
    # --- Завантаження з Binom API ---
    cfg = get_active_config()
    with st.spinner(f"📥 Завантажуємо дані з Binom API ({api_date_from} → {api_date_to})..."):
        try:
            client = BinomAPIClient(
                base_url=api_base_url,
                api_key=api_key,
                timezone=cfg.get('binom_api', {}).get('timezone', 'Europe/Kyiv'),
                timeout=cfg.get('binom_api', {}).get('timeout', 30),
            )
            ok, msg = client.test_connection()
            if not ok:
                st.error(msg)
                st.stop()

            df_raw = client.fetch_campaigns(
                date_from=api_date_from.isoformat(),
                date_to=api_date_to.isoformat(),
            )
            st.success(f"✅ Завантажено {len(df_raw)} кампаній з API")
            data_source = 'api'
        except Exception as e:
            st.error(f"❌ Помилка API: {e}")
            st.stop()

elif uploaded and analyze:
    # --- Завантаження з CSV ---
    cfg = get_active_config()
    with st.spinner("📊 Парсимо Binom CSV..."):
        df_raw = parse_binom_csv(uploaded, cfg)
    data_source = 'csv'

if df_raw is not None:
    cfg = get_active_config()

    # Якщо дані з API — нормалізуємо
    if data_source == 'api':
        with st.spinner("🔧 Нормалізуємо дані API..."):
            df = normalize_dataframe(df_raw, cfg)
    else:
        df = df_raw

    if len(df) == 0:
        st.error("😕 CSV порожній або не розпізнано. Перевір формат експорту Binom.")
        st.stop()

    # --- Діагностика колонок ---
    warnings = df.attrs.get('parser_warnings', {})
    if warnings.get('missing_required'):
        with st.expander("⚠️ Діагностика CSV — не знайдено важливі колонки", expanded=True):
            st.warning(f"**Не знайдено:** {', '.join(warnings['missing_required'])}")
            st.write("**Колонки в CSV:**", warnings.get('original_columns', []))
            st.markdown("""
            **Що робити:**
            1. Перевір, що в експорті Binom вибрані **всі потрібні поля**
            2. Потрібні колонки: `Name`, `Cost`, `Leads`, `Deps`, `Revenue`
            3. Якщо колонки називаються інакше — **скинь мені сюди назви з твого CSV**
            """)

    # Фільтруємо нульові
    mask = pd.Series(False, index=df.index)
    if 'Cost' in df.columns:
        mask = mask | (df['Cost'] > 0)
    if 'Leads' in df.columns:
        mask = mask | (df['Leads'] > 0)
    df_active = df[mask].copy()

    if len(df_active) == 0:
        st.warning("Усі кампанії з нульовим спендом. Завантаж актуальний CSV.")
        st.stop()

    # Загальне зведення
    summary = overall_summary(df_active)
    alerts = check_alerts(df_active, cfg)
    alert_summ = alert_summary(alerts)

    # ============================================================
    # KPI-картки
    # ============================================================
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    profit = summary['profit']
    profit_delta_color = "normal" if profit >= 0 else "inverse"

    c1.metric("💰 Спенд", f"${summary['total_cost']:,.0f}")
    c2.metric("📈 Revenue", f"${summary['total_revenue']:,.0f}")
    c3.metric("💵 Profit",
              f"${profit:,.0f}",
              delta=f"{summary['roi']:+.1f}% ROI",
              delta_color=profit_delta_color)
    c4.metric("📊 Кампаній",
              summary['active_count'],
              delta=f"{alert_summ['affected_campaigns']} з алертами",
              delta_color="off")
    c5.metric("👥 Лідів", f"{summary['total_leads']:,}")
    c6.metric("💎 Депозитів", f"{summary['total_deps']:,}")

    # Банер алертів
    if alert_summ['red'] > 0:
        st.error(
            f"🚨 **{alert_summ['red']} червоних алертів** на "
            f"{alert_summ['affected_campaigns']} кампаніях — перевір вкладку «Алерти»"
        )
    elif alert_summ['yellow'] > 0:
        st.warning(f"🟡 {alert_summ['yellow']} попереджень — див. вкладку «Алерти»")
    else:
        st.success("✅ Усі кампанії в порядку, алертів немає")

    # ============================================================
    # Вкладки
    # ============================================================
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📱 Android App",
        "🌐 PWA / Web",
        "🍏 iOS",
        "🚨 Алерти",
        "📋 Звіт для ТЛ",
        "📅 План на сьогодні",
        "📰 Новини"
    ])

    # ----- Tab 1: Android App -----
    with tab1:
        android_df = rank_campaigns(df_active, cfg, 'android')
        if len(android_df) > 0:
            st.subheader(f"📱 Android App — {len(android_df)} кампаній")

            display = android_df.copy()
            for col in ['Cost', 'Revenue']:
                if col in display.columns:
                    display[col] = display[col].apply(lambda x: f"${x:,.0f}")
            if 'ROI' in display.columns:
                display['ROI'] = display['ROI'].apply(lambda x: f"{x:+.1f}%")
            for col in ['CPI', 'CPR', 'CPA']:
                if col in display.columns:
                    display[col] = display[col].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) and x else "—"
                    )
            display['Статус'] = display['status_emoji'] + ' ' + display['status_label']

            show_cols = [c for c in [
                'Name', 'Traffic Source', 'Cost', 'Leads', 'Deps',
                'CPI', 'CPR', 'CPA', 'Revenue', 'ROI', 'Статус'
            ] if c in display.columns]

            st.dataframe(
                display[show_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Name': 'Кампанія',
                    'Traffic Source': 'Джерело',
                    'Cost': 'Спенд',
                    'Leads': 'Встановлення',
                    'Deps': 'Депозити',
                    'Revenue': 'Дохід',
                    'ROI': 'ROI',
                    'CPI': 'CPI',
                    'CPR': 'CPR',
                    'CPA': 'CPA',
                    'Статус': st.column_config.TextColumn('Статус', width='small'),
                }
            )

            android_summ = summarize_by_type(df_active).get('android', {})
            if android_summ:
                st.caption(
                    f"Спенд: ${android_summ.get('total_cost', 0):,.0f} | "
                    f"Дохід: ${android_summ.get('total_revenue', 0):,.0f} | "
                    f"ROI: {android_summ.get('roi', 0):+.1f}%"
                )
        else:
            st.info("Немає Android-кампаній у даних")

    # ----- Tab 2: PWA -----
    with tab2:
        pwa_df = rank_campaigns(df_active, cfg, 'pwa')
        if len(pwa_df) > 0:
            st.subheader(f"🌐 PWA / Web — {len(pwa_df)} кампаній")

            display = pwa_df.copy()
            for col in ['Cost', 'Revenue']:
                if col in display.columns:
                    display[col] = display[col].apply(lambda x: f"${x:,.0f}")
            if 'ROI' in display.columns:
                display['ROI'] = display['ROI'].apply(lambda x: f"{x:+.1f}%")
            for col in ['CPL', 'CPA']:
                if col in display.columns:
                    display[col] = display[col].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) and x else "—"
                    )
            display['Статус'] = display['status_emoji'] + ' ' + display['status_label']

            show_cols = [c for c in [
                'Name', 'Traffic Source', 'Cost', 'Leads', 'Deps',
                'CPL', 'CPA', 'Revenue', 'ROI', 'Статус'
            ] if c in display.columns]

            st.dataframe(
                display[show_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Name': 'Кампанія',
                    'Traffic Source': 'Джерело',
                    'Cost': 'Спенд',
                    'Leads': 'Ліди',
                    'Deps': 'Реєстрації',
                    'Revenue': 'Дохід',
                    'ROI': 'ROI',
                    'CPL': 'CPL',
                    'CPA': 'CPA',
                    'Статус': st.column_config.TextColumn('Статус', width='small'),
                }
            )

            pwa_summ = summarize_by_type(df_active).get('pwa', {})
            if pwa_summ:
                st.caption(
                    f"Спенд: ${pwa_summ.get('total_cost', 0):,.0f} | "
                    f"Дохід: ${pwa_summ.get('total_revenue', 0):,.0f} | "
                    f"ROI: {pwa_summ.get('roi', 0):+.1f}%"
                )
        else:
            st.info("Немає PWA-кампаній у даних")

    # ----- Tab 3: iOS -----
    with tab3:
        ios_df = rank_campaigns(df_active, cfg, 'ios')
        if len(ios_df) > 0:
            st.subheader(f"🍏 iOS — {len(ios_df)} кампаній")

            display = ios_df.copy()
            for col in ['Cost', 'Revenue']:
                if col in display.columns:
                    display[col] = display[col].apply(lambda x: f"${x:,.0f}")
            if 'ROI' in display.columns:
                display['ROI'] = display['ROI'].apply(lambda x: f"{x:+.1f}%")
            for col in ['CPI', 'CPA']:
                if col in display.columns:
                    display[col] = display[col].apply(
                        lambda x: f"${x:.2f}" if pd.notna(x) and x else "—"
                    )
            display['Статус'] = display['status_emoji'] + ' ' + display['status_label']

            show_cols = [c for c in [
                'Name', 'Traffic Source', 'Cost', 'Leads', 'Deps',
                'CPI', 'CPA', 'Revenue', 'ROI', 'Статус'
            ] if c in display.columns]

            st.dataframe(
                display[show_cols],
                use_container_width=True,
                hide_index=True,
            )

            ios_summ = summarize_by_type(df_active).get('ios', {})
            if ios_summ:
                st.caption(
                    f"Спенд: ${ios_summ.get('total_cost', 0):,.0f} | "
                    f"ROI: {ios_summ.get('roi', 0):+.1f}%"
                )
        else:
            st.info("Немає iOS-кампаній у даних")

    # ----- Tab 4: Алерти -----
    with tab4:
        st.subheader(f"🚨 Алерти — {alert_summ['total']} шт.")

        if alert_summ['red'] > 0:
            st.error(f"🔴 Червоні ({alert_summ['red']})")
            for a in alerts:
                if a['severity'] == 'red':
                    st.markdown(f"- **{a['campaign']}**: {a['message']}")

        if alert_summ['yellow'] > 0:
            st.warning(f"🟡 Жовті ({alert_summ['yellow']})")
            for a in alerts:
                if a['severity'] == 'yellow':
                    st.markdown(f"- **{a['campaign']}**: {a['message']}")

        if alert_summ['total'] == 0:
            st.success("Немає алертів — усі кампанії в порядку ✅")

    # ----- Tab 5: Звіт для ТЛ -----
    with tab5:
        st.subheader("📋 Звіт для Team Lead")

        tl_text = generate_tl_report(df_active, cfg, report_date)
        st.markdown(tl_text)

        st.download_button(
            label="📥 Скопіювати в буфер / зберегти",
            data=tl_text,
            file_name=f"report_{report_date.strftime('%Y%m%d')}.txt",
            mime="text/plain",
            use_container_width=True
        )

    # ----- Tab 6: План на сьогодні -----
    with tab6:
        st.subheader("📅 План на сьогодні")

        action_plan = generate_action_plan(df_active, cfg)
        st.markdown(action_plan)

    # ----- Tab 7: Новини -----
    with tab7:
        st.subheader("📰 Новини гемблінгу та арбітражу")

        if st.button("🔄 Оновити новини", use_container_width=True, key="news_refresh_tab"):
            st.session_state.news_data = None  # скидаємо кеш

        if 'news_data' not in st.session_state or st.session_state.news_data is None:
            with st.spinner("Завантажуємо новини..."):
                st.session_state.news_data = fetch_gambling_news()

        news = st.session_state.news_data

        if news:
            for item in news:
                with st.container():
                    st.markdown(f"**[{item['title']}]({item['link']})**")
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.caption(item.get('source', '') + ' · ' + item.get('date', ''))
                    with col2:
                        st.caption(f"🔑 {item.get('topic', '')}")
                    st.divider()
        else:
            st.info("Не вдалося завантажити новини. Перевір підключення до інтернету.")

else:
    # Порожній стан — дві колонки: інфо + новини
    col_info, col_news = st.columns([3, 2])

    with col_info:
        st.info(
            """
            ### 👋 Ласкаво просимо до Traffic Dashboard!

            1. **Завантаж Binom CSV** у боковій панелі ліворуч
            2. Налаштуй пороги під свій оффер
            3. Натисни **«Аналізувати»**

            #### Що отримаєш:
            - 📊 **Зведення** по всіх кампаніях (спенд, ROI, CPA)
            - 📱🌐 **Розбивку** по Android / PWA / iOS
            - 🚨 **Алерти** — які кампанії в мінус або вище CPA
            - 📋 **Звіт для ТЛ** — скопіював і надіслав
            - 📅 **План на день** — що масштабувати, що вимикати
            """
        )

        with st.expander("📋 Приклад очікуваного результату"):
            st.markdown("""
            ```
            📅 19.06.2026

            💰 Спенд: $17 167 | Revenue: $20 329 | Profit: +$3 162 | ROI: +18.4%

            🟢 TR — плюс (спенд $8,212, ROI +15.9%)
              📱 Android: Zeus +124% ✅, Zeus 77 +38% ✅
              🌐 PWA: skak Zeus +23.4% ✅

            🔴 UK — мінус (спенд $2,741, ROI -12.4%)
              ❌ SKAK -12.4%
            ```
            """)

    with col_news:
        st.subheader("📰 Новини арбітражу")
        if st.button("🔄 Оновити", use_container_width=True, key="news_refresh_home"):
            st.session_state.home_news = None

        if 'home_news' not in st.session_state or st.session_state.home_news is None:
            with st.spinner("Завантажуємо..."):
                st.session_state.home_news = fetch_gambling_news()

        news = st.session_state.home_news
        if news:
            for item in news[:8]:
                st.markdown(f"**[{item['title']}]({item['link']})**")
                st.caption(f"{item.get('source', '')} · {item.get('date', '')} · {item.get('topic', '')}")
        else:
            st.caption("Немає з'єднання з інтернетом")

# ============================================================
# Footer
# ============================================================
st.divider()
st.caption("Traffic Dashboard v1.0 · Binom CSV → Аналіз · Дані локально · macOS")
