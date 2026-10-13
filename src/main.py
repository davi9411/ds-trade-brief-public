"""
Orquestrador principal do Daily Brief - DS Trade.

Tipos de conteúdo:
  daily_brief  → canal de briefs (seg-sex, 9h Brasília)
  weekly_brief → canal de briefs (domingo, sem convite)
  weekly_main  → canal principal (domingo, com convite)

Uso:
  python -m src.main --auto              # decide pelo dia da semana
  python -m src.main --auto --dry-run    # só imprime, não envia
  python -m src.main --type daily_brief  # força um tipo
  python -m src.main --all-samples --dry-run  # todos os tipos no terminal
"""

import argparse
from datetime import datetime, timedelta, timezone

from src import config
from src import ptdate
from src import quotes
from src import signals
from src import seen_store
from src import telegraph_publisher
from src.generator import generate_post
from src.sources import news_forex, news_crypto, news_b3, economic_calendar, prices
from src import telegram_sender

BR_TZ = timezone(timedelta(hours=-3))

# Janela de recência do brief diário (notícias mais novas que isso).
DAILY_MAX_AGE_H = 36
# Janela do resumo semanal.
WEEKLY_MAX_AGE_H = 24 * 8


# ── Busca de dados por tipo ───────────────────────────────────────────────────

def _pick_fresh_unseen(items: list[dict], seen: set[str], n: int = 3) -> list[dict]:
    """Escolhe as n notícias mais relevantes que ainda NÃO foram postadas.

    Se todas já foram postadas (dia sem novidade), cai pras melhores mesmo assim
    pra não deixar a seção vazia.
    """
    unseen = [it for it in items if it.get("url") and it["url"] not in seen]
    chosen = unseen[:n]
    if not chosen:
        chosen = items[:n]
    return chosen


def _fetch_daily_brief() -> dict:
    weekday = datetime.now(BR_TZ).weekday()
    seen = seen_store.load_seen()
    # Busca um pool maior, filtra recência e remove o que já foi postado.
    forex  = _pick_fresh_unseen(news_forex.fetch_forex_news(limit=12, max_age_h=DAILY_MAX_AGE_H), seen)
    crypto = _pick_fresh_unseen(news_crypto.fetch_crypto_news(limit=12, max_age_h=DAILY_MAX_AGE_H), seen)
    b3     = _pick_fresh_unseen(news_b3.fetch_b3_news(limit=12, max_age_h=DAILY_MAX_AGE_H), seen)
    price_list = prices.fetch_prices()

    sections = {"forex": forex, "crypto": crypto, "b3": b3}
    data = {
        "date":   ptdate.date_pt(),
        "forex":  forex,
        "crypto": crypto,
        "b3":     b3,
        "prices": price_list,
        "selic":  quotes.fetch_selic(),
        # Elementos de assinatura (calculados, não inventados pelo Gemini)
        "heat": {
            "forex":  signals.section_heat("forex",  forex,  price_list),
            "crypto": signals.section_heat("crypto", crypto, price_list),
            "b3":     signals.section_heat("b3",     b3,     price_list),
        },
        "headline_of_day": signals.headline_of_day(sections),
    }
    if weekday == 0:  # segunda-feira: inclui calendário da semana
        data["calendar"] = economic_calendar.fetch_economic_calendar()
    return data


def _fetch_weekly() -> dict:
    # Resumo da semana: janela de ~8 dias, sem dedup (é recapitulação).
    return {
        "forex":  news_forex.fetch_forex_news(limit=4, max_age_h=WEEKLY_MAX_AGE_H),
        "crypto": news_crypto.fetch_crypto_news(limit=4, max_age_h=WEEKLY_MAX_AGE_H),
        "b3":     news_b3.fetch_b3_news(limit=4, max_age_h=WEEKLY_MAX_AGE_H),
    }


def _fetch_weekly_main() -> dict:
    data = _fetch_weekly()
    data["invite_links"] = {
        "telegram": config.TELEGRAM_BRIEF_LINK,
        "whatsapp": config.WHATSAPP_INVITE_LINK or "(em breve)",
    }
    return data


FETCH = {
    "daily_brief":  _fetch_daily_brief,
    "weekly_brief": _fetch_weekly,
    "weekly_main":  _fetch_weekly_main,
}

LABELS = {
    "daily_brief":  "📊 Brief Diário",
    "weekly_brief": "🗞️ Resumo Semanal — canal de briefs",
    "weekly_main":  "🗞️ Resumo Semanal — canal principal",
}


# ── Envio ─────────────────────────────────────────────────────────────────────

def _target_chat(content_type: str) -> str:
    """Retorna o chat_id correto pro tipo de conteúdo."""
    if content_type == "weekly_main":
        return config.TELEGRAM_MAIN_CHAT_ID or config.TELEGRAM_TEST_CHAT_ID
    return config.TELEGRAM_BRIEF_CHAT_ID or config.TELEGRAM_TEST_CHAT_ID


