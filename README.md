# DS Trade Brief

Pipeline automatizado que publica um **brief diário de mercado** (Forex, Cripto e B3) em canais de Telegram, em produção desde jun/2026.

> **EN —** Automated market-briefing pipeline in Python. GitHub Actions collects news, prices and the economic calendar; an LLM (Claude, via a scheduled cloud routine) writes the post; the pipeline validates it, inserts deterministic quote data and publishes to Telegram. Multi-level fallbacks guarantee exactly one post per day.

## O que faz

Todo dia útil às 9h (Brasília) publica um brief com:

- **Manchete do dia** e uma leitura curta de cada mercado (Forex, Cripto, B3);
- **Termômetro do Mercado**: 4 níveis de agitação por seção, calculados a partir da variação real de preço e da relevância das notícias;
- **Opinião do dia** baseada nos preços do fechamento anterior (sem recomendação de compra ou venda);
- **Cotações do dia** (Ibovespa, Bitcoin, Dólar, Selic) com a variação sobre o fechamento anterior.

Aos domingos publica o resumo da semana. Cada edição também vira uma página pública no Telegra.ph.

## Arquitetura

```
 cron-job.org (9h) ──▶ GitHub Actions ──────────────────────────────────────────┐
                        1. coleta notícias, preços, calendário                    │
                        2. ranqueia (motor de relevância) e calcula os sinais     │
                        3. grava routine/input/<id>.json                          │
                                    │                                             │
                                    ▼                                             │
                        Rotina na nuvem (Claude): lê o input + prompts,           │
                        escreve routine/out/<id>.html, push em branch claude/*    │
                                    │                                             │
                                    ▼                                             │
                        4. valida o texto (tamanho, tags, links permitidos)  ◀────┘
                        5. insere o bloco de cotações (código, não IA)
                        6. publica: Telegra.ph + Telegram · arquiva · mede consumo
```

Se a rotina não responder em 20 min ou entregar texto inválido, o ciclo cai num **modelo reserva (Gemini, cadeia de modelos)** e, por último, num **template determinístico**, avisa em um grupo de testes e marca a execução como falha. O post sai de qualquer forma.

Por que a coleta e o envio ficam no Actions: o ambiente da rotina na nuvem só alcança GitHub e PyPI (proxy de saída), então tudo que precisa de rede e de segredos roda no CI. O token do bot nunca chega ao ambiente do LLM.

Detalhes: [`docs/ROTINA_NUVEM.md`](docs/ROTINA_NUVEM.md).

## Stack

Python 3.12 · GitHub Actions · Claude (Anthropic) e Gemini (Google) · Telegram Bot API · Telegra.ph API · `requests`, `feedparser`, `python-dotenv`, `google-genai`. Fontes: RSS de portais brasileiros, Finnhub, ForexFactory, Yahoo Finance, Banco Central (SGS) e BrasilAPI. Dados, CI e hospedagem usam só tier gratuito; a redação usa a assinatura Claude do mantenedor (o Gemini é apenas reserva).

## Decisões de engenharia

- **Números fora do LLM.** O bloco de cotações é montado em código a partir das fontes e inserido no texto final. O modelo escreve a análise; nunca o valor. Em teste, 16 de 16 números citados no texto estavam nos dados de entrada.
- **Degradação em camadas.** Rotina → Gemini (3 modelos em cadeia) → template. A Selic tem 3 fontes (Banco Central → BrasilAPI → último valor guardado); se nenhuma responder, a linha é omitida, nunca inventada.
- **Idempotência.** O ciclo pula se o post do dia já existe, e o workflow tem trava de concorrência. Já houve post duplicado (dois agendadores) e foi eliminado na origem.
- **Motor de relevância.** Pontuação em camadas por título e resumo (macro e banco central, movimentos fortes, dado concreto, recência, penalidade para conteúdo promocional), bilíngue PT/EN, com memória das notícias já publicadas para não repetir.
- **Defesa contra injeção de prompt.** Manchetes de terceiros entram no contexto do LLM, então o input é higienizado, o prompt as trata como dado, as ferramentas da rotina são restritas e o validador rejeita qualquer link, `@` ou tag `<a>` fora da lista permitida.
- **Custo medido, não estimado.** A rotina lê o próprio transcript e registra os tokens de cada execução (`usage/`).

## Como rodar

Requisitos: Python 3.12+.

```bash
pip install -r requirements.txt
cp .env.example .env        # preencha apenas o que for usar

# 1) Coleta e ranqueamento, sem nenhuma chave e sem enviar nada:
python -m src.sources.news_b3
python -m src.main --routine-prepare daily_brief   # grava routine/input/*.json (de teste)

# 2) Checar as fontes de cotação (Yahoo + Selic), também sem chave:
python -m src.main --check-quotes

# 3) Gerar um brief completo sem enviar (precisa de GEMINI_API_KEY):
python -m src.main --type daily_brief --dry-run
```

O ciclo completo (com a rotina na nuvem e a publicação) roda no GitHub Actions. Veja `.github/workflows/daily_brief.yml` e a seção de operação em `docs/ROTINA_NUVEM.md`.

### Variáveis de ambiente

Veja [`.env.example`](.env.example). No CI, os mesmos nomes vêm dos Secrets do repositório.

## Estrutura

```
.github/workflows/daily_brief.yml   ciclo completo (workflow_dispatch)
prompts/system_prompt.md            tom de voz e formato dos posts
routine/PROMPT.md                   instruções do LLM na nuvem
routine/measure_usage.py            medição de tokens da sessão
src/main.py                         CLI e publicação
src/routine.py                      orquestração do ciclo com a rotina na nuvem
src/generator.py                    caminho de reserva (Gemini, cadeia de modelos)
src/quotes.py                       bloco de cotações e Selic em 3 fontes
src/signals.py                      Termômetro do Mercado e Manchete do dia
src/sources/                        notícias (forex, cripto, B3), calendário, preços, relevância
src/telegram_sender.py              envio com escape de HTML e fallback para texto puro
src/telegraph_publisher.py          páginas web dos briefs
```

## Limitações conhecidas

- Não há suíte de testes automatizados; a validação foi feita por ciclos de teste em um grupo separado e por scripts de conferência.
- O resumo semanal reaproveita a coleta do diário; falta um recap com a variação semanal dos preços.
- O conteúdo é informativo. Não é recomendação de investimento.
