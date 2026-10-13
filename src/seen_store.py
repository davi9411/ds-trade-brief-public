"""
Memória de notícias já postadas — evita repetir a mesma matéria dia após dia.

Guarda as URLs já publicadas num JSON (data/seen_news.json), com a data, e
descarta entradas antigas. No GitHub Actions o arquivo é mantido entre execuções
via actions/cache (ver workflow); localmente fica em data/ (no .gitignore).
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "data" / "seen_news.json"
RETENTION_DAYS = 6


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_seen() -> set[str]:
    """Conjunto de URLs já postadas (dentro da janela de retenção)."""
    return set(_load().keys())


def mark_seen(urls) -> None:
    """Marca URLs como postadas hoje e poda entradas antigas."""
    data = _load()
    today = _today()
    for u in urls:
        if u:
            data[u] = today

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=RETENTION_DAYS)).isoformat()
    data = {u: d for u, d in data.items() if d >= cutoff}

    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
