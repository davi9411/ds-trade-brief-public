"""
Registro e relatório de consumo de tokens da rotina na nuvem.

- record(): acrescenta uma linha em usage/usage_log.jsonl (uma por sessão da rotina).
- rebuild(): regenera usage/USAGE.md a partir do log, anexando as notas manuais
  em usage/NOTAS.md (observações manuais), se existir.

Os números vêm do próprio transcript da sessão (routine/measure_usage.py), então
são medidos, não estimados. Duas colunas importam:
  - "novos" = input + output + cache criado: o que a sessão realmente processou
    pela primeira vez.
  - "cache lido" = contexto reaproveitado a cada turno; é barato e domina o total bruto.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "usage" / "usage_log.jsonl"
REPORT = ROOT / "usage" / "USAGE.md"
NOTES = ROOT / "usage" / "NOTAS.md"

TOKEN_KEYS = ("input_tokens", "output_tokens",
              "cache_creation_input_tokens", "cache_read_input_tokens")


def _read_log() -> list[dict]:
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def record(entry: dict) -> None:
    """Acrescenta uma sessão ao log (ignora duplicata da mesma sessão)."""
    rows = _read_log()
    key = entry.get("session") or entry.get("id")
    if key and any((r.get("session") or r.get("id")) == key for r in rows):
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def build_entry(post_ids: list[str], types: list[str], channel: str, mode: str,
                usage: dict | None) -> dict:
    """Monta a linha do log a partir do JSON gerado por measure_usage.py."""
    entry = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "ids": post_ids,
        "types": types,
        "channel": channel,
        "mode": mode,  # routine | gemini | template
    }
    if usage and not usage.get("error"):
        entry["session"] = usage.get("source_file")
        entry["model"] = usage.get("model")
        entry["messages"] = usage.get("assistant_messages")
        for k in TOKEN_KEYS:
            entry[k] = int(usage.get(k) or 0)
    elif usage:
        entry["error"] = usage.get("error")
    return entry


def _fresh(r: dict) -> int:
    return (r.get("input_tokens", 0) + r.get("output_tokens", 0)
            + r.get("cache_creation_input_tokens", 0))


def _fmt(n: int | float) -> str:
    return f"{int(n):,}".replace(",", ".")


def rebuild() -> None:
    rows = _read_log()
    measured = [r for r in rows if r.get("input_tokens") is not None]
    prod = [r for r in measured if r.get("channel") == "official"]

    now = datetime.now(timezone.utc).date()
    cut7 = (now - timedelta(days=7)).isoformat()
    cut30 = (now - timedelta(days=30)).isoformat()

    def agg(sel):
        return {
            "runs": len(sel),
            "fresh": sum(_fresh(r) for r in sel),
            "out": sum(r.get("output_tokens", 0) for r in sel),
            "read": sum(r.get("cache_read_input_tokens", 0) for r in sel),
        }

    a7 = agg([r for r in prod if r["date"] >= cut7])
    a30 = agg([r for r in prod if r["date"] >= cut30])
    avg = agg(prod)

    L = []
    L.append("# Consumo de tokens — rotina DS Trade Brief (nuvem)")
    L.append("")
    L.append("Gerado automaticamente a cada publicação. Os números são **medidos** "
             "no transcript da sessão da rotina (`routine/measure_usage.py`), não estimados. "
             "A medição fica ligeiramente abaixo do real, porque o commit/push e a resposta "
             "final acontecem depois da leitura.")
    L.append("")
    L.append("- **Novos** = entrada + saída + cache criado: o que a sessão processou pela primeira vez.")
    L.append("- **Cache lido** = contexto reaproveitado em cada turno. É barato e domina o total bruto.")
    L.append("")
    L.append("## Resumo (só envios oficiais)")
    L.append("")
    L.append("| Janela | Sessões | Tokens novos | Saída | Cache lido |")
    L.append("|---|---:|---:|---:|---:|")
    L.append(f"| Últimos 7 dias | {a7['runs']} | {_fmt(a7['fresh'])} | {_fmt(a7['out'])} | {_fmt(a7['read'])} |")
    L.append(f"| Últimos 30 dias | {a30['runs']} | {_fmt(a30['fresh'])} | {_fmt(a30['out'])} | {_fmt(a30['read'])} |")
    if avg["runs"]:
        L.append(f"| **Média por sessão** | {avg['runs']} | {_fmt(avg['fresh'] / avg['runs'])} | "
                 f"{_fmt(avg['out'] / avg['runs'])} | {_fmt(avg['read'] / avg['runs'])} |")
    L.append("")
    L.append("## Últimas sessões")
    L.append("")
    L.append("| Data (UTC) | Posts | Canal | Modo | Msgs | Novos | Saída | Cache lido |")
    L.append("|---|---|---|---|---:|---:|---:|---:|")
    for r in reversed(rows[-40:]):
        posts = ", ".join(r.get("types", [])) or "-"
        if r.get("input_tokens") is None:
            tail = f"| - | - | - | - |"
            if r.get("error"):
                tail = f"| - | - | - | erro: {r['error'][:40]} |"
        else:
            tail = (f"| {r.get('messages', '-')} | {_fmt(_fresh(r))} | "
                    f"{_fmt(r.get('output_tokens', 0))} | {_fmt(r.get('cache_read_input_tokens', 0))} |")
        canal = "oficial" if r.get("channel") == "official" else "teste"
        L.append(f"| {r.get('date', '-')} | {posts} | {canal} | {r.get('mode', '-')} {tail}")
    L.append("")

    if NOTES.exists():
        L.append(NOTES.read_text(encoding="utf-8").rstrip())
        L.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
