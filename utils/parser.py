"""
Binom CSV parser.
Обробляє експорт Binom Tracker — визначає тип кампанії,
парсить числові поля, повертає pandas DataFrame.
"""

import pandas as pd
import re
from io import StringIO
from typing import Optional


def detect_campaign_type(traffic_source: str, config: dict) -> str:
    """
    Визначає тип кампанії за значенням колонки Traffic Source.
    Пріоритет: android > ios > pwa > other.
    """
    if not isinstance(traffic_source, str):
        return 'other'

    src = traffic_source.lower().strip()
    td = config.get('type_detection', {})

    for kw in td.get('android_keywords', []):
        if kw.lower() in src:
            return 'android'
    for kw in td.get('ios_keywords', []):
        if kw.lower() in src:
            return 'ios'
    for kw in td.get('pwa_keywords', []):
        if kw.lower() in src:
            return 'pwa'
    for kw in td.get('other_keywords', []):
        if kw.lower() in src:
            return 'other'

    return 'other'


def _parse_number(val) -> float:
    """Парсить число з рядка Binom: '$1 234.56', '48.55%', '1,234'."""
    if pd.isna(val) or val == '' or val == '—' or val == '-':
        return 0.0
    s = str(val).strip().replace('$', '').replace(' ', '')
    s = s.replace('%', '')
    if ',' in s:
        if '.' in s:
            s = s.replace(',', '')
        else:
            if s.count(',') > 1:
                s = s.replace(',', '')
            else:
                s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_int(val) -> int:
    """Парсить ціле число."""
    if pd.isna(val) or val == '' or val == '—' or val == '-':
        return 0
    s = str(val).strip().replace(',', '')
    try:
        return int(float(s))
    except ValueError:
        return 0


