# 🎰 Gambling Traffic Analyzer

Аналітичний дашборд для медіабаєра в гемблінг-вертикалі.

**Що робить:**
- Парсить CSV з Binom Tracker
- Рахує CPA, ROI, CPI, CPL, CPR
- Групує кампанії за ГЕО (TR, PT, UK, ...)
- Показує алерти: CPA > порогу, негативний ROI, 0 депозитів
- Генерує звіт для Team Lead (по ГЕО з оцінкою: плюс/мінус/в нуль)
- Генерує план на день: що масштабувати, що вимкнути

## 🚀 Запуск

```bash
# 1. Встанови залежності
pip install -r requirements.txt

# 2. Налаштуй конфіг
cp config.example.yaml config.yaml
# Відредагуй config.yaml — впиши свої пороги CPA/ROI

# 3. Запусти
streamlit run app.py
```

Відкриється браузер на `http://localhost:8501`

## 📂 Структура

```
traffic-dashboard/
├── app.py                  # Streamlit дашборд
├── config.yaml             # Конфігурація (пороги, API)
├── requirements.txt        # Залежності
└── utils/
    ├── parser.py           # Парсер Binom CSV
    ├── metrics.py          # Розрахунок метрик
    ├── alerts.py           # Система алертів
    ├── reporter.py         # Генератор звітів
    └── binom_api.py        # Binom API конектор
```

## 🔌 Binom API (опціонально)

У `config.yaml` впиши:

```yaml
binom_api:
  base_url: "https://твій-трекер.binom.org"
  api_key: "твій-ключ"
```

У дашборді постав галку «Використовувати API» → вибери дати → «Завантажити».

## ⚙️ Налаштування порогів

У `config.yaml`:

| Параметр | За замовчуванням | Опис |
|----------|-----------------|------|
| `cpa_max` | $210 | Максимальний CPA, вище — червоний алерт |
| `roi_min` | 15% | Мінімальний ROI для цілі |
| `roi_scale_threshold` | 20% | ROI вище — рекомендація масштабувати |
| `budget_multiplier` | 1.5 | У скільки разів збільшувати бюджет (+50%) |

## 🖥 Деплой

### Streamlit Cloud (безкоштовно)
1. Залей репозиторій на GitHub
2. Зайди на [share.streamlit.io](https://share.streamlit.io)
3. Deploy → вибери репо → готово

### VPS (Docker)
```bash
docker build -t traffic-dashboard .
docker run -p 8501:8501 traffic-dashboard
```
