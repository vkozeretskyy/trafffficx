"""
Генератор звітів.
Створює текст звіту для ТЛ та план дій на день.
"""

import pandas as pd
from datetime import datetime, date
from typing import Optional

from .metrics import (
    overall_summary,
    rank_campaigns,
    top_campaigns_for_scale,
    campaigns_to_kill
)
from .alerts import check_alerts, alert_summary


def _fmt_money(val: float) -> str:
    if abs(val) >= 1000:
        return f"${val:,.0f}"
    return f"${val:.2f}"


def _fmt_pct(val: float) -> str:
    return f"{val:+.1f}%"


def generate_tl_report(df: pd.DataFrame, config: dict,
                       report_date: Optional[date] = None) -> str:
    """
    Генерує короткий звіт для Team Lead.

    Формат — по ГЕО з оцінкою:
      🇹🇷 TR — плюс (спенд $X, ROI +Y%)
        📱 Android: кампанія +125% ✅, кампанія +38% ✅
        🌐 PWA: кампанія +23% ✅
        ❌ кампанія -20% (спенд $X)
    """
    if report_date is None:
        report_date = date.today()

    summary = overall_summary(df)
    alerts = check_alerts(df, config)
    alert_summ = alert_summary(alerts)

    lines = [
        f"📅 **{report_date.strftime('%d.%m.%Y')}**",
        "",
        f"💰 **Загалом:** Спенд {_fmt_money(summary['total_cost'])} | "
        f"Revenue {_fmt_money(summary['total_revenue'])} | "
        f"Profit {_fmt_money(summary['profit'])} | "
        f"ROI {_fmt_pct(summary['roi'])}",
        f"(кампаній: {summary['campaign_count']}, активних: {summary['active_count']}, "
        f"лідів: {summary['total_leads']:,}, депозитів: {summary['total_deps']:,})",
    ]

    # --- Групуємо за ГЕО ---
    from .parser import extract_geo

    # Додаємо колонку з ГЕО
    df = df.copy()
    df['geo'] = df['Name'].apply(extract_geo)

    # Тип кампанії для виводу
    def type_label(ct: str) -> str:
        return {'android': '📱 Android', 'pwa': '🌐 PWA',
                'ios': '🍏 iOS'}.get(ct, '📄 Інше')

    # Активні кампанії (зі спендом)
    active = df[(df['Cost'] > 0)].copy()

    for geo in sorted(active['geo'].unique()):
        geo_df = active[active['geo'] == geo]
        geo_cost = geo_df['Cost'].sum()
        geo_rev = geo_df['Revenue'].sum()
        geo_roi = ((geo_rev - geo_cost) / geo_cost * 100) if geo_cost > 0 else 0

        # Статус ГЕО
        if geo_cost < 50:
            geo_status = "мало спенда"
            emoji = "⚪"
        elif geo_roi > 20:
            geo_status = "плюс"
            emoji = "🟢"
        elif geo_roi >= 5:
            geo_status = "невеликий плюс"
            emoji = "🟡"
        elif geo_roi >= 0:
            geo_status = "в нуль"
            emoji = "🟡"
        else:
            geo_status = "мінус"
            emoji = "🔴"

        lines.append("")
        lines.append(
            f"{emoji} **{geo} — {geo_status}** "
            f"(спенд {_fmt_money(geo_cost)}, ROI {_fmt_pct(geo_roi)})"
        )

        # Групуємо за типом кампанії всередині ГЕО
        for ctype in ['android', 'pwa', 'ios']:
            type_df = geo_df[geo_df['campaign_type'] == ctype]
            if len(type_df) == 0:
                continue

            plus_list = []
            small_plus_list = []
            minus_list = []

            for _, r in type_df.iterrows():
                name = r.get('Name', '???')
                roi = r.get('ROI', 0)
                cost = r.get('Cost', 0)

                if roi > 20:
                    plus_list.append(f"**{name}** {_fmt_pct(roi)} 🟢")
                elif roi >= 0:
                    small_plus_list.append(f"{name} {_fmt_pct(roi)}")
                else:
                    minus_list.append(
                        f"~~{name}~~ {_fmt_pct(roi)} 🔴 (спенд {_fmt_money(cost)})"
                    )

            tlabel = type_label(ctype)
            if plus_list:
                lines.append(f"  {tlabel}: {', '.join(plus_list)}")
            if small_plus_list:
                lines.append(f"  {tlabel}: {', '.join(small_plus_list)}")
            if minus_list:
                lines.append(f"  ❌ {', '.join(minus_list)}")

        # Інші типи (other) — показуємо як мінус/плюс
        other_df = geo_df[~geo_df['campaign_type'].isin(['android', 'pwa', 'ios'])]
        if len(other_df) > 0:
            for _, r in other_df.iterrows():
                name = r.get('Name', '???')
                roi = r.get('ROI', 0)
                cost = r.get('Cost', 0)
                if roi < 0:
                    lines.append(
                        f"  ❌ ~~{name}~~ {_fmt_pct(roi)} 🔴 (спенд {_fmt_money(cost)})"
                    )
                elif roi > 20:
                    lines.append(f"  **{name}** {_fmt_pct(roi)} 🟢")
                else:
                    lines.append(f"  {name} {_fmt_pct(roi)}")

    # Підсумок алертів
    if alert_summ['red'] > 0:
        lines.append("")
        lines.append(f"🚨 **{alert_summ['red']} червоних алертів** — перевір вкладку «Алерти»")

    return '\n'.join(lines)


