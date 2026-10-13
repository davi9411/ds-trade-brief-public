"""
Orquestração do brief com a rotina na nuvem: o Claude escreve, o Actions publica.

Por que existe: o Gemini ficou sem créditos (402) e o brief passou a sair no
template de emergência. A rotina na nuvem usa o plano do Claude do dono, mas o
ambiente dela só enxerga o GitHub (proxy de saída bloqueia RSS, Telegram e
Telegra.ph). Então a divisão é:

  Actions (rede aberta, segredos)          Rotina na nuvem (só repo)
  ───────────────────────────────          ─────────────────────────
  1. coleta notícias/preços/sinais
  2. grava routine/input/<id>.json e
     faz push no master
                                           3. lê o input + system_prompt,
                                              escreve routine/out/<id>.html,
                                              mede tokens, push em claude/*
  4. espera o arquivo aparecer, valida
  5. publica (Telegra.ph + Telegram)
  6. arquiva em posts/, registra uso,
     apaga a branch claude/* consumida

Se a rotina não responder a tempo (ou entregar texto inválido), o Actions cai no
Gemini e, por último, no template, avisa no grupo de testes e marca a execução
como falha (o GitHub manda e-mail). O post nunca deixa de sair.
"""

import html
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from src import config, ptdate, telegram_sender, usage_report

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "routine" / "input"
POSTS_DIR = ROOT / "posts"
TEST_POSTS_DIR = POSTS_DIR / "test"

MARKERS = {
    "daily_brief": "BRIEF DS Trade",
    "weekly_brief": "RESUMO DS Trade",
    "weekly_main": "RESUMO DS Trade",
}
MAX_POST_CHARS = 3200   # limite do Telegram é 4096; o rodapé ocupa ~300 e o bloco de cotações ~450
MIN_POST_CHARS = 200
POLL_SECONDS = 20


# ── git ───────────────────────────────────────────────────────────────────────

def _ci() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falhou: {r.stderr.strip()[:300]}")
    return r


def _configure_git() -> None:
    _git("config", "user.name", "github-actions[bot]")
    _git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")


def _commit_push(message: str, paths: list[str]) -> None:
    """Commita as paths e faz push no master (1 retry com rebase)."""
    if not _ci():
        print("[routine] (local) sem git: nada foi commitado.")
        return
    for p in paths:
        _git("add", "-A", "--", p, check=False)  # path inexistente/ignorado não é erro
    if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    _git("commit", "-q", "-m", message)
    for _ in range(2):
        if _git("push", "-q", "origin", "HEAD:master", check=False).returncode == 0:
            return
        _git("pull", "--rebase", "-q", "origin", "master", check=False)
    raise RuntimeError("push para master falhou depois de 2 tentativas")


# ── planejamento ──────────────────────────────────────────────────────────────

def types_for_today() -> list[str]:
    wd = ptdate.now_br().weekday()
    if wd < 5:
        return ["daily_brief"]
    if wd == 6:
        return ["weekly_main", "weekly_brief"]
    return []  # sábado


def _post_id(content_type: str, channel: str) -> str:
    pid = f"{ptdate.today_iso()}_{content_type}"
    if channel == "test":
        pid += f"_test{ptdate.now_br():%H%M}"
    return pid


def _chat_for(content_type: str, channel: str) -> str:
    if channel == "test":
        if not config.TELEGRAM_TEST_CHAT_ID:
            raise RuntimeError("TELEGRAM_TEST_CHAT_ID não configurado (canal de teste).")
        return config.TELEGRAM_TEST_CHAT_ID
    from src import main as m
    return m._target_chat(content_type)


