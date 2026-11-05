---
schema: pong-agent-skill/1
name: pin-discipline
description: Every external artifact is identified by an immutable pin, and the pin lives in one place only. No pin, no step.
applies_to: [kernel-architect, rom-integrator, product-steward, release-orchestrator]
---

# Pin discipline

## Regra

Um artefato externo (commit, tag, imagem de toolchain, módulo, zip de ROM, ação do GitHub) só entra
em qualquer plano se tiver **pin imutável** e **um único lugar canônico** onde está escrito.

| Tipo | Pin válido | Pin inválido |
|---|---|---|
| Fonte git | `commit:<sha40>` | `branch:main`, `tag:v1` sem sha |
| Release/artefato | `tag:<tag>` **+** `sha256:<hex64>` | URL "mais recente" |
| Ação do GitHub | `uses: owner/action@<sha40>` | `@v4`, `@main` |
| Toolchain | arquivo com sha256 publicado | "clang mais novo" |
| Módulo | tag + versão que case com o kernel | "última versão" |

## Procedimento

1. Localize o objeto canônico: `objects/install-stack.json` (camadas), `objects/kernel-build-plan.json`
   (kernel), `objects/rom-artifacts.json` (ROM), `objects/kernel-candidates.json` (candidatos).
2. Se o campo não existe, **não invente**. O item é `PENDENTE (exit 3)` até alguém obter o valor de
   fonte verificável (API do GitHub, `git ls-remote`, hash do arquivo baixado).
3. Se dois objetos divergem no mesmo pin, o `stack_gate.py` reprova (`foreign_pin_kernel`,
   `foreign_pin_rom`). Corrija o objeto, nunca o gate.
4. Toda mudança de pin atualiza, no mesmo PR: objeto + gate/plano + texto humano que cita o pin
   (`README.md`, `INSTALL-SEQUENCE.md`, `CLAUDE.md`).

## Anti-padrões

- `~>`/`^`/`latest` em pin de build.
- sha256 copiado de comentário de terceiro.
- Pin corrigido só no workflow (o objeto continua dizendo outra coisa).
- "Vou fixar o sha depois" — depois não existe para um pipeline fail-closed.
