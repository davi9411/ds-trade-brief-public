"""
Envio de mensagens para o Telegram.

Robustez: o texto vem com HTML simples (<b>/<i>) gerado pelo Gemini, que às
vezes inclui um '&' solto (ex: "S&P 500") — isso quebra o parse_mode=HTML do
Telegram (400 Bad Request). Escapamos '&' soltos antes de enviar e, se ainda
assim falhar, mandamos em texto puro pra mensagem não deixar de sair.
"""

import re
import requests
from src import config

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# '&' que NÃO faz parte de uma entidade HTML válida (&amp; &lt; &#39; &#x1F;)
_STRAY_AMP = re.compile(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)")
_TAG_RE = re.compile(r"<[^>]+>")


def _escape_stray_amp(text: str) -> str:
    return _STRAY_AMP.sub("&amp;", text)


def send_message(text: str, chat_id: str | None = None) -> dict:
    """Envia uma mensagem em HTML para o Telegram.

    Args:
        text: texto da mensagem (HTML compatível com Telegram).
        chat_id: ID do chat/canal. Se None, usa TELEGRAM_TEST_CHAT_ID.

    Returns:
        dict com a resposta da API do Telegram.

    Raises:
        RuntimeError se TELEGRAM_BOT_TOKEN/chat não estiverem configurados.
        requests.HTTPError se nem o fallback em texto puro for aceito.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN não configurado. Defina no .env ou nos Secrets do GitHub."
        )

    target_chat_id = chat_id or config.TELEGRAM_TEST_CHAT_ID
    if not target_chat_id:
        raise RuntimeError(
            "TELEGRAM_TEST_CHAT_ID não configurado. Defina no .env ou nos Secrets do GitHub."
        )

    url = TELEGRAM_API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)
    safe = _escape_stray_amp(text)

    resp = requests.post(url, json={
        "chat_id": target_chat_id,
        "text": safe,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)

    if not resp.ok:
        # Mostra o motivo real do Telegram (ex: "can't parse entities ...")
        print(f"[telegram] {resp.status_code} ao enviar com HTML: {resp.text}")
        # Fallback: remove as tags e manda como texto puro, pra não perder o post.
        plain = _TAG_RE.sub("", safe)
        resp = requests.post(url, json={
            "chat_id": target_chat_id,
            "text": plain,
            "disable_web_page_preview": True,
        }, timeout=15)
        if resp.ok:
            print("[telegram] Enviado em texto puro (fallback).")

    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    result = send_message("✅ Teste de conexão do bot DS Trade - funcionando!")
    print(result)
