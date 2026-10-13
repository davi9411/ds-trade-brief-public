"""
Gerador de posts com auto-revisão via Google Gemini.

Fluxo:
  1. generate_post() → gera o texto com base nos dados e tipo
  2. _review_post()  → segundo call verifica qualidade e conformidade
  3. Se reprovado, regenera uma vez → posta de qualquer forma
"""

import json
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from src import config

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.md"


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _client() -> genai.Client:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não configurada.")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _model_chain() -> list[str]:
    """Cadeia de modelos: se o principal estiver sobrecarregado (503) ou sem
    cota, tenta o próximo. Verificado em produção: quando 'gemini-2.5-flash-lite'
    cai em 503, 'gemini-flash-lite-latest' e 'gemini-2.5-flash' seguem de pé.
    """
    chain = [config.GEMINI_MODEL, "gemini-flash-lite-latest", "gemini-2.5-flash"]
    seen, out = set(), []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _call_gemini(client: genai.Client, system: str, user: str, max_tokens: int = 700) -> str:
    """Gera conteúdo tentando a cadeia de modelos, com 1 retry curto por modelo
    em caso de 503. Pula imediatamente modelo com cota esgotada."""
    models = _model_chain()
    last_exc = None

    for i, model in enumerate(models):
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                    ),
                )
                text = (response.text or "").strip()
                if text:
                    if i > 0:
                        print(f"[generator] modelo reserva usado: {model}")
                    return text
                break  # resposta vazia → tenta próximo modelo
            except (genai_errors.ServerError, genai_errors.ClientError) as e:
                last_exc = e
                msg = str(e)
                exhausted = "PerDay" in msg or "limit: 0" in msg or "RESOURCE_EXHAUSTED" in msg
                overloaded = "UNAVAILABLE" in msg or "503" in msg or "overloaded" in msg
                if exhausted:
                    print(f"[generator] {model}: cota esgotada → próximo modelo")
                    break
                if overloaded and attempt == 0:
                    print(f"[generator] {model}: sobrecarregado (503), retry em 20s...")
                    time.sleep(20)
                    continue
                print(f"[generator] {model}: falhou ({msg[:50]}) → próximo modelo")
                break

    raise last_exc if last_exc else RuntimeError("Gemini indisponível em todos os modelos")


# ── Instruções por tipo de conteúdo ──────────────────────────────────────────

TYPE_INSTRUCTIONS = {
    "daily_brief": (
        "Gere o BRIEF DIÁRIO completo seguindo o TIPO 1 do system prompt.\n"
        "Os dados JSON abaixo contêm:\n"
        "- 'forex', 'crypto', 'b3': notícias JÁ RANQUEADAS por relevância "
        "(a primeira de cada lista é a mais importante — apresente nessa ordem).\n"
        "- 'prices': preços do fechamento anterior — use na seção Opinião do Dia. Não invente preços.\n"
        "- 'heat': a linha do Termômetro de cada seção, PRONTA. Copie exatamente.\n"
        "- 'headline_of_day': a notícia mais relevante do dia — vira a linha '🗞️ HOJE:'.\n"
        "- 'calendar' (só segunda): calendário econômico da semana."
    ),
    "weekly_brief": (
        "Gere o RESUMO SEMANAL — versão SEM convite — seguindo o TIPO 2 do system prompt.\n"
        "Os dados abaixo contêm notícias da semana de Forex, Cripto e B3.\n"
        "NÃO inclua o bloco de convite (📲 ACOMPANHE OS BRIEFS DIÁRIOS)."
    ),
    "weekly_main": (
        "Gere o RESUMO SEMANAL — versão COM convite — seguindo o TIPO 2 do system prompt.\n"
        "Os dados abaixo contêm notícias da semana de Forex, Cripto e B3.\n"
        "INCLUA o bloco de convite ao final com os links fornecidos em 'invite_links'."
    ),
}

REVIEW_SYSTEM = (
    "Você é um revisor de conteúdo para canais de trading no Telegram. "
    "Responda APENAS com 'APROVADO' ou 'REESCREVER: [motivo em até 20 palavras]'."
)

REVIEW_CRITERIA = """Revise o post abaixo e aprove se TODOS os critérios forem atendidos:
✓ Formatação HTML válida (<b>, <i>) — sem markdown (**) ou # headers
✓ Seções separadas por ━━━ quando o tipo exige
✓ Nenhuma recomendação de compra/venda, stop ou alvo de preço explícito ("compre", "venda", "entrada em X")
✓ Disclaimer de conteúdo educacional presente
✓ Seção Opinião (se presente) tem seu próprio disclaimer de não-sinal
✓ Linguagem em português do Brasil, natural
✓ Não inventa dados que não foram fornecidos
✓ Cada seção (FOREX, CRIPTO, B3) fala sobre movimentos de mercado, preços, dados econômicos
  ou eventos regulatórios — OU declara "Sem notícias relevantes de [X] hoje."
  NÃO APROVE se uma seção discutir patrocínios, parcerias de marketing, esports, premiações
  ou conteúdo corporativo sem relação direta com o mercado financeiro.

IMPORTANTE: Mencionar preços reais e variações % na seção Opinião é CORRETO e esperado —
o que NÃO pode é dar preço-alvo, stop loss, entrada ou saída explícita.
Se o disclaimer de não-sinal está presente após a Opinião, APROVE.

Post:
{post}

Responda APENAS: APROVADO  ou  REESCREVER: [motivo]"""


def _review_post(client: genai.Client, post: str) -> bool:
    """Retorna True se aprovado, False se precisa reescrever."""
    try:
        result = _call_gemini(
            client,
            system=REVIEW_SYSTEM,
            user=REVIEW_CRITERIA.format(post=post),
            max_tokens=80,
        )
        approved = result.upper().startswith("APROVADO")
        if not approved:
            print(f"[generator] Revisão: {result[:120]}")
        return approved
    except Exception as e:
        print(f"[generator] Revisão falhou ({e}), aprovando assim mesmo.")
        return True


def generate_post(content_type: str, data) -> str:
    """Gera e auto-revisa o post. Regenera uma vez se reprovado."""
    if content_type not in TYPE_INSTRUCTIONS:
        raise ValueError(f"content_type inválido: {content_type}")

    client = _client()
    system_prompt = _load_system_prompt()

    user_message = (
        f"{TYPE_INSTRUCTIONS[content_type]}\n\n"
        f"DADOS (JSON):\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
        "Responda APENAS com o texto final do post (sem comentários, sem aspas)."
    )

    post = _call_gemini(client, system_prompt, user_message)

    if not _review_post(client, post):
        print("[generator] Regenerando post após revisão...")
        try:
            post = _call_gemini(client, system_prompt, user_message)
        except Exception as e:
            print(f"[generator] Regeneração falhou ({e}), postando versão original.")

    return post
