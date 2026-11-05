#!/usr/bin/env python3
"""
workflow_audit.py — a fronteira do pipeline, provada fora do YAML.

O `pong-cicd.yml` já audita a si mesmo num passo inline. Este script faz a mesma prova a partir do
repositório, para que `make prove` e um humano no terminal cheguem ao mesmo veredito sem copiar
heredoc. Ele NÃO substitui o passo do CI (o CI é a autoridade sobre o próprio workflow) — ele dá
o mesmo resultado localmente.

Checa:
  1. exatamente um workflow, e ele é o esperado;
  2. toda ação de terceiro em sha40 (sem @vN, @main);
  3. nenhuma operação de deploy no texto executável (fastboot flash / adb sideload / set_active);
  4. o `mandate` existe e escreve production_authorized/production_deployed = False;
  5. os pins do ambiente batem com objects/kernel-build-plan.json.

Exit: 0=PASS, 1=FAIL, 3=PENDENTE (workflow ausente)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / ".github" / "workflows"
EXPECTED = "pong-cicd.yml"

# Só linhas YAML de verdade: `- name: ...` seguido de `uses:` na linha seguinte.
# O workflow contém um heredoc python com a string 'uses:' — casar isso gerava falso positivo.
PIN_RE = re.compile(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)")
SHA40_RE = re.compile(r"@[0-9a-f]{40}$")
# Texto executável = linhas que não são comentário puro.
DEPLOY_RES = [
    (re.compile(r"fastboot\s+flash"), "fastboot flash"),
    (re.compile(r"fastboot\s+--set-active"), "fastboot --set-active"),
    (re.compile(r"fastboot\s+set_active"), "fastboot set_active"),
    (re.compile(r"adb\s+[^\n]*sideload"), "adb sideload"),
    (re.compile(r"adb\s+[^\n]*reboot\s+(bootloader|recovery)"), "adb reboot para modo de gravação"),
]


def main() -> int:
    if not WF_DIR.is_dir():
        print("[PENDENTE] .github/workflows ausente")
        return 3
    workflows = sorted(list(WF_DIR.glob("*.yml")) + list(WF_DIR.glob("*.yaml")))
    if not workflows:
        print("[PENDENTE] nenhum workflow encontrado")
        return 3

    failures: list[str] = []
    if [w.name for w in workflows] != [EXPECTED]:
        failures.append(f"workflows inesperados: {[w.name for w in workflows]} (esperado: ['{EXPECTED}'])")

    target = WF_DIR / EXPECTED
    if not target.is_file():
        print(f"[PENDENTE] {EXPECTED} não existe")
        return 3

    text = target.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    pins = PIN_RE.findall(text)
    if not pins:
        failures.append("nenhuma ação referenciada — auditor não tem o que provar")
    bad = [p for p in pins if not SHA40_RE.search(p)]
    if bad:
        failures.append(f"ações sem sha40: {bad}")

    for pattern, label in DEPLOY_RES:
        m = pattern.search(executable)
        if m:
            failures.append(f"operação de deploy no texto executável: {label} ({m.group(0)!r})")

    if "production_authorized" not in text or "production_deployed" not in text:
        failures.append("mandate sem production_authorized/production_deployed")
    elif not re.search(r"'production_authorized':\s*False", text) or not re.search(
        r"'production_deployed':\s*False", text
    ):
        failures.append("mandate não fixa produção em False")

    plan_p = ROOT / "objects" / "kernel-build-plan.json"
    if plan_p.is_file():
        pin = json.loads(plan_p.read_text(encoding="utf-8")).get("source", {}).get("pin", "")
        env_match = re.search(r"KERNEL_COMMIT:\s*([0-9a-f]{40})", text)
        if not env_match:
            failures.append("KERNEL_COMMIT ausente do workflow")
        elif pin and env_match.group(1) != pin:
            failures.append(f"KERNEL_COMMIT do workflow != pin do objeto ({env_match.group(1)[:12]} != {pin[:12]})")
    else:
        failures.append("objects/kernel-build-plan.json ausente")

    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print(f"\n[SUMMARY] FAIL — {len(failures)} problema(s) na fronteira do pipeline")
        return 1

    print(f"[PASS] um workflow ({EXPECTED})")
    print(f"[PASS] {len(pins)} referências de ação, todas em sha40")
    print("[PASS] nenhuma operação de deploy no texto executável")
    print("[PASS] mandate fixa production_authorized/production_deployed = False")
    print("[PASS] KERNEL_COMMIT == pin do kernel-build-plan.json")
    print("\n[SUMMARY] PASS — pipeline release-only, fail-closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
