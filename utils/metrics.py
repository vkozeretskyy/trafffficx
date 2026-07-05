"""
Модуль розрахунку метрик.
Приймає DataFrame з parser.py, повертає зведення, рейтинги, статуси.
"""

import pandas as pd
from typing import Optional


def get_decision_metric(campaign_type: str, config: dict) -> str:
    """Повертає ключову метрику для типу кампанії (CPI/CPL)."""
    offer = config.get('offer_types', {}).get(campaign_type, {})
    return offer.get('decision_metric', 'CPA')


def campaign_status(row: pd.Series, config: dict) -> tuple:
    """
    Повертає (emoji, label) для кампанії.
    Правила:
      - ROI > 20%   → 🟢 МАСШТАБУВАТИ
      - ROI 0-20%   → 🟡 ТЕСТУВАТИ
      - ROI < 0%    → 🔴 ВИМИКАТИ
      - Cost = 0    → ⚪ БЕЗ СПЕНДУ
    """
    roi = row.get('ROI', 0)
    cost = row.get('Cost', 0)

    if cost == 0:
        return ('⚪', 'БЕЗ СПЕНДУ')
    if roi > config['scaling']['roi_scale_threshold']:
        return ('🟢', 'МАСШТАБУВАТИ')
    elif roi >= 0:
        return ('🟡', 'ТЕСТУВАТИ')
    else:
        return ('🔴', 'ВИМИКАТИ')


def rank_campaigns(df: pd.DataFrame, config: dict,
                   campaign_type: Optional[str] = None) -> pd.DataFrame:
    """
    Ранжує кампанії: спочатку за ROI (спад), потім за спендом (спад).
    Повертає DataFrame з колонками для відображення.
    """
    sub = df.copy()
    if campaign_type:
        sub = sub[sub['campaign_type'] == campaign_type]

    sub = sub[(sub['Cost'] > 0) | (sub['Leads'] > 0)].copy()
    if len(sub) == 0:
        return pd.DataFrame()

    sub = sub.sort_values(['ROI', 'Cost'], ascending=[False, False])

    sub['status_emoji'], sub['status_label'] = zip(
        *sub.apply(lambda r: campaign_status(r, config), axis=1)
    )

    display_cols = ['Name', 'Traffic Source', 'Cost', 'Leads', 'Deps',
                    'Revenue', 'ROI', 'CPI', 'CPR', 'CPL', 'CPA',
                    'status_emoji', 'status_label', 'campaign_type']

    available = [c for c in display_cols if c in sub.columns]

    return sub[available]


def overall_summary(df: pd.DataFrame) -> dict:
    """Загальне зведення по всіх кампаніях."""
    total_cost = df['Cost'].sum()
    total_rev = df['Revenue'].sum()
    total_leads = df['Leads'].sum()
    total_deps = df['Deps'].sum()

    return {
        'total_cost': total_cost,
        'total_revenue': total_rev,
        'profit': total_rev - total_cost,
        'roi': round(((total_rev - total_cost) / total_cost) * 100, 1) if total_cost > 0 else 0,
        'total_leads': total_leads,
        'total_deps': total_deps,
        'campaign_count': len(df),
        'active_count': len(df[df['Cost'] > 0]),
    }


def daily_comparison(today_df: pd.DataFrame, yesterday_df: Optional[pd.DataFrame] = None) -> dict:
    """Порівняння день-до-дня."""
    today_summary = overall_summary(today_df)
    result = {'today': today_summary}

    if yesterday_df is not None and len(yesterday_df) > 0:
        yesterday_summary = overall_summary(yesterday_df)
        result['yesterday'] = yesterday_summary

        for key in ['total_cost', 'total_revenue', 'profit', 'total_leads', 'total_deps']:
            t_val = today_summary.get(key, 0)
            y_val = yesterday_summary.get(key, 0)
            if y_val != 0:
                result[f'{key}_change_pct'] = round(((t_val - y_val) / y_val) * 100, 1)
            else:
                result[f'{key}_change_pct'] = 0

    return result


def top_campaigns_for_scale(df: pd.DataFrame, config: dict, top_n: int = 5) -> pd.DataFrame:
    """
    Повертає топ-N кампаній-кандидатів на масштабування.
    Критерії: ROI > порогу, є спенд > 0.
    """
    threshold = config['scaling']['roi_scale_threshold']
    sub = df[(df['ROI'] > threshold) & (df['Cost'] > 0)].copy()
    sub = sub.sort_values('ROI', ascending=False)
    return sub.head(top_n)


def campaigns_to_kill(df: pd.DataFrame, config: dict, top_n: int = 5) -> pd.DataFrame:
    """
    Повертає топ-N кампаній-кандидатів на вимкнення.
    Критерії: ROI < 0, спенд > min_spend_for_kill.
    """
    min_spend = config['kill_rules']['min_spend_for_kill']
    sub = df[(df['ROI'] < 0) & (df['Cost'] >= min_spend)].copy()
    sub = sub.sort_values('ROI', ascending=True)
    return sub.head(top_n)
