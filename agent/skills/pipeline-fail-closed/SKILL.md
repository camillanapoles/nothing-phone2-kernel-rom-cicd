---
schema: pong-agent-skill/1
name: pipeline-fail-closed
description: Missing evidence is PENDENTE, not PASS. Every job either proves something or is a bug.
applies_to: [pipeline-engineer, release-orchestrator, release-steward]
---

# Pipeline fail-closed

## Regra

Um job existe para **provar** ou **falhar**. Job que não consegue reprovar é decoração paga por minuto
de runner.

| Situação | Status correto | Status errado |
|---|---|---|
| build passou, device não testado | `PASS` de build, `PENDENTE` de device | "build verde = tudo ok" |
| teste de device pulado por input | `PENDENTE` | `success` |
| etapa opcional falhou e não bloqueia | `PASS` com nota explícita | silêncio |
| evidência manual ausente | `PENDENTE` | `continue-on-error: true` |

## Procedimento

1. Todo passo que prova algo tem saída verificável (exit code, arquivo, hash). Passo "informativo" que
   pode falhar sem consequência deve ser **dito** informativo.
2. Agregue sempre por `if: always()` no job de veredito, lendo `needs.<job>.result` — nunca inferindo
   pelo sucesso do workflow.
3. `mandate` é o único lugar que responde "esta release foi autorizada". Ele tem `false` escrito à mão
   para produção, porque o pipeline é release-only.
4. `continue-on-error` só é aceitável em **download de artefato opcional**, com justificativa no
   próprio passo. Em passo de prova, é proibido.
5. Observabilidade é artefato (`observability.json`), não log perdido: run id, sha, resultados, pendências.

## Anti-padrões

- `if: always()` para "deixar o workflow passar".
- Job que falha e o dependente roda mesmo assim sem ler `.result`.
- Release criada porque `staging` estava `skipped`.