def _wrap_draft(content_type: str, post_text: str) -> str:
    label = LABELS.get(content_type, content_type)
    return (
        f"🧪 <b>RASCUNHO — {label}</b>\n"
        f"────────────────────\n\n"
        f"{post_text}"
    )


def _telegraph_title(content_type: str, data: dict) -> str:
    if content_type == "daily_brief":
        return f"Brief do Mercado {data.get('date', '')} — Forex, Cripto e Ibovespa | DS Trade"
    return "Resumo da Semana nos Mercados — Forex, Cripto e B3 | DS Trade"


def _publish_telegraph(content_type: str, data: dict, post_text: str) -> str | None:
    """Publica o brief no Telegra.ph (web/SEO). Nunca trava o envio se falhar."""
    news_url = config.tme_url(config.TELEGRAM_BRIEF_LINK)
    cta = (f'👉 Receba o brief completo todo dia no nosso canal: '
           f'<a href="{news_url}">{config.TELEGRAM_BRIEF_LINK}</a>')
    try:
        return telegraph_publisher.publish(_telegraph_title(content_type, data), post_text, cta)
    except Exception as e:
        print(f"[main] Telegra.ph indisponível: {e}")
        return None


def _with_footer(content_type: str, post_text: str, page_url: str | None) -> str:
    """Acrescenta rodapé: link da edição (Telegra.ph) e do canal oficial.

    O link do canal oficial entra apenas nos posts do canal de NOTÍCIAS
    (daily_brief e weekly_brief); o weekly_main já está no canal oficial.
    """
    extras = []
    if page_url:
        extras.append(f"📄 <b>Edição completa (compartilhe):</b> {page_url}")
    if content_type in ("daily_brief", "weekly_brief"):
        extras.append(f"📲 <b>Nosso canal oficial:</b> {config.tme_url(config.TELEGRAM_MAIN_LINK)}")

    if not extras:
        return post_text
    return post_text + "\n\n━━━━━━━━━━━━━━━\n" + "\n".join(extras)


_EN_WORDS = {"the", "as", "of", "to", "in", "on", "for", "with", "and", "is", "are",
             "after", "amid", "higher", "lower", "markets", "stocks", "yields"}
_PT_WORDS = {"de", "do", "da", "dos", "das", "com", "em", "para", "que", "não",
             "o", "a", "os", "as", "um", "uma", "após", "sobe", "cai"}


def _looks_english(text: str) -> bool:
    words = [w.strip(".,;:!?()\"'").lower() for w in text.split()]
    en = sum(1 for w in words if w in _EN_WORDS)
    pt = sum(1 for w in words if w in _PT_WORDS)
    return en >= 2 and en > pt


def _fallback_post(content_type: str, data: dict) -> str:
    """Brief de reserva (sem IA): usado só se não houver texto escrito por IA.
    Monta um resumo de manchetes com Termômetro e Manchete do Dia — menos
    'humanizado', mas garante que o post sai."""
    is_daily = content_type == "daily_brief"
    header = "BRIEF DS Trade" if is_daily else "RESUMO DS Trade"
    lines = [f"🟡 <b>{header}</b>"]

    h = data.get("headline_of_day")
    hot = (h or {}).get("headline", "").strip()
    if hot:
        lines.append(f"\n🗞️ <b>HOJE:</b> {hot}")

    if is_daily and data.get("date"):
        lines.append(f"\n📊 <b>BRIEF DO DIA — {data['date']}</b>")
    elif not is_daily:
        lines.append("\n🗞️ <b>RESUMO DA SEMANA</b>")

    heat = data.get("heat", {})
    for key, emo, name in [("forex", "💱", "FOREX"), ("crypto", "₿", "CRIPTO"), ("b3", "📈", "B3")]:
        items = data.get(key, [])
        # Sem IA não há tradução: some com manchete em inglês quando houver em português
        pt_items = [it for it in items if not _looks_english(it.get("headline", ""))]
        items = pt_items or items
        # E não repete a manchete do dia como primeiro bullet
        items = [it for it in items if it.get("headline", "").strip() != hot] or items
        if not items:
            continue
        lines.append("\n━━━━━━━━━━━━━━━")
        lines.append(f"{emo} <b>{name}</b>")
        lines.append("━━━━━━━━━━━━━━━")
        if heat.get(key):
            lines.append(heat[key])
        for it in items[:3]:
            lines.append(f"• {it.get('headline', '')}")

    lines.append("\n<i>⚠️ Conteúdo educacional — não é recomendação de investimento.</i>")
    return "\n".join(lines)


