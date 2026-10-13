"""
Sinais do brief — os elementos de assinatura da DS Trade.

Dois cálculos determinísticos (números calculados aqui, voz fica com o Gemini):

1. Termômetro do Mercado  → mede a "temperatura" de cada seção combinando o
   movimento real de preço (prices.py) com a intensidade das notícias do dia.
   Resultado: um medidor visual recorrente que vira marca registrada.

2. Manchete do Dia        → escolhe automaticamente a notícia de maior
   relevância entre TODAS as seções, pra abrir o brief como capa de jornal.
"""

from src.sources import relevance

# Mapeia os rótulos de ativos de prices.py para cada seção.
_SECTION_ASSETS = {
    "forex":  ["EUR/USD", "GBP/USD", "Ouro (XAU/USD)", "Dólar (USD/BRL)"],
    "crypto": ["Bitcoin (BTC)"],
    "b3":     ["Ibovespa", "Dólar (USD/BRL)"],
}

# Limiares de |variação %| por seção (cripto se move mais que forex).
_THRESHOLDS = {
    "forex":  (0.3, 0.6, 1.2),
    "crypto": (1.5, 3.0, 6.0),
    "b3":     (0.6, 1.2, 2.5),
}

# Medidor visual por nível (0 a 3). Elemento de marca — mantido consistente.
_GAUGE = {
    0: "🧊 <b>Termômetro:</b> mercado tranquilo",
    1: "🌤️ <b>Termômetro:</b> movimento leve",
    2: "🔥 <b>Termômetro:</b> mercado movimentado",
    3: "🌋 <b>Termômetro:</b> dia agitado",
}


def _price_level(pct_abs: float, section: str) -> int:
    low, mid, high = _THRESHOLDS[section]
    if pct_abs >= high:
        return 3
    if pct_abs >= mid:
        return 2
    if pct_abs >= low:
        return 1
    return 0


def _news_level(top_score: int) -> int:
    if top_score >= 20:
        return 3
    if top_score >= 12:
        return 2
    if top_score >= 6:
        return 1
    return 0


def section_heat(section: str, news_items: list[dict], prices: list[dict]) -> str:
    """Termômetro de uma seção.

    O movimento real de preço é o motor primário (varia de verdade todo dia).
    Uma notícia macro forte (Fed, Copom, CPI…) dá um empurrão de UMA casa.
    Se não houver preço pra seção, cai pro nível de intensidade de notícia.
    """
    labels = _SECTION_ASSETS.get(section, [])
    matched = False
    pct_abs = 0.0
    for p in prices:
        if p.get("asset") in labels:
            matched = True
            pct_abs = max(pct_abs, abs(p.get("change_pct", 0.0)))

    news_top = relevance.top_score(news_items)

    if matched:
        # preço manda; notícia macro forte (>=18) sobe uma casa
        level = min(3, _price_level(pct_abs, section) + (1 if news_top >= 18 else 0))
    else:
        level = _news_level(news_top)

    return _GAUGE[level]


def headline_of_day(sections: dict[str, list[dict]]) -> dict | None:
    """Escolhe a notícia mais relevante entre todas as seções (cada lista já
    vem ranqueada, então comparamos o topo de cada uma).

    Retorna {"section", "headline", "summary"} ou None se não houver notícia.
    """
    best, best_score = None, -10**9
    for name, items in sections.items():
        if not items:
            continue
        top = items[0]
        s = relevance.score(top.get("headline", ""), top.get("summary", ""))
        if s > best_score:
            best_score = s
            best = {
                "section":  name,
                "headline": top.get("headline", ""),
                "summary":  top.get("summary", ""),
            }
    return best
