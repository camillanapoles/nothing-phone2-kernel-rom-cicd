---
schema: pong-agent-skill/1
name: falsifiable-evidence
description: A claim without a command, a literal output and a timestamp is PENDENTE. Evidence is produced, never narrated.
applies_to: [evidence-auditor, device-qa, security-reviewer, integrity-analyst, product-steward]
---

# Falsifiable evidence

## Regra

Toda afirmação técnica tem **três partes** e as três são obrigatórias:

```
claim:    "su concede root em Slot A"
command:  adb shell su -c id
output:   uid=0(root) gid=0(root) contexts=u:r:su:s0
at:       2026-11-05T18:04:11Z  (sha do pacote: <hex>)
```

Faltando qualquer uma → `PENDENTE (exit 3)`. Nunca `PASS`, nunca "ok pelo contexto".

## Vocabulário fechado

| Estado | Significado | Exit |
|---|---|---|
| `PASS` | comando rodou, saída bate com o critério, no commit atual | 0 |
| `FAIL` | comando rodou e a saída contraria o critério | 1 |
| `PENDENTE` | não rodou, rodou em outro commit, ou faltou insumo | 3 |

Não existe "PASS parcial", "verde com ressalva" ou "passou no app de teste".

## Procedimento

1. Escreva o critério **antes** do comando. Critério escrito depois da saída é racionalização.
2. Cole a saída literal no registro, inclusive a linha de erro. Se é longa, cole início + fim +
   linha do veredito, e diga que truncou.
3. Amarre a evidência ao commit/pacote: `sha256` do artefato e hora.
4. Evidência de outra execução não cobre esta. Reexecutar é mais barato que um bootloop.
5. Quando o insumo não existe (keybox revogada, app não instalado), o item é `PENDENTE`, com motivo
   escrito — nunca `PASS`.

## Anti-padrões

- Screenshot como única prova de comando de terminal.
- "Já testamos isso antes."
- Reescrever a saída para ficar bonita.
- Transformar `FAIL` em `PENDENTE` para não travar o ciclo.
