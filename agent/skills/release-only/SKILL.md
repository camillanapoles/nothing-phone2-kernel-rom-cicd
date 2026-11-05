---
schema: pong-agent-skill/1
name: release-only
description: The pipeline never touches the device. It produces a proveable artifact; a human writes it. This is a design constraint, not a missing feature.
applies_to: [release-steward, pipeline-engineer, security-reviewer, privacy-analyst]
---

# Release-only

## Regra

Este repositório **não executa** `fastboot flash`, `adb sideload`, `fastboot set_active` nem promoção
de slot — em workflow, em script de CI, em job noturno. O CI produz artefato provado; a gravação é ato
humano no aparelho físico.

Por quê: o aparelho é single-slot, único, e um bootloop custa a tarde de quem opera. Automatizar a
gravação é trocar risco de software por risco de hardware sem ganho de velocidade real.

## Procedimento

1. Todo comando de gravação é **texto para humano**, nunca passo de pipeline. Ele aparece em
   `INSTALL-SEQUENCE.md` e no plano de fase (`.install-plan.md`), com `PASS` esperado.
2. O agente emite: comando, critério, o que fazer no `FAIL`, e o item do ledger que fecha.
3. `production_authorized` e `production_deployed` são `false` no `mandate.json`. Não é placeholder:
   é a prova de que o pipeline parou onde devia.
4. Draft RC é o ponto máximo de automação. Estável é humano, com evidência na mão.
5. Qualquer PR que adicione operação de deploy no workflow é reprovado no `stack-governance` — o
   auditor procura os padrões no texto executável (não em comentário).

## Anti-padrões

- "Só um flash automático no runner self-hosted."
- Job de deploy atrás de `if: github.ref == 'main'` (continua existindo).
- Chamar de "staging" um passo que escreve no aparelho.
