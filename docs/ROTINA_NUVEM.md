# Rotina na nuvem — como o brief é escrito e publicado

**Por que existe.** O Gemini ficou sem créditos (erro 402 "prepayment credits are depleted") e, desde pelo menos 01/10/2026, o brief vinha saindo no template de emergência sem ninguém perceber. Agora quem escreve o texto é o Claude, numa rotina na nuvem, usando a assinatura Claude do mantenedor em vez de uma API paga.

## Fluxo

```
cron-job.org (9h, seg–sex + dom)
        │  workflow_dispatch type=auto
        ▼
┌─ GitHub Actions ─────────────────────────────┐        ┌─ Rotina na nuvem (Claude) ───────────┐
│ 1. coleta notícias, preços, Termômetro,      │        │                                      │
│    Manchete do dia  (src/sources, signals)   │        │                                      │
│ 2. grava routine/input/<id>.json → master ───┼───────▶│ 3. lê o input + prompts/system_prompt│
│                                              │        │    + routine/PROMPT.md               │
│                                              │        │ 4. escreve routine/out/<id>.html     │
│                                              │        │ 5. mede os próprios tokens           │
│ 6. espera o arquivo aparecer ◀───────────────┼────────┤ 6. push numa branch claude/*         │
│ 7. valida (tamanho, tags, links permitidos)  │        └──────────────────────────────────────┘
│ 8. Telegra.ph + Telegram (canal certo)       │
│ 9. arquiva em posts/, registra consumo em    │
│    usage/, apaga a branch claude/* consumida │
└──────────────────────────────────────────────┘
```

Por que a divisão: o ambiente da rotina só alcança GitHub e PyPI. Um proxy de saída bloqueia RSS, Yahoo, ForexFactory, Finnhub, **Telegram e Telegra.ph** (testado em 07/10/2026). Por isso a coleta e o envio ficam no Actions, que tem rede aberta e os segredos. O token do bot nunca vai para a nuvem do Claude.

## Quem faz o quê

| Arquivo | Papel |
|---|---|
| `src/routine.py` | orquestração do ciclo (roda no Actions) |
| `src/quotes.py` | bloco `💹 COTAÇÕES DO DIA` do brief diário (Ibovespa, Bitcoin, Dólar, Selic + variação), inserido por código depois da Opinião e antes dos avisos finais. O resumo semanal não leva |
| `routine/PROMPT.md` | **instruções do Claude** — fonte única das regras de redação. Ajustar o texto do brief = editar este arquivo e dar push |
| `prompts/system_prompt.md` | tom de voz, estrutura e formato dos posts |
| `routine/measure_usage.py` | a rotina mede os próprios tokens |
| `routine/input/` | entradas pendentes (o Actions grava, a rotina lê) |
| `routine/out/` | saída da rotina (só existe nas branches `claude/*`) |
| `posts/` | arquivo dos posts publicados + o input de cada um (`posts/test/` = testes) |
| `usage/USAGE.md` | consumo de tokens, atualizado a cada publicação |
| `data/seen_news.json` | memória anti-repetição de notícias |

## A rotina cadastrada

- **Nome:** "DS Trade Brief — redator diário" (em *Rotinas* no claude.ai)
- **Id:** `<trigger_id>` (descubra com a ferramenta de rotinas, ação `list`)
- **Agenda:** `2 12 * * 0-5` (UTC) = 09:02 em Brasília, domingo a sexta. Sábado não roda.
- **Modelo:** Claude Sonnet 5.5 · **Ferramentas:** só Bash, Read, Write, Edit, Glob, Grep (sem web)
- O prompt da rotina é só um "leia `routine/PROMPT.md`". Mudou a regra? Edite o arquivo, não a rotina.

## Se algo falhar

O post **nunca deixa de sair**. Se a rotina não responder em 20 minutos, ou entregar um texto inválido, o Actions:
1. tenta o **Gemini** (cadeia de modelos); 2. se também falhar, usa o **template**; 3. avisa no grupo de testes; 4. marca a execução como **falha**, e o GitHub manda e-mail.

Um e-mail de falha do Actions, ou um aviso "modo reserva" no grupo de testes, significa que **aquele dia saiu fora do padrão**. O motivo está no log da execução.

Contra post duplicado: o ciclo oficial pula se `posts/<data>_<tipo>.html` já existe, e o workflow tem trava de concorrência.

**Bloco de cotações:** o `💹 COTAÇÕES DO DIA` é inserido por código em **todos** os caminhos (texto da rotina, Gemini e template), logo antes dos avisos finais, só no brief diário. Fontes: Yahoo Finance (Ibovespa, Bitcoin, Dólar) e Selic em três degraus (Banco Central → BrasilAPI → valor guardado em `data/selic.json`). O Banco Central estoura o tempo dentro do GitHub, por isso a reserva. Se nenhuma fonte da Selic responder, a linha é omitida, nunca inventada.

O que não vive no Git (cadastro da rotina, agendamento no cron-job.org, nomes dos segredos) fica na documentação operacional privada do projeto.

## Segurança

O texto de sites de terceiros (manchetes, resumos) entra no contexto da rotina, então há várias camadas:
1. **Higienização do input**: sem HTML nem caracteres de controle, resumo ≤ 300 caracteres.
2. **Prompt**: manchetes e resumos são dado, nunca instrução; só mexe em `routine/out/`.
3. **Ferramentas**: sem web; ferramentas de conectores (Gmail, Drive etc.) bloqueadas por `disallowed_tools`. No teste de 07/10 a ferramenta de conector pedida não foi encontrada na sessão (os conectores aparecem só como "ainda conectando").
4. **Validação no código**: o post é rejeitado se tiver link, `@` ou tag `<a>` que não seja dos canais da DS Trade, ou se vier com tamanho/tags inválidos. Cai no fallback.
5. Nenhum segredo na nuvem do Claude.

> Observação: a API de rotinas anexa **todos os conectores da conta** a qualquer rotina nova, sem opção de remover pela API. Se quiser eliminar isso de vez, abra a rotina em *Rotinas* e remova os conectores pela interface.

## Operação

```bash
# Teste do diário: só o grupo de testes, não marca notícias como vistas
gh workflow run daily_brief.yml -f type=routine_test_daily
# Teste do domingo (os 2 posts)
gh workflow run daily_brief.yml -f type=routine_test_weekly
# Checar só as fontes de cotação (Yahoo + Selic); não envia nada
gh workflow run daily_brief.yml -f type=check_quotes
```
Depois do `workflow run`, dispare a rotina em *Rotinas → Executar agora* (em produção a agenda faz isso sozinha).

**Rollback para o Gemini:** o `type=legacy_auto` roda o caminho antigo. Para o cron-job.org usar o antigo, troque o `type` do corpo da chamada para `legacy_auto`. Para desligar a rotina, desative-a em *Rotinas*.

## Consumo de tokens

Cada sessão da rotina mede os próprios tokens (`routine/measure_usage.py`) e o Actions acumula o resultado em `usage/USAGE.md`. Ordem de grandeza medida: ~37–70 mil tokens novos e ~180–210 mil de cache lido por brief.

## Limitações conhecidas

- O resumo semanal reaproveita a mesma coleta do diário (top notícias de 8 dias). Falta um recap de verdade, com variação semanal dos preços.
- A medição de tokens perde as últimas ~2 mensagens da sessão (commit/push e resposta final).
- `WHATSAPP_INVITE_LINK` ainda vazio: o convite do semanal mostra "(em breve)".
- O horário real do post é ~9h05 (a rotina sai ~1–3 min depois do minuto agendado).
