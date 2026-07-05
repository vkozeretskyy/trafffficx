"""
Модуль алертів.
Перевіряє кампанії на перевищення порогів CPA, негативний ROI,
відсутність конверсій. Повертає список алертів для дашборду.
"""

import pandas as pd
from typing import Optional


def check_alerts(df: pd.DataFrame, config: dict,
                 geo: Optional[str] = None) -> list[dict]:
    """
    Перевіряє всі кампанії та повертає список алертів.
    Кожен алерт: { campaign, metric, value, threshold, severity, message }
    """
    alerts = []

    thresholds = config.get('thresholds', {})
    kill_rules = config.get('kill_rules', {})

    cpa_max = thresholds.get('cpa_max', 210)
    roi_min = thresholds.get('roi_min', 15)
    roi_negative = thresholds.get('roi_negative', 0)
    min_spend = kill_rules.get('min_spend_for_kill', 50)

    active = df[(df['Cost'] > 0) | (df['Leads'] > 0)]

    for _, row in active.iterrows():
        name = row.get('Name', '???')
        campaign_type = row.get('campaign_type', 'other')
        cost = row.get('Cost', 0)
        revenue = row.get('Revenue', 0)
        roi = row.get('ROI', 0)
        cpa = row.get('CPA')
        deps = row.get('Deps', 0)
        leads = row.get('Leads', 0)

        # --- Алерт 1: CPA вище порогу ---
        if cpa is not None and cpa > cpa_max and cost >= min_spend:
            alerts.append({
                'campaign': name,
                'campaign_type': campaign_type,
                'metric': 'CPA',
                'value': cpa,
                'threshold': cpa_max,
                'severity': 'red',
                'message': (
                    f"CPA ${cpa:.0f} > порогу ${cpa_max} "
                    f"(спенд ${cost:,.0f}, ROI {roi:.1f}%)"
                )
            })

        # --- Алерт 2: Негативний ROI ---
        if roi < roi_negative and cost >= min_spend:
            alerts.append({
                'campaign': name,
                'campaign_type': campaign_type,
                'metric': 'ROI',
                'value': roi,
                'threshold': roi_negative,
                'severity': 'red',
                'message': (
                    f"ROI {roi:.1f}% — негативний "
                    f"(спенд ${cost:,.0f}, збиток ${cost - revenue:,.0f})"
                )
            })

        # --- Алерт 3: ROI нижче цільового, але не негативний ---
        if 0 <= roi < roi_min and cost >= min_spend:
            alerts.append({
                'campaign': name,
                'campaign_type': campaign_type,
                'metric': 'ROI',
                'value': roi,
                'threshold': roi_min,
                'severity': 'yellow',
                'message': (
                    f"ROI {roi:.1f}% — нижче цільового {roi_min}% "
                    f"(спенд ${cost:,.0f})"
                )
            })

        # --- Алерт 4: Є спенд, але немає депозитів ---
        if deps == 0 and cost >= min_spend and leads > 0:
            alerts.append({
                'campaign': name,
                'campaign_type': campaign_type,
                'metric': 'Deps',
                'value': 0,
                'threshold': 1,
                'severity': 'yellow' if leads < 5 else 'red',
                'message': (
                    f"0 депозитів при {leads} лідах і спенді ${cost:,.0f}"
                )
            })

        # --- Алерт 5: 0 лідів при значному спенді ---
        if leads == 0 and cost >= min_spend:
            alerts.append({
                'campaign': name,
                'campaign_type': campaign_type,
                'metric': 'Leads',
                'value': 0,
                'threshold': 1,
                'severity': 'red',
                'message': (
                    f"0 лідів при спенді ${cost:,.0f} — ймовірно, не працює"
                )
            })

    severity_order = {'red': 0, 'yellow': 1}
    alerts.sort(key=lambda a: (severity_order.get(a['severity'], 99), a['campaign']))

    return alerts


def alert_summary(alerts: list[dict]) -> dict:
    """Зведення по алертах: кількість червоних, жовтих, порушених кампаній."""
    red = [a for a in alerts if a['severity'] == 'red']
    yellow = [a for a in alerts if a['severity'] == 'yellow']
    campaigns = set(a['campaign'] for a in alerts)

    return {
        'total': len(alerts),
        'red': len(red),
        'yellow': len(yellow),
        'affected_campaigns': len(campaigns),
        'red_list': red,
        'yellow_list': yellow,
    }
