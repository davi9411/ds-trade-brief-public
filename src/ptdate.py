"""
Datas em português do Brasil, independentes do locale do servidor.

O runner do GitHub Actions roda em inglês, então strftime("%A") devolvia
"Wednesday" no título do brief e na página do Telegra.ph. Aqui o dia da semana
vem de uma tabela fixa.
"""

from datetime import datetime, timedelta, timezone

BR_TZ = timezone(timedelta(hours=-3))

WEEKDAYS_PT = [
    "Segunda-feira", "Terça-feira", "Quarta-feira",
    "Quinta-feira", "Sexta-feira", "Sábado", "Domingo",
]


def now_br() -> datetime:
    return datetime.now(BR_TZ)


def date_pt(dt: datetime | None = None) -> str:
    """Ex.: 'Quarta-feira, 07/10/2026'."""
    dt = dt or now_br()
    return f"{WEEKDAYS_PT[dt.weekday()]}, {dt:%d/%m/%Y}"


def today_iso() -> str:
    """Data de hoje em Brasília, AAAA-MM-DD."""
    return now_br().strftime("%Y-%m-%d")