_TAG_RE = re.compile(r"<[^>]+>")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize(obj):
    """Higieniza o texto de terceiros antes de entregá-lo à rotina: tira HTML e
    caracteres de controle, colapsa espaços e encurta o resumo."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("headline", "summary") and isinstance(v, str):
                v = _CTRL_RE.sub("", _TAG_RE.sub(" ", v))
                v = re.sub(r"\s+", " ", v).strip()
                v = v[:300] if k == "summary" else v[:220]
            out[k] = _sanitize(v)
        return out
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    return obj


def prepare(content_type: str, post_id: str, channel: str) -> dict:
    """Coleta tudo e grava routine/input/<id>.json (o que a rotina vai ler)."""
    from src import main as m
    from src.generator import TYPE_INSTRUCTIONS

    data = _sanitize(m.FETCH[content_type]())
    data.setdefault("date", ptdate.date_pt())
    payload = {
        "id": post_id,
        "type": content_type,
        "channel": channel,
        "date_iso": ptdate.today_iso(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "instructions": TYPE_INSTRUCTIONS[content_type],
        "data": data,
    }
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    (INPUT_DIR / f"{post_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# ── espera e validação do texto da rotina ─────────────────────────────────────

def _find_post(post_id: str):
    """Procura routine/out/<id>.html em qualquer branch claude/* do remoto."""
    refs = _git("for-each-ref", "--format=%(refname:short)",
                "refs/remotes/origin/claude/", check=False).stdout.split()
    for ref in refs:
        r = _git("show", f"{ref}:routine/out/{post_id}.html", check=False)
        if r.returncode == 0 and r.stdout.strip():
            u = _git("show", f"{ref}:routine/out/{post_id}.usage.json", check=False)
            usage = None
            if u.returncode == 0:
                try:
                    usage = json.loads(u.stdout)
                except Exception:
                    usage = None
            return ref, r.stdout, usage
    return None


def _wait_for_post(post_id: str, deadline: float):
    last_log = 0.0
    while True:
        _git("fetch", "-q", "--prune", "origin",
             "+refs/heads/claude/*:refs/remotes/origin/claude/*", check=False)
        found = _find_post(post_id)
        if found:
            return found
        now = time.time()
        if now >= deadline:
            return None
        if now - last_log >= 120:
            print(f"[routine] aguardando a rotina… ({int(deadline - now)}s restantes)")
            last_log = now
        time.sleep(POLL_SECONDS)


_LINK_RE = re.compile(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+|\bt\.me/[^\s<>\"]+|<a[\s>])", re.I)
_HANDLE_RE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{4,}")


def _allowed_links(payload: dict) -> set[str]:
    """Links/@ que o post pode citar: só os canais da DS Trade e o convite do semanal."""
    inv = (payload.get("data") or {}).get("invite_links") or {}
    vals = [inv.get("telegram"), inv.get("whatsapp"), config.TELEGRAM_BRIEF_LINK,
            config.TELEGRAM_MAIN_LINK, config.WHATSAPP_INVITE_LINK]
    allowed = set()
    for v in vals:
        v = (v or "").strip()
        if v and not v.startswith("("):          # ignora o placeholder "(em breve)"
            allowed.add(v.lower().lstrip("@"))
    return allowed


def _clean_and_validate(raw: str, content_type: str,
                        allowed: set[str] | None = None) -> tuple[str, list[str]]:
    text = raw.strip()
    # Se o modelo embrulhou o post em bloco de código, desembrulha.
    text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text).strip()

    problems = []
    # Defesa contra injeção vinda de sites de terceiros: o post não tem motivo para
    # citar links ou @ que não sejam os canais da própria DS Trade.
    allowed = allowed or set()
    for m_ in _LINK_RE.findall(text) + _HANDLE_RE.findall(text):
        low = m_.lower().lstrip("@")
        if m_.lower().startswith("<a") or not any(a and a in low for a in allowed):
            problems.append(f"link/@ não permitido: {m_[:40]}")
    if len(text) < MIN_POST_CHARS:
        problems.append(f"texto curto demais ({len(text)} caracteres)")
    if len(text) > MAX_POST_CHARS:
        problems.append(f"texto longo demais ({len(text)} caracteres)")
    if MARKERS[content_type] not in text:
        problems.append(f"cabeçalho '{MARKERS[content_type]}' ausente")
    for tag in ("b", "i"):
        if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
            problems.append(f"tag <{tag}> desbalanceada")
    return text, problems


# ── reserva (sem a rotina) e alertas ──────────────────────────────────────────

def _fallback(content_type: str, data: dict) -> tuple[str, str]:
    from src import main as m
    from src.generator import generate_post
    try:
        return generate_post(content_type, data), "gemini"
    except Exception as e:
        print(f"[routine] Gemini também falhou ({str(e)[:120]}); usando o template.")
        return m._fallback_post(content_type, data), "template"


def _alert(text: str) -> None:
    chat = config.TELEGRAM_TEST_CHAT_ID
    if not chat:
        return
    try:
        telegram_sender.send_message(
            "⚠️ <b>DS Trade Brief — atenção</b>\n" + html.escape(text), chat_id=chat)
    except Exception as e:
        print(f"[routine] não consegui enviar o alerta: {e}")


# ── arquivo ───────────────────────────────────────────────────────────────────

def _archive(post_id, channel, payload, post_text, page_url, mode, problems) -> None:
    folder = TEST_POSTS_DIR if channel == "test" else POSTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{post_id}.html").write_text(post_text, encoding="utf-8")
    meta = dict(payload)
    meta["result"] = {
        "mode": mode,
        "telegraph_url": page_url,
        "chars": len(post_text),
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "problems": problems,
    }
    (folder / f"{post_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = INPUT_DIR / f"{post_id}.json"
    if pending.exists():
        pending.unlink()


def _delete_remote_branch(ref: str) -> None:
    name = ref.split("/", 1)[1] if "/" in ref else ref
    if name.startswith("claude/"):  # só apaga branches da própria rotina
        _git("push", "-q", "origin", "--delete", name, check=False)


# ── fluxo principal ───────────────────────────────────────────────────────────

def run(channel: str = "official", only: list[str] | None = None,
        wait_min: int | None = None) -> int:
    """Roda o ciclo completo. Devolve o exit code (1 se precisou de reserva)."""
    from src import main as m

    wait_min = wait_min or int(os.getenv("ROUTINE_WAIT_MIN", "20"))
    types = only or types_for_today()
    if not types:
        print("[routine] Sábado — sem post agendado.")
        return 0

    if _ci():
        _configure_git()

    jobs = []
    for ct in types:
        pid = _post_id(ct, channel)
        if channel == "official" and (POSTS_DIR / f"{pid}.html").exists():
            print(f"[routine] {pid} já foi publicado hoje — pulando (evita post duplicado).")
            continue
        print(f"\n[routine] Coletando: {pid}")
        jobs.append((ct, pid, prepare(ct, pid, channel)))
    if not jobs:
        return 0

    if not _ci():
        print("[routine] (local) input gravado em routine/input/. Sem espera nem publicação.")
        return 0

    _commit_push("routine: input " + ", ".join(pid for _, pid, _ in jobs), ["routine/input"])
    print(f"[routine] input enviado; aguardando a rotina na nuvem (até {wait_min} min).")

    deadline = time.time() + wait_min * 60
    exit_code = 0
    results, consumed = [], set()

    for ct, pid, payload in jobs:
        found = _wait_for_post(pid, max(deadline, time.time() + 30))
        post_text, mode, usage, problems = None, "routine", None, []

        if found:
            ref, raw, usage = found
            post_text, problems = _clean_and_validate(raw, ct, _allowed_links(payload))
            if problems:
                print(f"[routine] texto da rotina rejeitado: {problems}")
                post_text = None
            else:
                consumed.add(ref)
        else:
            problems = [f"a rotina não respondeu em {wait_min} min"]

        if not post_text:
            post_text, mode = _fallback(ct, payload["data"])
            exit_code = 1
            _alert(f"{pid}: brief saiu em modo reserva ({mode}). Motivo: {'; '.join(problems)}.")

        post_text = m.add_quotes(ct, payload["data"], post_text)  # entra também no arquivo
        page_url = m.publish_post(ct, payload["data"], post_text,
                                  _chat_for(ct, channel), mark_seen=(channel == "official"))
        _archive(pid, channel, payload, post_text, page_url, mode, problems)
        results.append({"pid": pid, "type": ct, "mode": mode, "usage": usage})

    # Uso de tokens: uma linha por sessão da rotina (domingo = 2 posts, 1 sessão).
    sessions: dict = {}
    for r in results:
        key = (r["usage"] or {}).get("source_file") or r["pid"]
        s = sessions.setdefault(key, {"ids": [], "types": [], "usage": r["usage"], "mode": r["mode"]})
        s["ids"].append(r["pid"])
        s["types"].append(r["type"])
    for s in sessions.values():
        usage_report.record(usage_report.build_entry(s["ids"], s["types"], channel, s["mode"], s["usage"]))
    usage_report.rebuild()

    for ref in consumed:
        _delete_remote_branch(ref)

    _commit_push("routine: publicado " + ", ".join(r["pid"] for r in results),
                 ["routine/input", "posts", "data", "usage"])
    return exit_code
