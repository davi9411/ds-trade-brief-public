"""
Motor de relevância — o "faro editorial" do DS Trade Brief.

Em vez de só contar palavras, pontua cada notícia como um editor de mercado faria:
o que move o mercado, traz dado concreto e é recente vai pro topo; conteúdo
corporativo/promocional vai pro fim.

Camadas de pontuação (somadas, com teto por camada pra evitar título "recheado"):
  +10  evento macro / banco central (Copom, Fed, Selic, CPI, juros…)
  +6   movimento forte (dispara, despenca, recorde, crash…)
  +3   movimento normal (sobe, cai, recua, lucro, dividendos…)
  +1   ativo citado (bitcoin, petrobras, dólar, ouro…)
Bônus:
  +2   título traz número/porcentagem ("Selic a 14,25%")
  +1   título traz valor monetário ("Bitcoin a US$ 100 mil")
  +2 / +1 / -1   recência (≤24h / ≤48h / >72h)
Penalidade:
  -5   conteúdo promo/corporativo (cartão, parceria, esports, airdrop…)

Bilíngue: Forex vem em inglês (Finnhub); B3 e Cripto em português (RSS).
"""

import re
import time
import calendar

# ── Camadas de palavras-chave (peso, termos) ──────────────────────────────────

_MACRO = [
    # PT
    "copom", "selic", "taxa selic", "taxa básica", "taxa de juros",
    "decisão de juros", "corte de juros", "alta de juros", "banco central",
    "juros", "ipca", "inflação", "deflação", "pib", "recessão", "desemprego",
    "super quarta", "galípolo", "tarifa", "tarifas", "sanção", "sanções",
    "guerra comercial",
    # EN
    "fed", "fomc", "ecb", "boe", "boj", "central bank", "rate decision",
    "rate cut", "rate hike", "interest rate", "rates", "cpi", "inflation",
    "gdp", "recession", "unemployment", "payroll", "payrolls", "nfp",
    "tariff", "tariffs", "sanction", "sanctions", "trade war",
]

_STRONG = [
    # PT
    "dispara", "disparou", "disparam", "despenca", "despencou", "desaba",
    "desabou", "derrete", "derreteu", "afunda", "afundou", "salta", "saltou",
    "explode", "explodiu", "máxima histórica", "mínima histórica", "recorde",
    "renova máxima", "rali", "derretimento", "dispara",
    # EN
    "soar", "soars", "soared", "plunge", "plunges", "plunged", "tumble",
    "tumbles", "tumbled", "surge", "surges", "surged", "crash", "crashes",
    "crashed", "rally", "all-time high", "record high", "spike", "spikes",
    "skyrocket",
]

_MOVE = [
    # PT
    "sobe", "subiu", "subindo", "sobem", "cai", "caiu", "caindo", "caem",
    "alta", "queda", "recua", "recuou", "recuam", "avança", "avançou",
    "avançam", "fecha", "fechou", "ganha", "ganhou", "perde", "perdeu",
    "valoriza", "valorizou", "desvaloriza", "desvalorizou", "oscila",
    "oscilou", "fechamento", "suporte", "resistência", "volatilidade",
    "lucro", "prejuízo", "balanço", "resultado", "dividendos", "guidance",
    # EN
    "rises", "rise", "rose", "falls", "fall", "fell", "gains", "gain",
    "gained", "drops", "drop", "dropped", "climbs", "climb", "slips", "slip",
    "slid", "jumps", "jump", "edges", "support", "resistance", "volatility",
    "earnings", "profit", "loss", "dividend", "dividends",
]

_ASSET = [
    "bitcoin", "btc", "ethereum", "eth", "xrp", "ripple", "solana", "sol",
    "bnb", "binance", "dogecoin", "doge", "cardano", "altcoin", "altcoins",
    "criptomoeda", "criptomoedas", "cripto", "stablecoin", "defi", "nft",
    "ibovespa", "ibov", "mini índice", "mini dólar", "win", "wdo", "ifix",
    "petrobras", "petr3", "petr4", "vale3", "itaú", "itau", "bradesco",
    "magalu", "dólar", "dolar", "dollar", "euro", "eur", "usd", "gbp", "jpy",
    "libra", "iene", "yen", "franco", "ouro", "gold", "petróleo", "oil",
    "brent", "wti", "treasury", "tesouro",
]

