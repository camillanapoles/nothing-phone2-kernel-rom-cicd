# `agent/` — o processo, declarado

Este diretório é a forma executável de `AGENT.md`. Nada aqui é prompt de modelo; tudo aqui é
**contrato que pode ser reprovado por um script**.

```
agent/
├── roles/       11 papéis, com autoridade declarada (decide/recommend/veto/advise/report)
├── skills/       5 habilidades reutilizáveis — o "como", separado do "quem"
├── workflows/    6 workflows YAML, um por bloco de fase, sem pin de modelo
└── prompts/      o prompt montável do agente, em partes + índice de composição
```

## O que roda onde

| Camada | Arquivo | Quem executa | O que prova |
|---|---|---|---|
| Identidade | `AGENT.md` | host | que o modelo é substituível |
| Papel | `agent/roles/*.md` | host / Claude Code / AO | quem decide o quê |
| Habilidade | `agent/skills/*/SKILL.md` | host / AO (`skill:`) | como se faz, sempre igual |
| Processo | `agent/workflows/*.yaml` | host / AO / CI | ordem, dependências e critérios |
| Prompt | `agent/prompts/*.md` | host / `.claude/agents/` | como o agente se apresenta |
| Prova | `scripts/ao_gate.py` | CI + host | que tudo acima é verdade |

## Regra que vale mais que as outras

**Veredito não vem de modelo.** Cada workflow declara `meta.deterministic_gate` — o comando ou job
que realmente prova a fase. Se o gate não rodou, a fase está `PENDENTE`, não `PASS`.

```bash
make agent                  # valida o processo inteiro (exit 0/1/3)
make agent-phase F5         # imprime o plano da fase, em ordem de dependência
make agent-compose PROMPT=system-prompt   # monta o prompt do agente
python3 scripts/ao_gate.py --project ao --base-url http://127.0.0.1:8000/v1  # forma compatível com AO
python3 scripts/ao_gate.py --require-compat --ao-cmd ao   # valida com o motor real, se instalado
```

## Como adicionar um passo

1. Escolha o papel em `agent/roles/` — se nenhum serve, crie o papel **com autoridade explícita**.
2. Escolha a habilidade em `agent/skills/` — se o método é novo, ele vira skill, não texto solto.
3. Abra o nó no workflow da fase: `task` (o que fazer), `pass_criteria` (como se reprova),
   `artifacts` (o que sai) e `depends_on` (de quem depende).
4. Rode `make agent`. Se o nó não declara critério falseável, ele não entra.

Nunca escreva `provider:` diferente de `host-agent`, nem `model:`, `base_url` ou `api_key`.
O gate reprova — e esse é o ponto inteiro deste diretório.
