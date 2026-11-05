# Agent Instructions — Nothing Phone 2 Kernel/ROM CI/CD

> **O contrato normativo é `AGENT.md`.** Este arquivo é o resumo operacional; ele aponta, não decide.
> O gate é `scripts/ao_gate.py` (`make agent`): se este texto divergir do contrato, o gate reprova.

## Regra zero: o modelo é do host

O agente deste repositório roda no host, com o modelo que o host escolher. **Nenhum arquivo pinar
`provider`, `model`, `base_url` ou `api_key`.** Workflows declaram `llm: { provider: host-agent,
model: "" }`. Trocar o modelo não muda veredito, papel, habilidade nem gate — e é por isso que o
processo vale.

## Papéis e autoridade (`agent/roles/`)

| Papel | Autoridade | Assina |
|---|---|---|
| `product-steward` | decide | escopo, não-objetivos, aceitar risco |
| `kernel-architect` | decide | patchset, config, toolchain |
| `rom-integrator` | decide | variante, GApps, manifesto de coleta |
| `security-reviewer` | **veto** | slot B, módulo vetado, patch forçado, segredo |
| `integrity-analyst` | recommend | BASIC/DEVICE/STRONG, keybox |
| `device-qa` | report | matriz M01–M15, evidência do aparelho |
| `pipeline-engineer` | decide | workflow, attestation, release-only |
| `evidence-auditor` | report | ledger de prova, pendências |
| `release-steward` | decide | draft RC, notas, limitações |
| `privacy-analyst` | advise | retenção, telemetria, limites de ocultação |
| `release-orchestrator` | decide | ordem das fases, handoff, gate por fase |

## Habilidades (`agent/skills/`)

`pin-discipline` · `falsifiable-evidence` · `build-contract` · `artifact-integrity` ·
`pipeline-fail-closed` · `phase-gate` · `release-only`

## Processo (`agent/workflows/`)

F0 contratos · build kernel · F1–F3 base/root · F4 ocultação · F5 integridade · F6–F7 apps ·
F8 fechamento. Cada workflow declara `meta.deterministic_gate` — **veredito vem do gate, não do modelo**.

## Padrões de trabalho

- **Fail-closed**: sem evidência é `PENDENTE` (exit 3), nunca `PASS`.
- **Single-slot (Slot A)**; um módulo por reboot; o agente **não grava** no aparelho.
- **Release-only**: nenhum `fastboot flash`/`adb sideload`/`set_active` no pipeline.
- **Pins** vêm de `objects/*.json`; pin ausente = `PENDENTE`, nunca valor plausível.
- **Nunca** editar `objects/*.json` sem atualizar o gate correspondente (`stack_gate.py`,
  `kernel_build_gate.py`, `ao_gate.py`).

## Comandos

```bash
make agent                 # valida o processo do agente (papéis, skills, workflows, prompts)
make agent-phase F5        # plano da fase, em ordem de dependência
make agent-compat          # valida o MESMO contrato no motor agency-orchestrator (ao)
make prove                 # stack + kernel-build + agent + workflow-audit
```