_PENALTY = [
    # PT
    "cartão", "cartao", "lança", "lançou", "lançamento", "parceria",
    "parcerias", "patrocínio", "patrocina", "patrocinador", "esports",
    "esport", "e-sports", "gaming", "jogos", "prêmio", "premiação", "sorteio",
    "campanha", "embaixador", "influenciador", "vaga", "vagas", "emprego",
    "contrata", "contratação", "evento", "eventos", "conferência",
    "hackathon", "airdrop", "pré-venda", "memecoin", "presale",
    # EN
    "sponsor", "sponsorship", "partnership", "brand deal", "award", "awards",
    "ambassador", "influencer", "campaign", "product launch", "app launch",
    "new feature", "rebrand", "merchandise", "hiring", "job opening",
    "giveaway", "contest", "tournament",
]


def _compile(words: list[str]) -> re.Pattern:
    # Ordena por tamanho desc pra casar frases antes de palavras soltas.
    parts = sorted({w.lower() for w in words}, key=len, reverse=True)
    pattern = "|".join(re.escape(p) for p in parts)
    # (?<!\w) ... (?!\w) = limite de palavra Unicode (respeita acentos).
    return re.compile(r"(?<!\w)(?:" + pattern + r")(?!\w)", re.IGNORECASE | re.UNICODE)


_LAYERS = [
    (10, _compile(_MACRO)),
    (6,  _compile(_STRONG)),
    (3,  _compile(_MOVE)),
    (1,  _compile(_ASSET)),
]
_PENALTY_RE = _compile(_PENALTY)

_PERCENT_RE = re.compile(r"\d[\d.,]*\s?%")
_MONEY_RE   = re.compile(r"(us\$|r\$|\$|€|£)\s?\d", re.IGNORECASE)

# Teto de termos contados por camada (anti-"keyword stuffing").
_CAP_PER_LAYER = 2


def score(title: str, summary: str = "", ts: float | None = None) -> int:
    """Pontua a relevância de uma notícia. Maior = mais digna de manchete.

    O título pesa mais que o resumo (decisão editorial fica na manchete).
    """
    title = title or ""
    summary = summary or ""
    t = title.lower()
    full = (title + " " + summary).lower()

    total = 0
    for weight, rx in _LAYERS:
        # distinto por camada, com teto
        hits = len({m.lower() for m in rx.findall(t)})
        if hits == 0:
            # vale metade do peso se aparecer só no resumo
            hits_sum = len({m.lower() for m in rx.findall(full)})
            total += (weight // 2) * min(hits_sum, _CAP_PER_LAYER)
        else:
            total += weight * min(hits, _CAP_PER_LAYER)

    # Penalidade (promo) — conta no texto todo
    total -= 5 * min(len({m.lower() for m in _PENALTY_RE.findall(full)}), 2)

    # Bônus de dado concreto no título
    if _PERCENT_RE.search(title):
        total += 2
    if _MONEY_RE.search(title):
        total += 1

    # Bônus/penalidade de recência
    if ts:
        age_h = (time.time() - ts) / 3600
        if age_h <= 24:
            total += 2
        elif age_h <= 48:
            total += 1
        elif age_h > 72:
            total -= 1

    return total


def rank(items: list[dict], limit: int | None = None, max_age_h: float | None = None) -> list[dict]:
    """Ordena notícias por relevância (desc). Cada item pode ter '_ts' (unix).

    Lê item['headline'] e item.get('summary'). Anexa '_score' temporário só
    pra ordenar e o remove no retorno. Mantém 'url' (usado p/ deduplicação).

    max_age_h: se informado, descarta itens mais antigos que isso (itens sem
    '_ts' são mantidos). Se o filtro esvaziar tudo, ignora o filtro.
    """
    pool = items
    if max_age_h is not None:
        cutoff = time.time() - max_age_h * 3600
        filtered = [it for it in items if it.get("_ts") is None or it["_ts"] >= cutoff]
        pool = filtered or items

    scored = []
    for it in pool:
        s = score(it.get("headline", ""), it.get("summary", ""), it.get("_ts"))
        scored.append((s, it))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for s, it in scored[: limit if limit else len(scored)]:
        clean = {k: v for k, v in it.items() if k not in ("_score", "_ts")}  # mantém 'url'
        out.append(clean)
    return out


def top_score(items: list[dict]) -> int:
    """Maior pontuação da lista (0 se vazia) — usado pelo Termômetro."""
    if not items:
        return 0
    return max(score(it.get("headline", ""), it.get("summary", ""), it.get("_ts"))
               for it in items)


def rss_ts(entry) -> float | None:
    """Converte a data de publicação de um item RSS (UTC struct_time) em unix."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return calendar.timegm(parsed)
        except Exception:
            return None
    return None
