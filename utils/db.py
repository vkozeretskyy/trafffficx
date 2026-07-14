"""
SQLite-модуль для збереження історії кампаній.
Щоразу після аналізу CSV зберігає зріз за поточний день.
Дозволяє дивитись тренди: ROI, CPA, спенд по днях.
"""

import sqlite3
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Optional
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'history.db')


def _ensure_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Створює таблиці, якщо їх немає."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            campaign_name TEXT NOT NULL,
            campaign_type TEXT,
            traffic_source TEXT,
            geo TEXT,
            cost REAL DEFAULT 0,
            revenue REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            roi REAL DEFAULT 0,
            leads INTEGER DEFAULT 0,
            deps INTEGER DEFAULT 0,
            cpi REAL,
            cpr REAL,
            cpl REAL,
            cpa REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshot_date ON daily_snapshots(snapshot_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshot_campaign ON daily_snapshots(campaign_name, snapshot_date)
    """)
    conn.commit()
    conn.close()


def save_snapshot(df: pd.DataFrame, snapshot_date: Optional[date] = None) -> int:
    """
    Зберігає зріз кампаній за вказану дату.
    Якщо за цю дату вже є дані — перезаписує.

    Returns: кількість збережених рядків
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    init_db()
    conn = _connect()

    # Видаляємо старі записи за цю дату (перезапис)
    conn.execute("DELETE FROM daily_snapshots WHERE snapshot_date = ?",
                 (snapshot_date.isoformat(),))

    from .parser import extract_geo

    rows = 0
    for _, row in df.iterrows():
        if row.get('Cost', 0) == 0 and row.get('Leads', 0) == 0:
            continue  # пропускаємо порожні

        geo = extract_geo(row.get('Name', ''))

        conn.execute("""
            INSERT INTO daily_snapshots
            (snapshot_date, campaign_name, campaign_type, traffic_source, geo,
             cost, revenue, profit, roi, leads, deps, cpi, cpr, cpl, cpa)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_date.isoformat(),
            row.get('Name', ''),
            row.get('campaign_type', ''),
            row.get('Traffic Source', ''),
            geo,
            row.get('Cost', 0),
            row.get('Revenue', 0),
            row.get('Profit', 0) if 'Profit' in row else row.get('Revenue', 0) - row.get('Cost', 0),
            row.get('ROI', 0),
            int(row.get('Leads', 0)),
            int(row.get('Deps', 0)),
            row.get('CPI'),
            row.get('CPR'),
            row.get('CPL'),
            row.get('CPA'),
        ))
        rows += 1

    conn.commit()
    conn.close()
    return rows


def load_history(days: int = 14, campaign_name: Optional[str] = None,
                 geo: Optional[str] = None) -> pd.DataFrame:
    """
    Завантажує історію за останні N днів.

    Args:
        days: скільки днів назад
        campaign_name: фільтр за назвою (None = всі)
        geo: фільтр за гео (None = всі)

    Returns: DataFrame з колонками snapshot_date, campaign_name, cost, roi, cpa, ...
    """
    init_db()
    conn = _connect()

    since = (date.today() - timedelta(days=days)).isoformat()

    query = "SELECT * FROM daily_snapshots WHERE snapshot_date >= ?"
    params = [since]

    if campaign_name:
        query += " AND campaign_name = ?"
        params.append(campaign_name)
    if geo:
        query += " AND geo = ?"
        params.append(geo)

    query += " ORDER BY snapshot_date DESC, cost DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_available_dates() -> list[str]:
    """Повертає список дат, за які є записи."""
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT snapshot_date FROM daily_snapshots ORDER BY snapshot_date DESC"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_trends(campaign_name: Optional[str] = None,
               geo: Optional[str] = None, days: int = 14) -> pd.DataFrame:
    """
    Повертає агреговані тренди по днях:
    загальний спенд, revenue, ROI, середній CPA.

    Returns: DataFrame з колонками snapshot_date, cost, revenue, roi, avg_cpa
    """
    init_db()
    conn = _connect()

    since = (date.today() - timedelta(days=days)).isoformat()

    query = """
        SELECT
            snapshot_date,
            SUM(cost) as total_cost,
            SUM(revenue) as total_revenue,
            SUM(revenue) - SUM(cost) as profit,
            CASE WHEN SUM(cost) > 0
                 THEN ROUND(((SUM(revenue) - SUM(cost)) / SUM(cost)) * 100, 1)
                 ELSE 0 END as roi,
            CASE WHEN SUM(deps) > 0
                 THEN ROUND(SUM(cost) / SUM(deps), 2)
                 ELSE NULL END as avg_cpa,
            SUM(leads) as total_leads,
            SUM(deps) as total_deps
        FROM daily_snapshots
        WHERE snapshot_date >= ?
    """
    params = [since]

    if campaign_name:
        query += " AND campaign_name = ?"
        params.append(campaign_name)
    if geo:
        query += " AND geo = ?"
        params.append(geo)

    query += " GROUP BY snapshot_date ORDER BY snapshot_date ASC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_campaign_trend(campaign_name: str, days: int = 14) -> pd.DataFrame:
    """
    Повертає щоденні метрики для однієї кампанії.
    """
    init_db()
    conn = _connect()

    since = (date.today() - timedelta(days=days)).isoformat()

    df = pd.read_sql_query("""
        SELECT snapshot_date, cost, revenue, roi, cpa, leads, deps
        FROM daily_snapshots
        WHERE campaign_name = ? AND snapshot_date >= ?
        ORDER BY snapshot_date ASC
    """, conn, params=[campaign_name, since])
    conn.close()
    return df


def detect_trends(days: int = 14) -> list[dict]:
    """
    Виявляє кампанії з вираженими трендами:
    - ROI падає 3+ дні поспіль
    - CPA росте 3+ дні поспіль
    - ROI стабільно росте

    Returns: список словників {campaign, trend_type, direction, values}
    """
    init_db()
    conn = _connect()

    since = (date.today() - timedelta(days=days)).isoformat()

    # Отримуємо всі кампанії з даними за останні N днів
    campaigns = conn.execute("""
        SELECT DISTINCT campaign_name FROM daily_snapshots
        WHERE snapshot_date >= ? AND cost > 0
    """, [since]).fetchall()
    conn.close()

    alerts = []

    for (name,) in campaigns:
        df = get_campaign_trend(name, days)
        if len(df) < 3:
            continue

        roi_vals = df['roi'].tolist()
        cpa_vals = [v for v in df['cpa'].tolist() if v is not None]

        # ROI падає 3+ дні
        if len(roi_vals) >= 3:
            last3 = roi_vals[-3:]
            if last3[0] > last3[1] > last3[2] and last3[0] > 0:
                alerts.append({
                    'campaign': name,
                    'trend_type': 'roi_falling',
                    'direction': '📉',
                    'message': f"ROI падає: {last3[0]:.1f}% → {last3[1]:.1f}% → {last3[2]:.1f}%",
                    'severity': 'yellow' if last3[2] > 0 else 'red',
                })

        # CPA росте 3+ дні
        if len(cpa_vals) >= 3:
            last3c = cpa_vals[-3:]
            if last3c[0] < last3c[1] < last3c[2]:
                alerts.append({
                    'campaign': name,
                    'trend_type': 'cpa_rising',
                    'direction': '📈',
                    'message': f"CPA росте: ${last3c[0]:.0f} → ${last3c[1]:.0f} → ${last3c[2]:.0f}",
                    'severity': 'yellow',
                })

        # ROI стабільно росте 3+ дні
        if len(roi_vals) >= 3:
            last3 = roi_vals[-3:]
            if last3[0] < last3[1] < last3[2] and last3[2] > 20:
                alerts.append({
                    'campaign': name,
                    'trend_type': 'roi_rising',
                    'direction': '📈',
                    'message': f"ROI росте: {last3[0]:.1f}% → {last3[1]:.1f}% → {last3[2]:.1f}%",
                    'severity': 'green',
                })

    return alerts
