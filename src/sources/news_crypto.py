"""
Fonte de notícias: CRIPTO (geral)
Estratégia: agrega RSS de todos os portais brasileiros e ranqueia pelo motor
de relevância compartilhado — preço/mercado primeiro, produto por último.

Use `python -m src.sources.news_crypto` para testar rapidamente.
"""

import re

import feedparser
from src import config  # noqa: F401
from src.sources import relevance

FEED_URLS = [
    "https://www.criptofacil.com/feed/",
    "https://portaldobitcoin.uol.com.br/feed/",
    "https://livecoins.com.br/feed/",
    "https://www.moneytimes.com.br/criptomoedas/feed/",
]

MOCK_NEWS = [
    {
        "headline": "Bitcoin testa região de resistência após semana de alta volatilidade",
        "summary": "BTC se aproxima de níveis-chave enquanto o mercado avalia o "
                    "apetite por risco em ativos digitais.",
        "source": "Exemplo (mock)",
        "url": "",
    },
    {
        "headline": "Ethereum mantém suporte importante apesar de saída de capital",
        "summary": "Dados on-chain mostram redução no volume de negociação, "
                    "mas o preço se mantém estável acima de suporte técnico.",
        "source": "Exemplo (mock)",
        "url": "",
    },
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_crypto_news(limit: int = 5, max_age_h: float | None = None) -> list[dict]:
    """Agrega notícias de cripto de todos os feeds e retorna ranqueadas
    por relevância para traders (preço/mercado primeiro, produto por último).
    """
    seen: set[str] = set()
    candidates: list[dict] = []

    for feed_url in FEED_URLS:
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                continue

            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                title_key = title.lower()[:60]
                if title_key in seen:
                    continue
                seen.add(title_key)

                summary = entry.get("summary", "") or entry.get("description", "")
                candidates.append({
                    "headline": title,
                    "summary":  _clean(summary)[:400],
                    "source":   feed.feed.get("title", "RSS Cripto"),
                    "url":      entry.get("link", ""),
                    "_ts":      relevance.rss_ts(entry),
                })

        except Exception as e:
            print(f"[news_crypto] Erro ao ler feed {feed_url}: {e}")
            continue

    if not candidates:
        print("[news_crypto] Nenhum feed retornou itens. Usando dados de exemplo.")
        return relevance.rank(MOCK_NEWS, limit=limit)

    return relevance.rank(candidates, limit=limit, max_age_h=max_age_h)


if __name__ == "__main__":
    for n in fetch_crypto_news(limit=8):
        print(f"[{relevance.score(n['headline'], n.get('summary','')):+3d}] {n['headline'][:75]}")
