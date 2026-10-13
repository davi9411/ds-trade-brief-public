"""
Fonte de notícias: FOREX (câmbio global e moedas)

O Finnhub free tier devolve pouquíssima notícia de forex (às vezes 1 item),
então a fonte principal passou a ser RSS em PT (Investing.com forex + economia),
com o Finnhub (inglês) entrando como bônus quando tiver itens. Tudo é filtrado
pelo gate de câmbio e ranqueado pelo motor de relevância compartilhado.

Use `python -m src.sources.news_forex` para testar rapidamente.
"""

import re

import requests
import feedparser
from src import config
from src.sources import relevance

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"

FEED_URLS = [
    "https://br.investing.com/rss/forex.rss",     # câmbio (PT, dedicado)
    "https://br.investing.com/rss/news_1.rss",    # notícias gerais (macro/FX global)
    "https://www.moneytimes.com.br/economia/feed/",  # economia
]

# Gate: a notícia precisa falar de câmbio/moedas/política monetária global.
# Termos distintos o bastante pra usar substring sem falso positivo.
_FOREX_KW = [
    # Moedas e pares (PT/EN)
    "dólar", "dolar", "dollar", "euro", "iene", "yen", "yuan", "dxy",
    "libra esterlina", "franco suíço", "peso mexicano", "peso argentino",
    "eur/usd", "gbp/usd", "usd/jpy", "usd/brl", "eur/brl", "usd/chf",
    "câmbio", "forex", "moeda", "moedas", "currency", "exchange rate",
    # Bancos centrais e macro global
    "fed", "fomc", "federal reserve", "powell", "bce", "banco central europeu",
    "boe", "boj", "ecb", "central bank", "payroll", "nonfarm", "nfp",
    "decisão de juros", "rate decision", "treasury", "dados de emprego",
]

# Filtro do Finnhub (inglês): exclui promo, exige termo de mercado.
_EXCLUDE = {
    "sponsor", "esport", "gaming", "tournament", "prize", "contest",
    "ambassador", "partnership", "collaborat", "brand deal", "campaign",
    "award", "celebrity", "influencer", "product launch", "app launch",
    "new feature", "rebrand", "merchandise",
}
_REQUIRE_ANY = {
    "usd", "eur", "gbp", "jpy", "chf", "aud", "nzd", "cad", "brl",
    "dollar", "euro", "pound", "yen", "franc", "peso",
    "fed", "ecb", "boe", "boj", "fomc", "central bank", "rate",
    "inflation", "cpi", "gdp", "nfp", "employment", "pmi",
    "interest", "monetary", "treasury", "yield", "bond",
    "currency", "exchange", "forex", "fx ", "trade balance",
    "economic", "recession", "growth", "export", "import",
}

_TAG_RE = re.compile(r"<[^>]+>")

MOCK_NEWS = [
    {
        "headline": "Dólar recua frente a moedas fortes após dados de inflação dos EUA",
        "summary": "O índice DXY caiu após o CPI dos EUA vir abaixo do esperado, "
                    "reduzindo apostas de novas altas de juros pelo Fed.",
        "source": "Exemplo (mock)",
        "url": "",
    },
    {
        "headline": "Euro ganha força com expectativa de decisão do BCE",
        "summary": "Mercado aguarda sinais do Banco Central Europeu sobre o ritmo "
                    "de cortes de juros na zona do euro.",
        "source": "Exemplo (mock)",
        "url": "",
    },
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text or "")).strip()


def _is_forex_title(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _FOREX_KW)


def _finnhub_relevant(headline: str, summary: str) -> bool:
    text = (headline + " " + summary).lower()
    if any(ex in text for ex in _EXCLUDE):
        return False
    return any(req in text for req in _REQUIRE_ANY)


def fetch_forex_news(limit: int = 5, max_age_h: float | None = None) -> list[dict]:
    """Agrega notícias de câmbio de RSS (PT) + Finnhub (EN), filtra pelo gate
    de forex e retorna ranqueadas por relevância (recentes primeiro).
    """
    seen: set[str] = set()
    candidates: list[dict] = []

    # 1) RSS em português (fonte principal)
    for feed_url in FEED_URLS:
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                continue
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title or not _is_forex_title(title):
                    continue
                key = title.lower()[:60]
                if key in seen:
                    continue
                seen.add(key)
                summary = entry.get("summary", "") or entry.get("description", "")
                candidates.append({
                    "headline": title,
                    "summary":  _clean(summary)[:400],
                    "source":   feed.feed.get("title", "RSS Forex"),
                    "url":      entry.get("link", ""),
                    "_ts":      relevance.rss_ts(entry),
                })
        except Exception as e:
            print(f"[news_forex] Erro ao ler feed {feed_url}: {e}")
            continue

    # 2) Finnhub em inglês (bônus, quando tiver itens)
    if config.FINNHUB_API_KEY:
        try:
            resp = requests.get(
                FINNHUB_NEWS_URL,
                params={"category": "forex", "token": config.FINNHUB_API_KEY},
                timeout=15,
            )
            resp.raise_for_status()
            for item in resp.json():
                headline = item.get("headline", "")
                summary  = item.get("summary", "")
                if not _finnhub_relevant(headline, summary):
                    continue
                key = headline.lower()[:60]
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "headline": headline,
                    "summary":  summary,
                    "source":   item.get("source", "Finnhub"),
                    "url":      item.get("url", ""),
                    "_ts":      item.get("datetime"),
                })
        except Exception as e:
            print(f"[news_forex] Finnhub indisponível: {e}")

    if not candidates:
        print("[news_forex] Nenhuma fonte retornou itens. Usando dados de exemplo.")
        return relevance.rank(MOCK_NEWS, limit=limit)

    return relevance.rank(candidates, limit=limit, max_age_h=max_age_h)


if __name__ == "__main__":
    for n in fetch_forex_news(limit=8):
        print(f"[{relevance.score(n['headline'], n.get('summary','')):+3d}] {n['headline'][:75]}")