# ----------------------------------------------------------------
# Мапінг назв колонок Binom (EN ← UK/RU/інші варіанти)
# ----------------------------------------------------------------
COLUMN_MAP = {
    'ID': ['ID', 'id', '№'],
    'Name': ['Name', 'Назва', 'Название', 'Имя', 'Campaign', 'Campaign Name',
             'Назва кампанії', 'Название кампании'],
    'Traffic Source': ['Traffic Source', 'TrafficSource', 'Source',
                       'Джерело трафіку', 'Джерело', 'Источник трафика', 'Источник',
                       'Трафик', 'Трафік'],
    'Clicks': ['Clicks', 'Кліки', 'Клики'],
    'Unique Clicks': ['Unique Clicks', 'UniqueClicks', 'Uniques',
                      'Унікальні кліки', 'Уникальные клики', 'Унікальні', 'Уникальные'],
    'Leads': ['Leads', 'Ліди', 'Лиды', 'Установки', 'Установлення',
              'Conversions', 'Конверсії', 'Конверсии'],
    'Deps': ['Deps', 'Deposits', 'Депозити', 'Депозиты', 'Депы',
             'Реєстрації', 'Регистрации', 'Registrations'],
    'Revenue': ['Revenue', 'Дохід', 'Доход', 'Income', 'Выручка', 'Виручка'],
    'Cost': ['Cost', 'Spend', 'Spent', 'Витрати', 'Расход', 'Расходы',
             'Затраты', 'Витрачено', 'Потрачено', 'Спенд'],
    'Profit': ['Profit', 'Прибуток', 'Прибыль'],
    'CR': ['CR', 'CVR', 'Конверсія', 'Конверсия'],
    'EPC': ['EPC'],
    'CPC': ['CPC'],
    'ROI': ['ROI', 'ROI %'],
    'reg2dep': ['reg2dep', 'reg2dep %', 'reg2dep%', 'Reg2Dep',
                'Рег2Деп', 'Рег в деп'],
    'inst2reg': ['inst2reg', 'inst2reg %', 'inst2reg%', 'Inst2Reg',
                 'Уст2Рег', 'Уст в рег'],
    'Campaign Owner': ['Campaign Owner', 'Owner', 'Власник', 'Владелец',
                       'Власник кампанії', 'Владелец кампании'],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Приводить назви колонок до стандартних англійських."""
    reverse_map = {}
    for standard, aliases in COLUMN_MAP.items():
        for alias in aliases:
            reverse_map[alias.lower().strip()] = standard

    new_columns = {}
    for col in df.columns:
        col_clean = col.strip()
        standard = reverse_map.get(col_clean) or reverse_map.get(col_clean.lower())
        if standard:
            new_columns[col] = standard
        else:
            new_columns[col] = col_clean

    df = df.rename(columns=new_columns)
    df = df.loc[:, ~df.columns.duplicated(keep='first')]
    return df


def load_config(path: str = 'config.yaml') -> dict:
    """Завантажує YAML-конфіг. Якщо файл не знайдено — пробує config.example.yaml."""
    import yaml
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # Пробуємо example.yaml (для Streamlit Cloud)
        example = path.replace('.yaml', '.example.yaml').replace('.yml', '.example.yml')
        with open(example, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)


def parse_binom_csv(file_or_path, config: Optional[dict] = None) -> pd.DataFrame:
    """
    Парсить Binom CSV (файл, шлях або StringIO) → DataFrame
    з доданими колонками campaign_type, CPI, CPR, CPL, CPA.
    """
    if config is None:
        config = load_config()

    # Читаємо CSV з автовизначенням роздільника
    if isinstance(file_or_path, bytes):
        content = file_or_path.decode('utf-8-sig')
    elif isinstance(file_or_path, str):
        with open(file_or_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    else:
        raw = file_or_path.read()
        if isinstance(raw, bytes):
            content = raw.decode('utf-8-sig')
        else:
            content = raw

    first_line = content.split('\n')[0] if '\n' in content else content
    commas = first_line.count(',')
    semicolons = first_line.count(';')
    tabs = first_line.count('\t')

    if semicolons > commas and semicolons > tabs:
        sep = ';'
    elif tabs > commas and tabs > semicolons:
        sep = '\t'
    else:
        sep = ','

    df = pd.read_csv(StringIO(content), sep=sep)

    # Нормалізуємо назви колонок (EN ← UK/RU)
    df.columns = [c.strip() for c in df.columns]
    df = _normalize_columns(df)

    # Парсимо числові поля
    numeric_cols = ['Clicks', 'Unique Clicks', 'Leads', 'Deps', 'Revenue',
                    'Cost', 'Profit', 'CR', 'EPC', 'CPC', 'ROI', 'inst2reg', 'reg2dep']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(_parse_number)

    int_cols = ['Clicks', 'Unique Clicks', 'Leads', 'Deps', 'ID']
    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].apply(_parse_int)

    # Визначаємо тип кампанії
    traffic_col = 'Traffic Source'
    if traffic_col not in df.columns:
        for alt in ['Traffic Source', 'Source', 'TrafficSource', 'Трафик', 'Джерело']:
            if alt in df.columns:
                traffic_col = alt
                break
        else:
            df[traffic_col] = ''
            print("⚠️  Колонку 'Traffic Source' не знайдено — тип кампанії визначено за назвою")

    df['campaign_type'] = df[traffic_col].apply(
        lambda x: detect_campaign_type(x, config)
    )

    # Рахуємо метрики (безпечно — перевіряємо наявність колонок)
    def _safe_div(a, b):
        try:
            if pd.notna(b) and b > 0:
                return round(a / b, 2)
        except (TypeError, ZeroDivisionError):
            pass
        return None

    has_leads = 'Leads' in df.columns
    has_deps = 'Deps' in df.columns
    has_cost = 'Cost' in df.columns
    has_revenue = 'Revenue' in df.columns

    if has_cost and has_leads:
        df['CPI'] = df.apply(lambda r: _safe_div(r['Cost'], r['Leads']), axis=1)
    else:
        df['CPI'] = None

    if has_cost and has_deps:
        df['CPR'] = df.apply(lambda r: _safe_div(r['Cost'], r['Deps']), axis=1)
    else:
        df['CPR'] = None

    if has_cost and has_leads:
        df['CPL'] = df.apply(lambda r: _safe_div(r['Cost'], r['Leads']), axis=1)
    else:
        df['CPL'] = None

    if has_cost and has_deps:
        df['CPA'] = df.apply(lambda r: _safe_div(r['Cost'], r['Deps']), axis=1)
    else:
        df['CPA'] = None

    if has_cost and has_revenue:
        df['ROI_calc'] = df.apply(
            lambda r: round(((r['Revenue'] - r['Cost']) / r['Cost']) * 100, 1)
            if r['Cost'] > 0 else 0.0,
            axis=1
        )
    else:
        df['ROI_calc'] = 0.0

    if 'ROI' in df.columns:
        df['ROI'] = df['ROI'].fillna(df['ROI_calc'])
    else:
        df['ROI'] = df['ROI_calc']

    # Зберігаємо діагностику
    required = ['Name', 'Cost', 'Leads', 'Deps', 'Revenue']
    missing = [c for c in required if c not in df.columns]
    df.attrs['parser_warnings'] = {
        'original_columns': list(df.columns),
        'missing_required': missing,
        'has_cost': has_cost,
        'has_leads': has_leads,
        'has_deps': has_deps,
        'has_revenue': has_revenue,
    }

    return df


def normalize_dataframe(df: pd.DataFrame, config: Optional[dict] = None) -> pd.DataFrame:
    """
    Застосовує ту саму нормалізацію, що й parse_binom_csv, але до вже
    завантаженого DataFrame (наприклад, з API).
    """
    if config is None:
        config = load_config()

    df.columns = [c.strip() for c in df.columns]
    df = _normalize_columns(df)

    for col in ['Clicks', 'Unique Clicks', 'Leads', 'Deps', 'Revenue',
                'Cost', 'Profit', 'CR', 'EPC', 'CPC', 'ROI', 'inst2reg', 'reg2dep']:
        if col in df.columns:
            df[col] = df[col].apply(_parse_number)
    for col in ['Clicks', 'Unique Clicks', 'Leads', 'Deps', 'ID']:
        if col in df.columns:
            df[col] = df[col].apply(_parse_int)

    traffic_col = None
    for alt in ['Traffic Source', 'Source', 'TrafficSource']:
        if alt in df.columns:
            traffic_col = alt
            break
    if traffic_col is None:
        df['Traffic Source'] = ''
        traffic_col = 'Traffic Source'

    df['campaign_type'] = df[traffic_col].apply(lambda x: detect_campaign_type(x, config))

    def _sd(a, b):
        try:
            if pd.notna(b) and b > 0:
                return round(a / b, 2)
        except (TypeError, ZeroDivisionError):
            pass
        return None

    has_cost = 'Cost' in df.columns
    has_leads = 'Leads' in df.columns
    has_deps = 'Deps' in df.columns
    has_revenue = 'Revenue' in df.columns

    if has_cost and has_leads:
        df['CPI'] = df.apply(lambda r: _sd(r['Cost'], r['Leads']), axis=1)
        df['CPL'] = df.apply(lambda r: _sd(r['Cost'], r['Leads']), axis=1)
    else:
        df['CPI'] = df['CPL'] = None

    if has_cost and has_deps:
        df['CPR'] = df.apply(lambda r: _sd(r['Cost'], r['Deps']), axis=1)
        df['CPA'] = df.apply(lambda r: _sd(r['Cost'], r['Deps']), axis=1)
    else:
        df['CPR'] = df['CPA'] = None

    if has_cost and has_revenue:
        df['ROI_calc'] = df.apply(
            lambda r: round(((r['Revenue'] - r['Cost']) / r['Cost']) * 100, 1)
            if r['Cost'] > 0 else 0.0, axis=1)
    else:
        df['ROI_calc'] = 0.0

    if 'ROI' in df.columns:
        df['ROI'] = df['ROI'].fillna(df['ROI_calc'])
    else:
        df['ROI'] = df['ROI_calc']

    df.attrs['parser_warnings'] = {
        'original_columns': list(df.columns),
        'missing_required': [c for c in ['Name', 'Cost', 'Leads', 'Deps', 'Revenue'] if c not in df.columns],
        'has_cost': has_cost, 'has_leads': has_leads,
        'has_deps': has_deps, 'has_revenue': has_revenue,
    }
    return df


def summarize_by_type(df: pd.DataFrame) -> dict:
    """Групує метрики за типом кампанії."""
    summary = {}
    for ctype in ['android', 'pwa', 'ios', 'other']:
        sub = df[df['campaign_type'] == ctype]
        if len(sub) == 0:
            continue
        total_cost = sub['Cost'].sum()
        total_rev = sub['Revenue'].sum()
        total_leads = sub['Leads'].sum()
        total_deps = sub['Deps'].sum()
        summary[ctype] = {
            'count': len(sub),
            'total_cost': total_cost,
            'total_revenue': total_rev,
            'profit': total_rev - total_cost,
            'roi': round(((total_rev - total_cost) / total_cost) * 100, 1) if total_cost > 0 else 0,
            'total_leads': total_leads,
            'total_deps': total_deps,
        }
    return summary


def extract_geo(name: str) -> str:
    """Витягує гео з назви кампанії: 'FB - TR - Zeus' → 'TR'."""
    if not isinstance(name, str):
        return '??'
    parts = name.split('-')
    if len(parts) >= 2:
        geo = parts[1].strip()
        if len(geo) == 2 and geo.isalpha() and geo.isupper():
            return geo
    return '??'