def add_quotes(content_type: str, data: dict, post_text: str) -> str:
    """Brief diário: insere o bloco 💹 COTAÇÕES DO DIA antes do aviso educacional."""
    if content_type != "daily_brief":
        return post_text
    return quotes.add_quotes(post_text, data)


def publish_post(content_type: str, data: dict, post_text: str, chat_id: str,
                 mark_seen: bool = True, dry_run: bool = False) -> str | None:
    """Publica no Telegra.ph, monta o rodapé e envia ao Telegram.

    Ponto único de saída: serve tanto ao caminho com Gemini quanto à rotina na
    nuvem. Retorna a URL do Telegra.ph (ou None).
    """
    post_text = add_quotes(content_type, data, post_text)  # idempotente
    page_url = _publish_telegraph(content_type, data, post_text)
    final_text = _with_footer(content_type, post_text, page_url)

    if dry_run:
        print("[main] --dry-run ativo, não enviando.\n")
        print(_wrap_draft(content_type, final_text))
        return page_url

    telegram_sender.send_message(final_text, chat_id=chat_id)
    print(f"[main] Enviado → chat {chat_id}")
    if page_url:
        print(f"[main] Telegra.ph: {page_url}")
    # Registra as notícias do brief diário como já postadas (anti-repetição)
    if mark_seen and content_type == "daily_brief":
        urls = [it.get("url") for sec in ("forex", "crypto", "b3") for it in data.get(sec, [])]
        seen_store.mark_seen([u for u in urls if u])
    return page_url


def run_for_type(content_type: str, dry_run: bool = False) -> str:
    print(f"\n[main] Gerando: {content_type}")
    data = FETCH[content_type]()
    try:
        post_text = generate_post(content_type, data)
    except Exception as e:
        print(f"[main] Gemini falhou em todos os modelos ({e}); usando brief de reserva.")
        post_text = _fallback_post(content_type, data)

    publish_post(content_type, data, post_text, _target_chat(content_type), dry_run=dry_run)
    return post_text


# ── Lógica de dia da semana ───────────────────────────────────────────────────

def run_auto(dry_run: bool = False):
    weekday = datetime.now(BR_TZ).weekday()
    if weekday < 5:       # seg-sex
        run_for_type("daily_brief", dry_run=dry_run)
    elif weekday == 6:    # domingo
        run_for_type("weekly_main",  dry_run=dry_run)
        run_for_type("weekly_brief", dry_run=dry_run)
    else:                 # sábado
        print("[main] Sábado — sem post agendado.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DS Trade - Daily Brief Bot")
    parser.add_argument("--type", choices=list(LABELS.keys()),
                        help="Força um tipo específico de conteúdo.")
    parser.add_argument("--auto", action="store_true",
                        help="Decide o tipo automaticamente pelo dia da semana (Brasília).")
    parser.add_argument("--all-samples", action="store_true",
                        help="Gera um exemplo de cada tipo (útil para testes).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Não envia ao Telegram, apenas imprime.")
    parser.add_argument("--routine-auto", action="store_true",
                        help="Ciclo oficial com a rotina na nuvem (Claude escreve, Actions publica).")
    parser.add_argument("--routine-test", choices=list(LABELS.keys()) + ["weekly"],
                        help="Mesmo ciclo, mas envia só ao grupo de testes e não marca notícias como vistas. "
                             "'weekly' testa os dois posts de domingo de uma vez.")
    parser.add_argument("--routine-prepare", choices=list(LABELS.keys()),
                        help="Só coleta e grava routine/input/<id>.json localmente (depuração).")
    parser.add_argument("--check-quotes", action="store_true",
                        help="Só busca as cotações e mostra o bloco (não envia nada). Serve para checar as fontes.")
    args = parser.parse_args()

    config.warn_missing_keys()

    if args.check_quotes:
        from src.sources import prices as _prices
        data = {"prices": _prices.fetch_prices(), "selic": quotes.fetch_selic()}
        print("selic:", data["selic"])
        print(quotes.build_block(data) or "(bloco vazio)")
        return

    if args.routine_auto or args.routine_test or args.routine_prepare:
        import sys
        from src import routine
        if args.routine_prepare:
            pid = routine._post_id(args.routine_prepare, "test")
            routine.prepare(args.routine_prepare, pid, "test")
            print(f"[routine] gravado routine/input/{pid}.json")
            return
        if args.routine_test:
            only = (["weekly_main", "weekly_brief"] if args.routine_test == "weekly"
                    else [args.routine_test])
            sys.exit(routine.run("test", only=only))
        sys.exit(routine.run("official"))

    if args.all_samples:
        for ct in LABELS:
            run_for_type(ct, dry_run=args.dry_run)
        return

    if args.type:
        run_for_type(args.type, dry_run=args.dry_run)
        return

    if args.auto:
        run_auto(dry_run=args.dry_run)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
