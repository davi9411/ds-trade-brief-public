"""
Publicação automática dos briefs no Telegra.ph.

O Telegra.ph é a ferramenta de páginas instantâneas do Telegram: páginas
gratuitas, sem servidor nem domínio, que o Google indexa. Cada brief vira uma
página pública (legível por qualquer um, mesmo sem Telegram) com um convite de
volta pro canal — funciona como "site" de SEO sem ter site.

Fluxo:
  publish(title, html_text, cta) -> url da página
Falha graciosamente (retorna None) pra nunca travar o envio ao Telegram.
"""

import json
from html.parser import HTMLParser

import requests

from src import config

API = "https://api.telegra.ph"

# Tags inline do HTML do Telegram que o Telegra.ph entende (com mapeamento).
_INLINE_MAP = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u", "s": "s", "a": "a", "code": "code"}


class _InlineParser(HTMLParser):
    """Converte uma linha com <b>/<i>/<a> em nós do Telegra.ph."""

    def __init__(self):
        super().__init__()
        self.nodes: list = []
        self.stack: list = []

    def handle_starttag(self, tag, attrs):
        tag = _INLINE_MAP.get(tag)
        if not tag:
            return
        node = {"tag": tag, "children": []}
        ad = dict(attrs)
        if tag == "a" and "href" in ad:
            node["attrs"] = {"href": ad["href"]}
        self._append(node)
        self.stack.append(node)

    def handle_endtag(self, tag):
        tag = _INLINE_MAP.get(tag)
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if data:
            self._append(data)

    def _append(self, node):
        if self.stack:
            self.stack[-1]["children"].append(node)
        else:
            self.nodes.append(node)


def _inline_nodes(line: str) -> list:
    p = _InlineParser()
    p.feed(line)
    return p.nodes or [line]


def _to_content(html_text: str) -> list:
    """Converte o texto do brief (HTML simples + quebras de linha) em nós."""
    content = []
    for raw in html_text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        # Linha só de separador vira <hr>
        if set(line) <= set("━─-—_=•"):
            content.append({"tag": "hr"})
            continue
        content.append({"tag": "p", "children": _inline_nodes(line)})
    return content


def _ensure_token() -> str | None:
    """Usa o token salvo; se não houver, cria uma conta Telegra.ph na hora."""
    if config.TELEGRAPH_ACCESS_TOKEN:
        return config.TELEGRAPH_ACCESS_TOKEN
    try:
        r = requests.post(f"{API}/createAccount", data={
            "short_name": "DSTrade",
            "author_name": "DS Trade",
            "author_url": config.tme_url(config.TELEGRAM_BRIEF_LINK),
        }, timeout=15).json()
        if r.get("ok"):
            tok = r["result"]["access_token"]
            print(f"[telegraph] Conta criada. Salve este token em TELEGRAPH_ACCESS_TOKEN:\n{tok}")
            return tok
    except Exception as e:
        print(f"[telegraph] Falha ao criar conta: {e}")
    return None


def publish(title: str, html_text: str, cta: str | None = None) -> str | None:
    """Publica o brief como página Telegra.ph e retorna a URL (ou None se falhar)."""
    token = _ensure_token()
    if not token:
        return None

    content = _to_content(html_text)
    if cta:
        content.append({"tag": "p", "children": _inline_nodes(cta)})

    try:
        r = requests.post(f"{API}/createPage", data={
            "access_token": token,
            "title": title[:256],
            "author_name": "DS Trade",
            "author_url": config.tme_url(config.TELEGRAM_BRIEF_LINK),
            "content": json.dumps(content, ensure_ascii=False),
            "return_content": "false",
        }, timeout=20).json()
        if r.get("ok"):
            return r["result"]["url"]
        print(f"[telegraph] Erro ao publicar: {r.get('error')}")
    except Exception as e:
        print(f"[telegraph] Falha ao publicar: {e}")
    return None
