"""
Fonte de notícias: B3 (foco em mini índice / mini dólar / Ibovespa / Selic)
Estratégia: agrega RSS de portais financeiros + AgenciaBrasil (oficial BC),
filtra o que pertence ao mercado BR e ranqueia pelo motor de relevância.

OBS: feeds RSS de portais de notícia mudam de endereço com frequência.
Se um feed parar de retornar itens, troque a URL na lista FEED_URLS.
Use `python -m src.sources.news_b3` para testar rapidamente.
"""

import re

import feedparser
from src import config  # noqa: F401
from src.sources import relevance


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


# Palavras que precisam de verificação de palavra inteira (não substring)
# para não casar "ações" em "operações", "bolsa" em "Bolsa Família", etc.
_WHOLE_WORD_KW = {
    "ações ordinárias", "ações preferenciais", "vale s.a", "win", "wdo",
}

_KW_PATTERNS = {
    kw: re.compile(r"(?<![a-záàãâéêíóôõúüç])" + re.escape(kw) + r"(?![a-záàãâéêíóôõúüç])", re.IGNORECASE)
    for kw in _WHOLE_WORD_KW
}

# Todos os feeds são varridos e os resultados agregados — não paramos no
# primeiro com itens, porque cada feed cobre ângulos diferentes.
# AgenciaBrasil é a fonte oficial de decisões do Banco Central (COPOM/Selic).
FEED_URLS = [
    "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml",  # oficial BC / COPOM / Selic
    "https://exame.com/invest/feed/",                           # maior cobertura mercado BR
    "https://www.infomoney.com.br/feed/",                       # mercado BR
    "https://www.moneytimes.com.br/mercados/feed/",             # mercado BR
    "https://br.investing.com/rss/stock_Indices.rss",           # Ibovespa / índices
    "https://www.seudinheiro.com/feed/",                        # mercado BR
]

# Palavras-chave para filtrar notícias que PERTENCEM ao universo B3/mercado BR.
# (o RANKING de relevância vem depois, via src.sources.relevance)
KEYWORDS = [
    # Índices e ativos — termos específicos de mercado
    "ibovespa", "b3", "mini índice", "mini dólar", "win", "wdo",
    "ifix", "ibrx", "petrobras", "vale s.a", "ações ordinárias", "ações preferenciais",
    "bolsa de valores", "bolsa brasileira", "pregão",
    # Câmbio
    "dólar", "dolar", "câmbio", "taxa de câmbio",
    # Juros e política monetária — crítico para COPOM/Selic
    "selic", "copom", "taxa selic", "taxa básica", "taxa de juros",
    "banco central", "bcb", "política monetária", "corte de juros",
    "alta de juros", "reunião do copom", "super quarta", "galípolo",
    "0,25", "0,50", "25 pontos", "50 pontos",
    # Economia Brasil — termos específicos
    "inflação", "ipca", "igpm", "pib brasileiro", "economia brasileira",
    "tesouro direto", "renda fixa", "fundo imobiliário", "fii",
]

MOCK_NEWS = [
    {
        "headline": "Ibovespa fecha em alta puxado por ações de bancos e mineradoras",
        "summary": "Mercado repercute expectativas sobre a próxima decisão do Copom "
                    "e movimento do dólar frente ao real.",
        "source": "Exemplo (mock)",
        "url": "",
    },
    {
        "headline": "Dólar opera em leve queda à espera de indicadores nos EUA",
        "summary": "Investidores monitoram divulgação de dados econômicos americanos "
                    "que podem influenciar o mini dólar (WDO) na B3.",
        "source": "Exemplo (mock)",
        "url": "",
    },
]


def _matches_keywords(title: str) -> bool:
    """Filtra apenas pelo título com matching de palavra inteira para keywords
    ambíguas — evita 'ações' casar em 'operações', 'bolsa' em 'Bolsa Família'."""
    t = title.lower()
    for kw in KEYWORDS:
        if kw in _WHOLE_WORD_KW:
            if _KW_PATTERNS[kw].search(t):
                return True
        else:
            if kw in t:
                return True
    return False


def fetch_b3_news(limit: int = 5, max_age_h: float | None = None) -> list[dict]:
    """Agrega notícias de B3/Ibovespa/Selic de todos os feeds e retorna
    ranqueadas por relevância (movimentos de mercado e COPOM/Selic primeiro).
    """
    seen: set[str] = set()
    candidates: list[dict] = []

    for feed_url in FEED_URLS:
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                continue

            for entry in feed.entries:
                title   = entry.get("title", "").strip()
                summary = _strip_html(
                    entry.get("summary", "") or entry.get("description", "")
                ).strip()

                if not _matches_keywords(title):
                    continue

                title_key = title.lower()[:60]
                if title_key in seen:
                    continue
                seen.add(title_key)

                candidates.append({
                    "headline": title,
                    "summary":  summary[:400],
                    "source":   feed.feed.get("title", ""),
                    "url":      entry.get("link", ""),
                    "_ts":      relevance.rss_ts(entry),
                })

        except Exception as e:
            print(f"[news_b3] Erro ao ler feed {feed_url}: {e}")
            continue

    if not candidates:
        print("[news_b3] Nenhum feed retornou itens relevantes. Usando dados de exemplo.")
        return relevance.rank(MOCK_NEWS, limit=limit)

    return relevance.rank(candidates, limit=limit, max_age_h=max_age_h)


if __name__ == "__main__":
    for n in fetch_b3_news(limit=8):
        print(f"[{relevance.score(n['headline'], n.get('summary','')):+3d}] {n['headline'][:75]}")
