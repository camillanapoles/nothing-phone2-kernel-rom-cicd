---
schema: pong-agent-skill/1
name: phase-gate
description: A phase opens only when the previous one closed with no required item PENDENTE. Order comes from the document, not from enthusiasm.
applies_to: [release-orchestrator, product-steward, device-qa]
---

# Phase gate

## Regra

Fase F0–F8 vem de `INSTALL-SEQUENCE.md`. A ordem é do documento. Dentro da fase, `depends_on` manda.
Nada mais.

```
F0 contratos ─→ F1 base (Slot A) ─→ F2 saneamento ─→ F3 root
    └→ F4 ocultação ─→ F5 integridade ─→ F6 apps ─→ F7 performance ─→ F8 fechamento
```

## Procedimento

1. Abra a fase com `make agent-phase F<n>`: sai o plano em ordem de dependência, com papel,
   habilidade, critério e gate por nó.
2. **Handoff fechado**: o nó declara o que entrega (`declares`) e com que evidência. Campo declarado
   que o anterior não entregou → `pending` → fase bloqueada.
3. Um módulo por reboot. Sempre. Agrupar módulos esconde qual quebrou e transforma um bootloop em
   diagnóstico de três horas.
4. Feche a fase com: todos os `required` em `PASS`, `optional`/`conditional` declarados, e o
   `deterministic_gate` da fase exit 0.
5. Fase fechada não reabre por conveniência: nova medição = nova entrada no ledger.

## Anti-padrões

- Rodar F5 antes de F4 "porque o reboot está quente".
- Fechar fase com `PENDENTE` e anotar no rodapé.
- Plano de fase sem `PASS` esperado por item.
