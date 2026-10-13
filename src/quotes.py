"""
Bloco "COTAÇÕES DO DIA": valores reais e variação sobre o fechamento anterior.

Montado em código, sem IA: os números vêm direto das fontes (Yahoo Finance e
Banco Central) e entram no post já formatados, então não dependem de o texto ser
reescrito por um modelo. Entra no mesmo post, logo depois da Opinião e antes dos
dois avisos finais: primeiro as cotações, depois o 💬 (não é sinal) e por último o
⚠️ (conteúdo educacional).

Ibovespa, Bitcoin e Dólar vêm de src/sources/prices.py. A Selic vem da série 432
do SGS do Banco Central (meta definida pelo Copom), sem chave. Como os servidores
do GitHub ficam nos EUA e o BCB costuma estourar o tempo de fora do Brasil, há
reserva em três degraus: BCB → BrasilAPI (só o valor) → último valor guardado em
data/selic.json (se tiver até 10 dias). Se nada responder, a linha some: nunca
inventamos valor.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BR_TZ = timezone(timedelta(hours=-3))
BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados"
BRASILAPI_URL = "https://brasilapi.com.br/api/taxas/v1/selic"
CACHE = Path(__file__).resolve().parent.parent / "data" / "selic.json"

TITLE = "COTAÇÕES DO DIA"
UP, DOWN, FLAT = "🟢", "🔴", "⚪"
SELIC_NOTE_DAYS = 60     # só comenta a mudança da Selic se for recente
CACHE_MAX_AGE_DAYS = 10  # idade máxima do valor guardado para usar de reserva


# ── Selic ─────────────────────────────────────────────────────────────────────

def _selic_from_bcb() -> dict | None:
    """Valor vigente + data da última mudança (SGS 432). 2 tentativas.

    A API limita "últimos N" a 20 valores, então consultamos por intervalo de
    datas (que também corta no dia de hoje).
    """
    today = datetime.now(BR_TZ).date()
    params = {
        "formato": "json",
        "dataInicial": (today - timedelta(days=400)).strftime("%d/%m/%Y"),
        "dataFinal": today.strftime("%d/%m/%Y"),
    }
    for attempt in (1,):  # de fora do Brasil costuma estourar o tempo: 1 tentativa curta
        try:
            r = requests.get(BCB_URL, params=params, timeout=10)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return None
            cur = float(rows[-1]["valor"])
            i = len(rows) - 1
            while i > 0 and float(rows[i - 1]["valor"]) == cur:
                i -= 1
            since = datetime.strptime(rows[i]["data"], "%d/%m/%Y").date()
            prev = float(rows[i - 1]["valor"]) if i > 0 else None
            return {"rate": cur, "since": since.isoformat(), "prev_rate": prev, "source": "bcb"}
        except Exception as e:
            print(f"[quotes] BCB falhou: {str(e)[:90]}")
    return None


def _selic_from_brasilapi() -> dict | None:
    """Só o valor vigente (sem a data da última mudança)."""
    try:
        r = requests.get(BRASILAPI_URL, timeout=10)
        r.raise_for_status()
        return {"rate": float(r.json()["valor"]), "since": None, "prev_rate": None,
                "source": "brasilapi"}
    except Exception as e:
        print(f"[quotes] BrasilAPI falhou: {str(e)[:90]}")
        return None


def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(s: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({**s, "fetched_at": datetime.now(BR_TZ).date().isoformat()},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[quotes] não consegui gravar o cache da Selic: {e}")


def fetch_selic() -> dict | None:
    """Meta Selic vigente (e a última mudança, quando a fonte informa). None se nada responder."""
    cache = _load_cache()
    s = _selic_from_bcb() or _selic_from_brasilapi()

    if s:
        # A BrasilAPI não traz a data da mudança: reaproveita a do cache se o valor não mudou.
        if s["since"] is None and cache:
            if cache.get("rate") == s["rate"]:
                s["since"], s["prev_rate"] = cache.get("since"), cache.get("prev_rate")
            elif cache.get("rate") is not None:
                # O valor mudou desde a última checagem (o Copom decidiu): a data é a da detecção.
                s["since"] = datetime.now(BR_TZ).date().isoformat()
                s["prev_rate"] = cache["rate"]
        _save_cache(s)
        return s

    if cache:
        try:
            age = (datetime.now(BR_TZ).date() - datetime.strptime(cache["fetched_at"], "%Y-%m-%d").date()).days
        except Exception:
            age = 999
        if age <= CACHE_MAX_AGE_DAYS:
            print(f"[quotes] fontes da Selic fora do ar; usando o valor guardado há {age} dia(s).")
            return {k: cache.get(k) for k in ("rate", "since", "prev_rate")} | {"source": "cache"}
    print("[quotes] Selic indisponível em todas as fontes; a linha será omitida.")
    return None


# ── formatação ────────────────────────────────────────────────────────────────

def _num(x: float, decimals: int = 0) -> str:
    """Formata no padrão brasileiro: 204.787 / 5,01."""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(p: float) -> str:
    """'🔴 -2,58%', '🟢 +0,21%' ou '⚪ 0,00%'."""
    if abs(p) < 0.005:
        return f"{FLAT} 0,00%"
    emoji = UP if p > 0 else DOWN
    sign = "+" if p > 0 else "-"
    return f"{emoji} {sign}{_num(abs(p), 2)}%"


def _find(prices: list[dict], label: str) -> dict | None:
    for p in prices or []:
        if p.get("asset") == label and p.get("price") is not None:
            return p
    return None


def build_block(data: dict) -> str:
    """Devolve o bloco pronto (HTML do Telegram) ou '' se não houver nada."""
    prices = data.get("prices") or []
    lines = []

    p = _find(prices, "Ibovespa")
    if p:
        lines.append(f"🇧🇷 <b>Ibovespa:</b> {_num(p['price'])} pontos  {_pct(p['change_pct'])}")
    p = _find(prices, "Bitcoin (BTC)")
    if p:
        lines.append(f"₿ <b>Bitcoin:</b> US$ {_num(p['price'])}  {_pct(p['change_pct'])}")
    p = _find(prices, "Dólar (USD/BRL)")
    if p:
        lines.append(f"💵 <b>Dólar:</b> R$ {_num(p['price'], 2)}  {_pct(p['change_pct'])}")

    s = data.get("selic")
    if s and s.get("rate") is not None:
        line = f"🏦 <b>Selic:</b> {_num(s['rate'], 2)}% ao ano"
        try:
            since = datetime.strptime(s["since"], "%Y-%m-%d").date()
            recent = (datetime.now(BR_TZ).date() - since).days <= SELIC_NOTE_DAYS
        except Exception:
            since, recent = None, False
        if recent and s.get("prev_rate") is not None and s["prev_rate"] != s["rate"]:
            delta = s["rate"] - s["prev_rate"]
            sign = "+" if delta > 0 else "-"
            line += f" <i>({sign}{_num(abs(delta), 2)} p.p. desde {since:%d/%m})</i>"
        lines.append(line)

    if not lines:
        return ""

    return "\n".join([
        "━━━━━━━━━━━━━━━",
        f"💹 <b>{TITLE}</b>",
        "━━━━━━━━━━━━━━━",
        *lines,
        "<i>Variação sobre o fechamento anterior. Ibovespa: último pregão.</i>",
    ])


def add_quotes(post_text: str, data: dict) -> str:
    """Insere o bloco antes dos dois avisos finais (💬 e ⚠️). Idempotente."""
    if TITLE in post_text:
        return post_text
    block = build_block(data)
    if not block:
        return post_text

    lines = post_text.split("\n")
    # O bloco vem ANTES dos dois avisos finais: primeiro procura o aviso de
    # "não é sinal" (💬); se não houver, o aviso educacional (⚠️).
    idx = None
    for pattern in (r"💬|baseada em dados p[úu]blicos|n[ãa]o representa sinal",
                    r"conte[úu]do educacional"):
        for i in range(len(lines) - 1, -1, -1):
            if re.search(pattern, lines[i], re.I):
                idx = i
                break
        if idx is not None:
            break
    if idx is None:  # sem nenhum aviso: acrescenta no fim
        return post_text.rstrip() + "\n\n" + block

    before = "\n".join(lines[:idx]).rstrip()
    after = "\n".join(lines[idx:])
    return f"{before}\n\n{block}\n\n{after}"
