"""
Configuração central do projeto.
Carrega variáveis de ambiente do .env (uso local) ou do ambiente
do sistema (uso em GitHub Actions, via Secrets).
"""

import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BRIEF_CHAT_ID = os.getenv("TELEGRAM_BRIEF_CHAT_ID", "")   # canal de briefs diários
TELEGRAM_MAIN_CHAT_ID  = os.getenv("TELEGRAM_MAIN_CHAT_ID", "")    # canal principal (weekly)
# Legado: usado em --all-samples / testes quando os canais ainda não estão configurados
TELEGRAM_TEST_CHAT_ID  = os.getenv("TELEGRAM_TEST_CHAT_ID", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# Links de convite (usados no post semanal do canal principal)
TELEGRAM_BRIEF_LINK  = os.getenv("TELEGRAM_BRIEF_LINK", "@dstradenoticias")  # canal de notícias
TELEGRAM_MAIN_LINK   = os.getenv("TELEGRAM_MAIN_LINK", "@ds_tradefx")        # canal oficial
WHATSAPP_INVITE_LINK = os.getenv("WHATSAPP_INVITE_LINK", "")

# Telegra.ph (publicação web automática dos briefs — SEO/compartilhamento)
TELEGRAPH_ACCESS_TOKEN = os.getenv("TELEGRAPH_ACCESS_TOKEN", "")


def tme_url(handle: str) -> str:
    """Converte '@canal' ou 'canal' em https://t.me/canal. Aceita URL pronta."""
    handle = (handle or "").strip()
    if handle.startswith("http"):
        return handle
    return "https://t.me/" + handle.lstrip("@")


def warn_missing_keys():
    missing = []
    for name, value in [
        ("TELEGRAM_BOT_TOKEN",     TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_BRIEF_CHAT_ID", TELEGRAM_BRIEF_CHAT_ID),
        ("GEMINI_API_KEY",         GEMINI_API_KEY),
        ("FINNHUB_API_KEY",        FINNHUB_API_KEY),
    ]:
        if not value:
            missing.append(name)
    if missing:
        print(f"[config] Aviso: variáveis não configuradas: {', '.join(missing)}")
