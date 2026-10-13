#!/usr/bin/env python3
"""
Mede os tokens consumidos pela própria sessão da rotina (Claude Code na nuvem).

Uso (dentro da rotina, no fim da execução):
    python3 routine/measure_usage.py <post_id> [<post_id> ...]

Lê o transcript mais recente em ~/.claude/projects/*/*.jsonl (no ambiente da
rotina fica em /root/.claude/projects/-home-user-<repo>/<uuid>.jsonl), soma o
campo `usage` das mensagens do assistente — deduplicando por id, porque o
mesmo id aparece em várias linhas durante o streaming — e grava
routine/out/<post_id>.usage.json.

Observação: é uma medição ligeiramente subestimada. As últimas mensagens
(commit/push e resposta final) acontecem depois da leitura e não entram.
Nunca falha: se não achar o transcript, grava o motivo no JSON.
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone

FIELDS = ("input_tokens", "output_tokens",
          "cache_creation_input_tokens", "cache_read_input_tokens")


def _candidates() -> list[str]:
    roots = {os.path.expanduser("~"), "/root", "/home/user"}
    found = []
    for root in roots:
        found += glob.glob(os.path.join(root, ".claude", "projects", "*", "*.jsonl"))
    return sorted(set(found), key=os.path.getmtime, reverse=True)


def _sum_usage(path: str) -> dict:
    per_id: dict[str, dict] = {}
    model = None
    first_ts = last_ts = None

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            msg = d.get("message") if isinstance(d.get("message"), dict) else None
            if not msg or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            model = msg.get("model") or model
            mid = msg.get("id") or d.get("uuid") or str(len(per_id))
            cur = {k: int(usage.get(k) or 0) for k in FIELDS}
            prev = per_id.get(mid)
            # Mesmo id em várias linhas: o streaming reenvia o usage; fica o maior.
            if prev is None or sum(cur.values()) >= sum(prev.values()):
                per_id[mid] = cur

    totals = {k: sum(v[k] for v in per_id.values()) for k in FIELDS}
    return {
        "model": model,
        "assistant_messages": len(per_id),
        **totals,
        "first_event": first_ts,
        "last_event": last_ts,
    }


def main() -> int:
    ids = sys.argv[1:] or ["sem_id"]
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)

    # A sessão é uma só, mesmo que tenha escrito vários posts (domingo = 2):
    # o mesmo total vai em cada arquivo e o orquestrador deduplica pela sessão.
    result = {"ids": ids,
              "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        files = _candidates()
        if not files:
            result["error"] = "transcript nao encontrado em ~/.claude/projects"
        else:
            result["source_file"] = files[0]
            result.update(_sum_usage(files[0]))
    except Exception as e:  # nunca derruba a rotina por causa da medição
        result["error"] = f"{type(e).__name__}: {e}"

    for post_id in ids:
        with open(os.path.join(out_dir, f"{post_id}.usage.json"), "w", encoding="utf-8") as f:
            json.dump({"id": post_id, **result}, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