def generate_action_plan(df: pd.DataFrame, config: dict) -> str:
    """
    Генерує план дій на сьогодні:
      ✅ Масштабувати (підняти бюджет +50% або дублювати)
      ❌ Вимкнути
      🔍 Тестувати далі
    """
    lines = []

    # Масштабувати
    to_scale = top_campaigns_for_scale(df, config, top_n=5)
    if len(to_scale) > 0:
        lines.append("### ✅ МАСШТАБУВАТИ")
        lines.append("")
        for _, row in to_scale.iterrows():
            name = row.get('Name', '???')
            roi = row.get('ROI', 0)
            cost = row.get('Cost', 0)
            new_budget = cost * config['scaling']['budget_multiplier']
            dup_count = config['scaling']['duplicates']
            dup_budget = config['scaling']['dup_budget']
            lines.append(
                f"- **{name}** — ROI {roi:.1f}%: "
                f"підняти бюджет до {_fmt_money(new_budget)} "
                f"(+{int((config['scaling']['budget_multiplier'] - 1) * 100)}%) "
                f"або запустити {dup_count} дублів по ${dup_budget}"
            )
        lines.append("")

    # Вимкнути
    to_kill = campaigns_to_kill(df, config, top_n=5)
    if len(to_kill) > 0:
        lines.append("### ❌ ВИМКНУТИ")
        lines.append("")
        for _, row in to_kill.iterrows():
            name = row.get('Name', '???')
            roi = row.get('ROI', 0)
            cost = row.get('Cost', 0)
            loss = abs(cost - row.get('Revenue', 0))
            lines.append(
                f"- **{name}** — ROI {roi:.1f}%, "
                f"спенд {_fmt_money(cost)}, "
                f"збиток {_fmt_money(loss)}"
            )
        lines.append("")

    # Тестувати
    test = df[
        (df['ROI'] >= 0) &
        (df['ROI'] <= config['scaling']['roi_scale_threshold']) &
        (df['Cost'] > 10)
    ].sort_values('ROI', ascending=False).head(5)

    if len(test) > 0:
        lines.append("### 🔍 ТЕСТУВАТИ ДАЛІ")
        lines.append("")
        for _, row in test.iterrows():
            name = row.get('Name', '???')
            roi = row.get('ROI', 0)
            lines.append(
                f"- **{name}** — ROI {roi:.1f}%: "
                f"продовжити спостереження, не змінювати бюджет"
            )
        lines.append("")

    if len(to_scale) == 0 and len(to_kill) == 0 and len(test) == 0:
        lines.append("### 📭 Немає даних для плану")
        lines.append("Завантаж актуальний CSV з Binom.")

    return '\n'.join(lines)


def generate_full_report(df: pd.DataFrame, config: dict,
                         report_date: Optional[date] = None) -> dict:
    """Повертає повний звіт: TL-текст, план дій, зведення, алерти."""
    return {
        'report_date': report_date or date.today(),
        'tl_text': generate_tl_report(df, config, report_date),
        'action_plan': generate_action_plan(df, config),
        'summary': overall_summary(df),
        'alerts': alert_summary(check_alerts(df, config)),
        'to_scale': top_campaigns_for_scale(df, config, top_n=5).to_dict('records'),
        'to_kill': campaigns_to_kill(df, config, top_n=5).to_dict('records'),
    }
