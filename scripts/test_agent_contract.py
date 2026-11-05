#!/usr/bin/env python3
"""
test_agent_contract.py — prova que o gate do processo REPROVA.

Um gate que só passa não prova nada. Este teste injeta, num diretório temporário, as falhas que
importam e exige exit != 0 em cada uma:

  1. pin de modelo no workflow  → FAIL    (o ponto inteiro do contrato)
  2. papel citado e inexistente → FAIL
  3. nó sem critério falseável  → FAIL
  4. veto sem cláusula de saída → FAIL
  5. fase F0–F8 sem workflow    → FAIL
  6. prompt publicado defasado  → FAIL
  7. workflow válido            → PASS    (senão o teste só mede o quanto o gate reclama)

Roda com: python3 scripts/test_agent_contract.py   (ou: make test-agent)

Não depende de rede, de LLM ou do motor AO — só da stdlib, como o resto dos gates.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "ao_gate.py"

BASE_WORKFLOW = """\
name: "teste"
llm:
  provider: host-agent
  model: ""
inputs:
  - name: goal
    required: true
meta:
  schema: pong-agent-workflow/1
  phase: F0
  owner: product-steward
  deterministic_gate:
    kind: command
    command: "make -s stack"
    expect: "exit 0"
  source_of_truth: [objects/install-stack.json]
steps:
  - id: only_step
    role: product-steward
    skill: [pin-discipline]
    task: "fazer {{goal}}"
    output: findings
    pass_criteria:
      - "tem saída"
"""


def sandbox() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="pong-agent-test-"))
    shutil.copytree(ROOT / "agent", tmp / "agent")
    shutil.copytree(ROOT / "objects", tmp / "objects")
    shutil.copytree(ROOT / "kernel", tmp / "kernel")
    for f in ("AGENT.md", "AGENTS.md", "README.md", "CLAUDE.md"):
        if (ROOT / f).is_file():
            shutil.copy2(ROOT / f, tmp / f)
    (tmp / ".github").mkdir()
    if (ROOT / ".github" / "CODEOWNERS").is_file():
        shutil.copy2(ROOT / ".github" / "CODEOWNERS", tmp / ".github" / "CODEOWNERS")
    if (ROOT / ".claude").is_dir():
        shutil.copytree(ROOT / ".claude", tmp / ".claude")
    (tmp / "scripts").mkdir()
    shutil.copy2(GATE, tmp / "scripts" / "ao_gate.py")
    return tmp


def run_gate(path: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(path / "scripts" / "ao_gate.py"), "--json"],
        cwd=path, capture_output=True, text=True, timeout=180,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"raw": proc.stdout[-800:], "stderr": proc.stderr[-800:]}
    return proc.returncode, data


def failed_checks(data: dict) -> dict:
    return {c["check"]: c for c in data.get("checks", []) if c["status"] in ("FAIL", "PENDENTE")}


def case(name, mutate, expect_fail_check):
    tmp = sandbox()
    try:
        mutate(tmp)
        code, data = run_gate(tmp)
        bad = failed_checks(data)
        if expect_fail_check is None:
            ok = code == 0
            detail = "exit 0" if ok else f"exit {code}; falhas: {sorted(bad)}"
        else:
            ok = code != 0 and expect_fail_check in bad
            detail = (
                f"exit {code}, {expect_fail_check}={'FAIL' if expect_fail_check in bad else 'não reprovado'}"
            )
        print(f"{'[PASS]' if ok else '[FAIL]'} {name}: {detail}")
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_workflow(path: Path, text: str):
    (path / "agent" / "workflows" / "only.yaml").write_text(text, encoding="utf-8")


def m_model_pin(p: Path):
    write_workflow(p, BASE_WORKFLOW.replace('model: ""', 'model: "claude-sonnet-4-5"'))


def m_cli_provider(p: Path):
    write_workflow(p, BASE_WORKFLOW.replace("provider: host-agent", "provider: deepseek"))


def m_alias(p: Path):
    readme = p / "README.md"
    readme.write_text(readme.read_text() + "\n- `@mechanical-coder` mantém\n", encoding="utf-8")


def m_no_criteria(p: Path):
    text = BASE_WORKFLOW.replace(
        '    pass_criteria:\n      - "tem saída"\n', ""
    )
    write_workflow(p, text)


def m_veto_no_exit(p: Path):
    text = BASE_WORKFLOW.replace(
        '    output: findings',
        '    output: findings\n    veto:\n      on: "algo"\n',
    )
    write_workflow(p, text)


def m_phase_gap(p: Path):
    for f in (p / "agent" / "workflows").glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        if "phases: [F1, F2, F3]" in text:
            f.write_text(text.replace("phases: [F1, F2, F3]", "phases: [F1, F2]"), encoding="utf-8")


def m_stale_prompt(p: Path):
    target = p / ".claude" / "agents" / "pong-orchestrator.md"
    if target.is_file():
        target.write_text(target.read_text(encoding="utf-8").replace("Identidade", "Identidade (velha)"),
                          encoding="utf-8")
    (p / "agent" / "prompts" / "method.md").write_text(
        (p / "agent" / "prompts" / "method.md").read_text(encoding="utf-8") + "\n\nmudança\n",
        encoding="utf-8",
    )


def m_valid(p: Path):
    # base já é o caso válido: só remove os workflows reais para não duplicar fase
    for f in (p / "agent" / "workflows").glob("*.yaml"):
        f.unlink()
    write_workflow(p, BASE_WORKFLOW)
    # F1–F8 passam a faltar; então este caso espera FAIL de cobertura, não PASS global.
    # A validade do YAML é medida pelo check workflows.contract (que deve PASSAR).
    return None


def main() -> int:
    print("Teste de mutação do contrato do agente\n")
    results = [
        case("pin de modelo no YAML", m_model_pin, "identity.no_model_pin"),
        case("provider de LLM no YAML", m_cli_provider, "identity.no_model_pin"),
        case("papel inexistente citado", m_alias, "roles.aliases"),
        case("nó sem pass_criteria", m_no_criteria, "workflows.contract"),
        case("veto sem escalate_on", m_veto_no_exit, "workflows.contract"),
        case("fase sem workflow", m_phase_gap, "workflows.coverage"),
        case("prompt publicado defasado", m_stale_prompt, "prompts.published"),
    ]

    # caso positivo: o workflow base, sozinho, tem de passar no contrato estrutural
    tmp = sandbox()
    try:
        for f in (tmp / "agent" / "workflows").glob("*.yaml"):
            f.unlink()
        write_workflow(tmp, BASE_WORKFLOW)
        _code, data = run_gate(tmp)
        struct = {c["check"]: c["status"] for c in data.get("checks", [])}.get("workflows.contract")
        ok = struct == "PASS"
        print(f"{'[PASS]' if ok else '[FAIL]'} workflow válido isolado: workflows.contract={struct}")
        results.append(ok)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if all(results):
        print(f"[SUMMARY] PASS — {len(results)}/{len(results)} mutações reprovadas e o caso válido aprovado")
        return 0
    print(f"[SUMMARY] FAIL — {sum(results)}/{len(results)} casos com o resultado esperado")
    return 1


if __name__ == "__main__":
    sys.exit(main())
