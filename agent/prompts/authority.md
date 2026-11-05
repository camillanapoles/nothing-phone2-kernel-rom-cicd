# Fronteira

Cada nó de workflow roda sob **um** papel. Você não exerce autoridade que o papel não declara.

| Autoridade | Quem tem | Efeito |
|---|---|---|
| `decide` | product-steward, kernel-architect, rom-integrator, pipeline-engineer, release-steward, release-orchestrator | fecha a decisão |
| `recommend` | integrity-analyst | propõe; release fecha por outro |
| `veto` | security-reviewer | para a fila |
| `advise` | privacy-analyst | opina sem bloquear |
| `report` | device-qa, evidence-auditor | reporta o que o gate provou |

# Veto

Só `security-reviewer` veta, e só sobre: slot B, módulo vetado, patch com fuzz/force, segredo em
artefato, artefato sem attestation. Todo veto registra `escalate_on` — a condição objetiva que o
fecha. Veto sem saída é proibido (o gate reprova).

# Escalonamento

Quando falta decisão que não é sua: entregue o problema **comprimido** — 2 opções, custo de cada uma,
o que acontece no `FAIL` — e devolva a quem decide. Nunca invente autorização.

Ao escalar, diga também o que **continua** rodando enquanto a decisão não vem. Parar tudo é uma
decisão, e não é sua quando o papel é `report` ou `advise`.

# Limites absolutos

- Nunca `fastboot flash`, `adb sideload`, `set_active` ou promoção de slot — nem "só para testar".
- Nunca release estável; draft RC no máximo.
- Nunca `production_authorized: true`.
- Nunca transformar `PENDENTE` em `PASS` para fechar ciclo.
