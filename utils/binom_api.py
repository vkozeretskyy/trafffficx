"""
Binom API connector.
Подключается к Binom Tracker API, получает статистику по кампаниям
за указанный период. Возвращает pandas DataFrame, совместимый с parser.py.

Поддерживает:
  - Binom API v1 (GET /api/campaigns)
  - Binom API v2 (POST /api/v2/report)
  - Ручной ввод endpoint в конфиге
"""

import pandas as pd
import requests
from datetime import date, datetime
from typing import Optional, Tuple
from io import StringIO


class BinomAPIClient:
    """
    Клиент для Binom Tracker API.

    Использование:
        client = BinomAPIClient(
            base_url="https://tracker.example.com",
            api_key="your-api-key"
        )
        df = client.fetch_campaigns(date_from="2026-06-01", date_to="2026-06-19")
    """

    def __init__(self, base_url: str, api_key: str,
                 timezone: str = "Europe/Kyiv",
                 timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timezone = timezone
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': api_key,
            'Accept': 'application/json',
        })

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET-запрос к API."""
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: Optional[dict] = None) -> dict:
        """POST-запрос к API."""
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, json=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_campaigns(self, date_from: str, date_to: str,
                        endpoint: Optional[str] = None) -> pd.DataFrame:
        """
        Получает статистику кампаний за период.

        Args:
            date_from: начальная дата (YYYY-MM-DD)
            date_to: конечная дата (YYYY-MM-DD)
            endpoint: путь API (если None — авто-определение)

        Returns:
            DataFrame с колонками как в CSV-экспорте Binom
        """
        if endpoint:
            return self._fetch_custom(endpoint, date_from, date_to)

        # Пробуем форматы API по очереди
        errors = []
        for fetcher in [
            self._fetch_v1_campaigns,
            self._fetch_v2_report,
            self._fetch_csv_export,
        ]:
            try:
                df = fetcher(date_from, date_to)
                if df is not None and len(df) > 0:
                    return df
            except Exception as e:
                errors.append(f"{fetcher.__name__}: {e}")
                continue

        raise RuntimeError(
            "Не удалось получить данные ни одним способом:\n" +
            "\n".join(errors)
        )

    def _fetch_v1_campaigns(self, date_from: str, date_to: str) -> pd.DataFrame:
        """
        Binom API v1: GET /api/campaigns
        Параметры: date_from, date_to, timezone
        """
        params = {
            'date_from': date_from,
            'date_to': date_to,
            'timezone': self.timezone,
        }
        data = self._get('/api/campaigns', params)

        # Обработка разных форматов ответа
        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            # Возможно: {"data": [...], "count": N}
            for key in ['data', 'campaigns', 'rows', 'items']:
                if key in data and isinstance(data[key], list):
                    return pd.DataFrame(data[key])
            # Или плоский словарь с одной записью
            return pd.DataFrame([data])

        return pd.DataFrame()

    def _fetch_v2_report(self, date_from: str, date_to: str) -> pd.DataFrame:
        """
        Binom API v2: POST /api/v2/report
        Тело: {"date_from": "...", "date_to": "...", "group_by": "campaign"}
        """
        body = {
            'date_from': date_from,
            'date_to': date_to,
            'timezone': self.timezone,
            'group_by': 'campaign',
        }
        data = self._post('/api/v2/report', body)

        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            for key in ['data', 'campaigns', 'rows', 'items', 'report']:
                if key in data and isinstance(data[key], list):
                    return pd.DataFrame(data[key])
            return pd.DataFrame([data])

        return pd.DataFrame()

    def _fetch_csv_export(self, date_from: str, date_to: str) -> pd.DataFrame:
        """
        Binom CSV export: GET /export/campaigns.csv
        Возвращает CSV как в ручном экспорте.
        """
        params = {
            'date_from': date_from,
            'date_to': date_to,
            'timezone': self.timezone,
        }
        # Пробуем несколько путей
        for path in ['/export/campaigns.csv', '/api/export/campaigns', '/export/csv']:
            try:
                url = f"{self.base_url}{path}"
                resp = self.session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                content = resp.text
                if content and ',' in content:
                    # Определяем разделитель
                    first_line = content.split('\n')[0]
                    sep = ';' if first_line.count(';') > first_line.count(',') else ','
                    return pd.read_csv(StringIO(content), sep=sep)
            except Exception:
                continue

        raise RuntimeError("CSV export: ни один путь не сработал")

    def _fetch_custom(self, endpoint: str,
                      date_from: str, date_to: str) -> pd.DataFrame:
        """
        Кастомный endpoint из конфига.
        """
        method = endpoint.get('method', 'GET').upper()
        path = endpoint.get('path', '/api/campaigns')
        params_template = endpoint.get('params', {})

        full_params = {
            **params_template,
            'date_from': date_from,
            'date_to': date_to,
        }

        if method == 'POST':
            data = self._post(path, full_params)
        else:
            data = self._get(path, full_params)

        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            for key in ['data', 'campaigns', 'rows', 'items']:
                if key in data and isinstance(data[key], list):
                    return pd.DataFrame(data[key])
            return pd.DataFrame([data])
        return pd.DataFrame()

    def test_connection(self) -> Tuple[bool, str]:
        """
        Проверяет соединение с API.
        Returns: (ok, message)
        """
        try:
            # Пробуем стукнуться в /api/campaigns с минимальной датой
            today = date.today().isoformat()
            self._get('/api/campaigns', {
                'date_from': today,
                'date_to': today,
                'timezone': self.timezone,
            })
            return True, "✅ Соединение установлено"
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                return False, "❌ Ошибка авторизации — проверь API-ключ"
            elif e.response.status_code == 404:
                return False, "❌ Эндпоинт не найден — проверь base_url"
            else:
                return False, f"❌ HTTP {e.response.status_code}: {e}"
        except requests.ConnectionError:
            return False, "❌ Не удалось подключиться — проверь base_url"
        except Exception as e:
            return False, f"❌ Ошибка: {e}"
