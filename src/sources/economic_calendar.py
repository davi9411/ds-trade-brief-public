"""
Fonte: CALENDÁRIO ECONÔMICO DA SEMANA

Estratégia (em ordem de tentativa):
1. ForexFactory JSON público (nfs.faireconomy.media) — sem chave, dados reais da semana
2. Finnhub (https://finnhub.io/docs/api/economic-calendar) — requer FINNHUB_API_KEY;
   o endpoint de calendário pode ser bloqueado em contas free (retorna 403).
3. Mock estático — fallback final para não travar o pipeline.

Filtramos apenas eventos de ALTO impacto relevantes para traders de mini índice,
mini dólar e Forex (USD, BRL, EUR, GBP + globais).
"""

from datetime import datetime, timedelta

import requests
from src import config

FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"

# ForexFactory usa códigos de MOEDA (3 letras), não de país (2 letras)
RELEVANT_COUNTRIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "BRL", "CNY"}

HIGH_IMPACT_KEYWORDS = [
    "fed", "fomc", "interest rate", "cpi", "non farm", "nonfarm", "payroll",
    "gdp", "pib", "selic", "copom", "ipca", "rate decision", "inflation",
    "employment", "unemployment",
]

MOCK_CALENDAR = [
    {"day": "Segunda", "country": "BR", "event": "IPCA-15 (prévia da inflação)", "impact": "alto"},
    {"day": "Quarta", "country": "US", "event": "Decisão de juros do FOMC", "impact": "alto"},
    {"day": "Quinta", "country": "BR", "event": "Reunião do Copom - decisão Selic", "impact": "alto"},
    {"day": "Sexta", "country": "US", "event": "Payroll (criação de empregos)", "impact": "alto"},
]

WEEKDAY_PT = {
    "Monday": "Segunda", "Tuesday": "Terça", "Wednesday": "Quarta",
    "Thursday": "Quinta", "Friday": "Sexta", "Saturday": "Sábado", "Sunday": "Domingo",
}


def _fmt_day(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "").replace("T", " ").split(" ")[0])
        return WEEKDAY_PT.get(dt.strftime("%A"), dt.strftime("%A"))
    except Exception:
        return date_str


def _fetch_forexfactory() -> list[dict]:
    """Busca o calendário da semana no ForexFactory (JSON público, sem chave)."""
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(FOREXFACTORY_URL, headers=ua, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    items = []
    for ev in data:
        if ev.get("impact") != "High":
            continue
        country = (ev.get("country") or "").upper()
        if country not in RELEVANT_COUNTRIES:
            continue
        items.append({
            "day": _fmt_day(ev.get("date", "")),
            "country": country,
            "event": ev.get("title", ""),
            "impact": "alto",
        })
    return items


def _is_high_impact(event_name: str, impact_field: str = "") -> bool:
    text = f"{event_name} {impact_field}".lower()
    if impact_field.lower() in ("high", "3", "alto"):
        return True
    return any(kw in text for kw in HIGH_IMPACT_KEYWORDS)


def _fetch_finnhub(days_ahead: int = 7) -> list[dict]:
    """Busca calendário na Finnhub (requer API key; pode retornar 403 no free tier)."""
    today = datetime.utcnow().date()
    end_date = today + timedelta(days=days_ahead)

    resp = requests.get(
        FINNHUB_CALENDAR_URL,
        params={"from": today.isoformat(), "to": end_date.isoformat(), "token": config.FINNHUB_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    items = []
    for ev in data.get("economicCalendar", []):
        event_name = ev.get("event", "")
        impact = ev.get("impact", "")
        if not _is_high_impact(event_name, str(impact)):
            continue
        event_date_str = ev.get("time", "") or ev.get("date", "")
        items.append({
            "day": _fmt_day(event_date_str),
            "country": ev.get("country", ""),
            "event": event_name,
            "impact": str(impact) or "alto",
        })
    return items


def fetch_economic_calendar(days_ahead: int = 7) -> list[dict]:
    """Busca eventos econômicos de alto impacto para a semana.

    Tenta ForexFactory primeiro (sem chave), depois Finnhub, depois mock.
    Retorna lista de dicts com: day, country, event, impact.
    """
    # 1. ForexFactory (sem chave, mais confiável)
    try:
        items = _fetch_forexfactory()
        if items:
            print(f"[economic_calendar] ForexFactory: {len(items)} eventos de alto impacto.")
            return items
    except Exception as e:
        print(f"[economic_calendar] ForexFactory falhou: {e}.")

    # 2. Finnhub (se tiver chave)
    if config.FINNHUB_API_KEY:
        try:
            items = _fetch_finnhub(days_ahead)
            if items:
                print(f"[economic_calendar] Finnhub: {len(items)} eventos.")
                return items
        except Exception as e:
            print(f"[economic_calendar] Finnhub falhou: {e}.")

    # 3. Mock
    print("[economic_calendar] Usando calendário de exemplo (mock).")
    return MOCK_CALENDAR


if __name__ == "__main__":
    for ev in fetch_economic_calendar():
        print(f"  {ev['day']} | {ev['country']} | {ev['event']}")
