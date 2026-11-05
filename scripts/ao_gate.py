#!/usr/bin/env python3
"""
ao_gate.py — o gate do PROCESSO do agente (não do modelo).

Prova que o agente deste repositório é processo, não modelo:
  * todo workflow declara `llm.provider: host-agent` e NÃO pina model/base_url/api_key;
  * todo nó tem papel existente, tarefa, critério falseável e (fase física) handoff;
  * todo papel tem autoridade declarada; `veto` exige `escalate_on`;
  * toda skill referenciada existe e tem frontmatter válido;
  * o prompt montado não contém pin de modelo;
  * o fingerprint do processo é emitido (é isso que entra no CI/release — não há fingerprint de modelo).

Uso:
  python3 scripts/ao_gate.py                      # valida o projeto (exit 0/1/3)
  python3 scripts/ao_gate.py --json               # saída legível por máquina
  python3 scripts/ao_gate.py --phase F5           # plano da fase, em ordem de dependência
  python3 scripts/ao_gate.py --compose system-prompt
  python3 scripts/ao_gate.py --project ao --base-url http://127.0.0.1:8000/v1
  python3 scripts/ao_gate.py --require-compat --ao-cmd ao

Exit codes (mesmo vocabulário do repo): 0=PASS, 1=FAIL, 3=PENDENTE (insumo ausente)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"

EXIT_PASS, EXIT_FAIL, EXIT_PENDING = 0, 1, 3

AUTHORITIES = {"decide", "recommend", "veto", "advise", "report"}
PHASES = ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]
HOST_PROVIDER = "host-agent"
# Ao projetar para o motor AO, o provider é um cliente HTTP qualquer apontando para o host;
# o nome do modelo é irrelevante por contrato (ver AGENT.md §1).
AO_PROVIDER = "anthropic-compatible"
MODEL_PIN_KEYS = ("model", "base_url", "api_key", "api-key", "endpoint")
FORBIDDEN_PIN_PATTERNS = [
    (re.compile(r"(?m)^\s*(model|base_url|api_key|api-key)\s*:\s*(?!\"\")"), "pin de modelo/endpoint no YAML"),
    (re.compile(r"(?im)^\s*provider\s*:\s*(?!host-agent|\"host-agent\")"), "provider diferente de host-agent"),
]
MODEL_NAME_PATTERN = re.compile(
    r"(?i)\b(claude|gpt|gemini|deepseek|qwen|llama|grok|o[134](?:-mini)?)\s*(model|-\d|v\d)"
)


# ─────────────────────────────────────────────────────────────────────────────
# YAML mínimo (subset suficiente para agent/workflows/*.yaml)
# Regra de ouro: se este parser não entender, ele FALHA (nunca "chuta").
# ─────────────────────────────────────────────────────────────────────────────


class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    """Remove comentário de fim de linha, respeitando aspas simples/duplas."""
    out, quote, i = [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
            out.append(ch)
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
        i += 1
    # Só tira tab/CR: apagar espaços do fim comeria a indentação de blocos
    # literal (`pass_criteria: |` + itens indentados). Recuo significativo fica.
    return "".join(out).rstrip("\t\r")


def _scalar(raw: str):
    s = raw.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    if (s.startswith('"') and s.endswith('"') and len(s) >= 2) or (
        s.startswith("'") and s.endswith("'") and len(s) >= 2
    ):
        return s[1:-1]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_flow(inner)]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        if not inner:
            return {}
        out = {}
        for part in _split_flow(inner):
            if ":" not in part:
                raise YamlError(f"mapa flow inválido: {s}")
            k, v = part.split(":", 1)
            out[k.strip()] = _scalar(v)
        return out
    return s


def _split_flow(inner: str) -> list[str]:
    parts, buf, quote, depth = [], [], None, 0
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_yaml(text: str):
    raw_lines = text.replace("\r\n", "\n").split("\n")
    lines: list[tuple[int, str, int]] = []  # (indent, conteúdo, nº da linha)
    for no, line in enumerate(raw_lines, 1):
        if not line.strip():
            lines.append((-1, "", no))
            continue
        stripped = _strip_comment(line)
        if not stripped.strip():
            lines.append((-1, "", no))
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip(), no))

    value, idx = _parse_block(lines, 0, lines[0][0] if lines and lines[0][0] >= 0 else 0)
    # garante que o documento terminou
    while idx < len(lines) and lines[idx][0] == -1:
        idx += 1
    if idx < len(lines):
        raise YamlError(f"conteúdo não consumido na linha {lines[idx][2]}: {lines[idx][1]!r}")
    return value


def _parse_block(lines, idx, indent):
    while idx < len(lines) and lines[idx][0] == -1:
        idx += 1
    if idx >= len(lines):
        return None, idx
    if lines[idx][0] < indent:
        return None, idx
    if lines[idx][1].startswith("- "):
        return _parse_seq(lines, idx, lines[idx][0])
    if lines[idx][1] == "-":
        return _parse_seq(lines, idx, lines[idx][0])
    return _parse_map(lines, idx, lines[idx][0])


def _key_split(content: str) -> tuple[str, str] | None:
    m = re.match(r"^([^:#][^:]*?):(?:\s+(.*))?$", content)
    if not m:
        return None
    return m.group(1).strip(), (m.group(2) or "").strip()


def _parse_map(lines, idx, indent):
    out: dict = {}
    while idx < len(lines):
        cur_indent, content, no = lines[idx]
        if cur_indent == -1:
            idx += 1
            continue
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamlError(f"indentação inesperada na linha {no}: {content!r}")
        if content.startswith("- "):
            break
        kv = _key_split(content)
        if kv is None:
            raise YamlError(f"esperava 'chave: valor' na linha {no}: {content!r}")
        key, rest = kv
        idx += 1
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            block, idx = _parse_literal(lines, idx, indent, folded=rest.startswith(">"))
            out[key] = block
            continue
        if rest != "":
            out[key] = _scalar(rest)
            continue
        # valor em bloco: precisa olhar a próxima linha com conteúdo
        nxt = idx
        while nxt < len(lines) and lines[nxt][0] == -1:
            nxt += 1
        # Bloco de sequência pode ficar no MESMO recuo da chave (YAML válido) —
        # é exatamente o que dump_yaml() emite. Tratar como filho, não como fim do mapa.
        same_level_seq = (
            nxt < len(lines)
            and lines[nxt][0] == indent
            and (lines[nxt][1] == "-" or lines[nxt][1].startswith("- "))
        )
        if nxt >= len(lines) or (lines[nxt][0] <= indent and not same_level_seq):
            out[key] = None
            continue
        value, idx = _parse_block(lines, nxt, lines[nxt][0])
        out[key] = value
    return out, idx


def _parse_seq(lines, idx, indent):
    out: list = []
    while idx < len(lines):
        cur_indent, content, no = lines[idx]
        if cur_indent == -1:
            idx += 1
            continue
        if cur_indent < indent:
            break
        if cur_indent != indent or not (content == "-" or content.startswith("- ")):
            break
        body = content[1:].strip()
        if body == "":
            idx += 1
            nxt = idx
            while nxt < len(lines) and lines[nxt][0] == -1:
                nxt += 1
            if nxt < len(lines) and lines[nxt][0] > indent:
                value, idx = _parse_block(lines, nxt, lines[nxt][0])
            else:
                value = None
            out.append(value)
            continue
        kv = _key_split(body)
        if kv and not body.startswith(("'", '"', "[", "{")):
            # item de sequência que abre um mapa: reancorar a linha
            rest_indent = cur_indent + (len(content) - len(body))
            lines[idx] = (rest_indent, body, no)
            value, idx = _parse_map(lines, idx, rest_indent)
            out.append(value)
        else:
            out.append(_scalar(body))
            idx += 1
    return out, idx


def _parse_literal(lines, idx, indent, folded=False):
    collected = []
    while idx < len(lines):
        cur_indent, content, _no = lines[idx]
        if cur_indent != -1 and cur_indent <= indent:
            break
        collected.append("" if cur_indent == -1 else content)
        idx += 1
    if folded:
        return " ".join(x for x in collected if x).strip() + "\n", idx
    return "\n".join(collected) + "\n", idx


def load_yaml(path: Path):
    return parse_yaml(path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Descoberta do processo
# ─────────────────────────────────────────────────────────────────────────────


def frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$", text)
    if not m:
        return {}, text
    return parse_yaml(m.group(1)) or {}, m.group(2)


def discover():
    roles, skills, workflows, prompts = {}, {}, {}, []

    roles_dir = AGENT_DIR / "roles"
    if roles_dir.is_dir():
        for p in sorted(roles_dir.glob("*.md")):
            fm, body = frontmatter(p.read_text(encoding="utf-8"))
            roles[p.stem] = {"path": p, "meta": fm, "body": body}

    skills_dir = AGENT_DIR / "skills"
    if skills_dir.is_dir():
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            f = d / "SKILL.md"
            if f.is_file():
                fm, body = frontmatter(f.read_text(encoding="utf-8"))
                skills[d.name] = {"path": f, "meta": fm, "body": body}

    wf_dir = AGENT_DIR / "workflows"
    if wf_dir.is_dir():
        for p in sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml")):
            workflows[p.stem] = {"path": p, "doc": load_yaml(p)}

    pr_dir = AGENT_DIR / "prompts"
    if pr_dir.is_dir():
        for p in sorted(pr_dir.glob("*.md")):
            prompts.append(p)

    return roles, skills, workflows, prompts


# ─────────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": name, "status": status, "detail": detail})

    def ok(self, name, detail=""):
        self.add(name, "PASS", detail)

    def fail(self, name, detail=""):
        self.add(name, "FAIL", detail)

    def pending(self, name, detail=""):
        self.add(name, "PENDENTE", detail)

    def skip(self, name, detail=""):
        self.add(name, "SKIP", detail)

    @property
    def status(self) -> str:
        statuses = [c["status"] for c in self.checks if c["status"] != "SKIP"]
        if "FAIL" in statuses:
            return "FAIL"
        if "PENDENTE" in statuses:
            return "PENDENTE"
        return "PASS"

    @property
    def exit_code(self) -> int:
        return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "PENDENTE": EXIT_PENDING}[self.status]


def _iter_nodes(wf):
    for node in wf.get("steps") or []:
        if isinstance(node, dict):
            yield node


def _skill_list(node: dict) -> list[str]:
    out = []
    skill = node.get("skill")
    if isinstance(skill, str):
        out.append(skill)
    elif isinstance(skill, list):
        out.extend(str(s) for s in skill)
    skills = node.get("skills")
    if isinstance(skills, list):
        out.extend(str(s) for s in skills)
    return [s for s in out if s]


def check_identity(rep: Report):
    """
    O ponto inteiro: o contrato não pode pinar modelo.

    Analisa o YAML de verdade (não regex): `model: ""` é a declaração de que o modelo é do host;
    `model: "x"` é pin. Comentário explicando por que o campo está vazio não é pin.
    """
    if not AGENT_DIR.is_dir():
        rep.pending("identity.agent_dir", "agent/ ausente → PENDENTE (exit 3)")
        return
    rep.ok("identity.agent_dir", "agent/ presente")

    hits = []
    files = sorted(AGENT_DIR.rglob("*.yaml")) + sorted(AGENT_DIR.rglob("*.yml"))
    for p in files:
        try:
            doc = load_yaml(p)
        except YamlError as exc:
            hits.append(f"{p.relative_to(ROOT)}: YAML inválido ({exc})")
            continue
        if not isinstance(doc, dict):
            continue
        llm = doc.get("llm")
        if isinstance(llm, dict):
            if llm.get("provider") != HOST_PROVIDER:
                hits.append(f"{p.relative_to(ROOT)}: llm.provider != {HOST_PROVIDER}")
            for key in MODEL_PIN_KEYS:
                if key in llm and llm[key] not in (None, ""):
                    hits.append(f"{p.relative_to(ROOT)}: llm.{key} pinado ({llm[key]!r})")
    if hits:
        rep.fail("identity.no_model_pin", "; ".join(hits[:5]))
    else:
        rep.ok("identity.no_model_pin", "nenhum provider/model/base_url/api_key pinado em agent/**")

    if (ROOT / "AGENT.md").is_file():
        rep.ok("identity.agent_md", "AGENT.md presente")
    else:
        rep.fail("identity.agent_md", "AGENT.md ausente")


def check_roles(rep: Report, roles: dict):
    if not roles:
        rep.pending("roles.discovery", "nenhum papel encontrado em agent/roles/")
        return
    bad = []
    for name, r in roles.items():
        meta = r["meta"]
        if meta.get("schema") != "pong-agent-role/1":
            bad.append(f"{name}: schema inválido")
        auth = meta.get("authority")
        if auth not in AUTHORITIES:
            bad.append(f"{name}: authority {auth!r} fora de {sorted(AUTHORITIES)}")
        if auth == "veto":
            esc = meta.get("escalate_on")
            if not esc or (isinstance(esc, list) and not any(str(x).strip() for x in esc)):
                bad.append(f"{name}: authority=veto sem escalate_on (veto sem saída é proibido)")
        for key in ("name", "description", "skills", "outputs"):
            if not meta.get(key):
                bad.append(f"{name}: frontmatter sem '{key}'")
        if not r["body"].strip():
            bad.append(f"{name}: corpo vazio (papel sem prompt)")
    if bad:
        rep.fail("roles.contract", "; ".join(bad))
    else:
        rep.ok("roles.contract", f"{len(roles)} papéis com autoridade declarada")


def check_skills(rep: Report, skills: dict, roles: dict):
    if not skills:
        rep.pending("skills.discovery", "nenhuma skill em agent/skills/*/SKILL.md")
        return
    bad = []
    for name, s in skills.items():
        if s["meta"].get("schema") != "pong-agent-skill/1":
            bad.append(f"{name}: schema inválido")
        if not s["meta"].get("description"):
            bad.append(f"{name}: sem description")
        if len(s["body"].strip()) < 200:
            bad.append(f"{name}: corpo curto demais para ser método")
    missing = sorted({sk for r in roles.values() for sk in (r["meta"].get("skills") or []) if sk not in skills})
    if missing:
        bad.append(f"papéis citam skills inexistentes: {missing}")
    if bad:
        rep.fail("skills.contract", "; ".join(bad))
    else:
        rep.ok("skills.contract", f"{len(skills)} habilidades válidas")


def check_workflows(rep: Report, workflows: dict, roles: dict, skills: dict):
    if not workflows:
        rep.pending("workflows.discovery", "nenhum workflow em agent/workflows/")
        return

    problems, node_total, phase_seen = [], 0, {}

    for name, wf in workflows.items():
        doc = wf["doc"]
        where = wf["path"].name
        if not isinstance(doc, dict):
            problems.append(f"{where}: raiz não é mapa")
            continue
        if not doc.get("name"):
            problems.append(f"{where}: sem 'name'")

        llm = doc.get("llm") or {}
        if not isinstance(llm, dict):
            problems.append(f"{where}: llm não é mapa")
        else:
            if llm.get("provider") != HOST_PROVIDER:
                problems.append(f"{where}: llm.provider deve ser '{HOST_PROVIDER}' (veio {llm.get('provider')!r})")
            for key in MODEL_PIN_KEYS:
                if key in llm and llm[key] not in (None, ""):
                    problems.append(f"{where}: llm.{key} pinado ({llm[key]!r}) — o modelo é do host")

        meta = doc.get("meta") or {}
        if meta.get("schema") != "pong-agent-workflow/1":
            problems.append(f"{where}: meta.schema inválido")
        phase = str(meta.get("phase") or "")
        phases = meta.get("phases")
        declared = [str(p) for p in phases] if isinstance(phases, list) else ([phase] if phase else [])
        bad_phases = [p for p in declared if p not in PHASES]
        if not declared:
            problems.append(f"{where}: sem meta.phase/meta.phases")
        elif bad_phases:
            problems.append(f"{where}: fase(s) fora de F0–F8: {bad_phases}")
        else:
            for p in declared:
                phase_seen.setdefault(p, []).append(name)

        gate = meta.get("deterministic_gate") or {}
        if not isinstance(gate, dict) or not gate.get("command"):
            problems.append(f"{where}: sem meta.deterministic_gate.command (critério sem prova)")
        elif not str(gate.get("expect", "")).strip():
            problems.append(f"{where}: deterministic_gate sem 'expect'")

        owner = meta.get("owner")
        if owner not in roles:
            problems.append(f"{where}: meta.owner {owner!r} não é papel de agent/roles/")

        src = meta.get("source_of_truth") or []
        if not src:
            problems.append(f"{where}: sem meta.source_of_truth")
        for rel in src if isinstance(src, list) else [src]:
            if not (ROOT / str(rel)).exists():
                problems.append(f"{where}: source_of_truth inexistente: {rel}")

        nodes = list(_iter_nodes(doc))
        if not nodes:
            problems.append(f"{where}: sem steps")
        ids = [n.get("id") for n in nodes]
        if len(ids) != len(set(ids)):
            problems.append(f"{where}: ids de passo duplicados")

        for node in nodes:
            node_total += 1
            nid = node.get("id")
            tag = f"{where}::{nid}"

            role = node.get("role")
            if role not in roles:
                problems.append(f"{tag}: role {role!r} inexistente")
            if not str(node.get("task") or "").strip():
                problems.append(f"{tag}: sem task")
            criteria = node.get("pass_criteria")
            if not criteria:
                problems.append(f"{tag}: sem pass_criteria (critério falseável é obrigatório)")
            elif not isinstance(criteria, list) or not any(str(c).strip() for c in criteria):
                problems.append(f"{tag}: pass_criteria deve ser lista não vazia")
            for sk in _skill_list(node):
                if sk not in skills:
                    problems.append(f"{tag}: skill {sk!r} inexistente")

            for dep in node.get("depends_on") or []:
                if dep not in ids:
                    problems.append(f"{tag}: depends_on {dep!r} não existe")

            ho = node.get("handoff")
            if ho is not None:
                if not isinstance(ho, dict):
                    problems.append(f"{tag}: handoff não é mapa")
                else:
                    if not ho.get("declares"):
                        problems.append(f"{tag}: handoff sem declares")
                    if not ho.get("evidence"):
                        problems.append(f"{tag}: handoff sem evidence")

            veto = node.get("veto")
            if veto is not None:
                if not isinstance(veto, dict):
                    problems.append(f"{tag}: veto não é mapa")
                else:
                    if not veto.get("on"):
                        problems.append(f"{tag}: veto sem 'on'")
                    if not veto.get("escalate_on"):
                        problems.append(f"{tag}: veto sem escalate_on")
                    # Quem veta é a autoridade, não a proximidade: papel `veto` sempre pode;
                    # papel `decide` pode vetar dentro do seu escopo declarado.
                    if roles.get(node.get("role"), {}).get("meta", {}).get("authority") not in ("veto", "decide"):
                        problems.append(f"{tag}: nó declara veto mas o papel não tem autoridade de veto/decide")

            # Fase física exige handoff (o que circula entre fases)
            physical = any(p in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8") for p in declared)
            if physical and ho is None:
                if node is nodes[-1]:
                    problems.append(f"{tag}: último nó de fase física sem handoff")

        # Ordem de DAG: dependência sempre aponta para trás
        pos = {nid: i for i, nid in enumerate(ids)}
        for node in nodes:
            for dep in node.get("depends_on") or []:
                if dep in pos and pos[dep] > pos[node.get("id")]:
                    problems.append(f"{where}::{node.get('id')}: depends_on aponta para frente ({dep})")

    if problems:
        rep.fail("workflows.contract", " | ".join(problems[:10]) + (" …" if len(problems) > 10 else ""))
    else:
        rep.ok("workflows.contract", f"{len(workflows)} workflows, {node_total} nós, todos com papel+critério+gate")

    missing_phases = [p for p in PHASES if p not in phase_seen]
    if missing_phases:
        # Fase sem workflow é buraco de processo, não erro de digitação: FAIL, nunca aviso.
        rep.fail("workflows.coverage", f"fases sem workflow: {missing_phases}")
    else:
        rep.ok("workflows.coverage", "F0–F8 cobertas")


def check_prompts(rep: Report, prompts: list[Path]):
    index_path = AGENT_DIR / "prompts" / "index.yaml"
    if not index_path.is_file():
        rep.pending("prompts.index", "agent/prompts/index.yaml ausente")
        return
    try:
        index = load_yaml(index_path)
    except YamlError as exc:
        rep.fail("prompts.index", f"YAML inválido: {exc}")
        return

    problems = []
    if index.get("schema") != "pong-agent-prompt/1":
        problems.append("schema inválido")
    parts = index.get("parts") or []
    if not parts:
        problems.append("sem parts")
    for part in parts:
        f = AGENT_DIR / "prompts" / str(part.get("file"))
        if not f.is_file():
            problems.append(f"parte ausente: {part.get('file')}")
            continue
        body = f.read_text(encoding="utf-8")
        for section in part.get("required_sections") or []:
            if f"# {section}" not in body and f"## {section}" not in body:
                problems.append(f"{part.get('file')}: seção obrigatória '{section}' ausente")

    compose = (index.get("compose") or {})
    order = compose.get("order") or []
    if sorted(order) != sorted(str(p.get("id")) for p in parts):
        problems.append(f"compose.order {order} não cobre as parts")
    target = (compose.get("target") or {}).get("claude_agents_file")
    if not target:
        problems.append("compose.target.claude_agents_file ausente")

    for pattern in compose.get("forbidden_patterns") or []:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            problems.append(f"forbidden_patterns inválido {pattern!r}: {exc}")

    if problems:
        rep.fail("prompts.contract", "; ".join(problems))
    else:
        rep.ok("prompts.contract", f"{len(parts)} partes + índice de composição")


def compose_prompt() -> str:
    index = load_yaml(AGENT_DIR / "prompts" / "index.yaml")
    sep = index["compose"].get("separator", "\n\n---\n\n")
    order = index["compose"]["order"]
    parts = {str(p["id"]): p for p in index["parts"]}
    chunks = []
    for pid in order:
        f = AGENT_DIR / "prompts" / str(parts[pid]["file"])
        chunks.append(f.read_text(encoding="utf-8").strip())
    return sep.join(chunks) + "\n"


PROMPT_SHA_MARK = "pong-agent-prompt-sha256:"


def published_prompt_text() -> tuple[str, str]:
    """(conteúdo publicado, sha da composição) — gerar e conferir usam esta mesma função."""
    body = compose_prompt()
    sha = hashlib.sha256(body.encode()).hexdigest()
    index = load_yaml(AGENT_DIR / "prompts" / "index.yaml")
    target = ((index.get("compose") or {}).get("target") or {}).get("claude_agents_file")
    description = (
        "Agente de processo do repo nothing-phone2-kernel-rom-cicd (kernel/ROM Nothing Phone 2, "
        "single-slot Slot A). Roda no modelo do host; papéis, habilidades e gates vêm de agent/ "
        "e AGENT.md."
    )
    header = (
        "---\n"
        "name: pong-orchestrator\n"
        f"description: {description}\n"
        "---\n\n"
        "<!-- GERADO por `make agent-prompt`. Não edite à mão: edite agent/prompts/ e regenere.\n"
        f"     {PROMPT_SHA_MARK} {sha} -->\n\n"
    )
    return header + body, sha


def check_published_prompt(rep: Report) -> None:
    """
    O prompt publicado (`.claude/agents/pong-orchestrator.md`) é derivado, não fonte.
    Se existir e estiver defasado em relação a agent/prompts/, isso é FAIL: um agente com
    contrato velho é pior que agente nenhum.
    """
    index = load_yaml(AGENT_DIR / "prompts" / "index.yaml")
    target_rel = ((index.get("compose") or {}).get("target") or {}).get("claude_agents_file")
    if not target_rel:
        rep.fail("prompts.published", "compose.target.claude_agents_file ausente")
        return
    target = ROOT / str(target_rel)
    if not target.is_file():
        rep.pending("prompts.published", f"{target_rel} não gerado (rode: make agent-prompt > {target_rel})")
        return
    body = target.read_text(encoding="utf-8")
    m = re.search(re.escape(PROMPT_SHA_MARK) + r"\s*([0-9a-f]{64})", body)
    if not m:
        rep.fail("prompts.published", f"{target_rel} sem marcador de origem")
        return
    expected_text, current = published_prompt_text()
    if m.group(1) != current or body != expected_text:
        rep.fail("prompts.published", f"{target_rel} defasado (regenere com make agent-prompt)")
    else:
        rep.ok("prompts.published", f"{target_rel} em sincronia com agent/prompts/")


def check_composed_prompt(rep: Report):
    try:
        text = compose_prompt()
    except (YamlError, KeyError, FileNotFoundError) as exc:
        rep.fail("prompts.composed", f"não foi possível montar: {exc}")
        return
    problems = []
    for pattern in (MODEL_NAME_PATTERN, re.compile(r"(?i)\bbase_url\b|\bapi_key\b")):
        for m in pattern.finditer(text):
            problems.append(f"prompt montado cita modelo/credencial: {m.group(0)!r}")
    if "host-agent" not in text and "host" not in text.lower():
        problems.append("prompt montado não declara que o runtime é o host")
    if problems:
        rep.fail("prompts.composed", "; ".join(problems[:5]))
    else:
        rep.ok("prompts.composed", f"{len(text)} bytes, sem pin de modelo")


def check_install_sequence_aliases(rep: Report, roles: dict):
    """
    AGENTS.md/CODEOWNERS citavam @mechanical-coder/@android-architect/@security-reviewer, handles
    que não existiam em lugar nenhum. Agora todo `@papel` citado tem de existir em agent/roles/.
    """
    paths = [ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / ".github" / "CODEOWNERS"]
    known = set(roles)
    problems = []
    for p in paths:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        for handle in sorted(set(re.findall(r"(?<![\w./])@([a-z][a-z0-9]*(?:-[a-z0-9]+)+)", text))):
            if handle not in known:
                problems.append(f"{p.relative_to(ROOT)} cita @{handle} que não é papel de agent/roles/")
    if problems:
        rep.fail("roles.aliases", "; ".join(problems))
    else:
        rep.ok("roles.aliases", "nenhuma referência a papel inexistente")


def process_fingerprint(roles, skills, workflows, prompts) -> str:
    files = [ROOT / "AGENT.md"]
    files += [r["path"] for r in roles.values()]
    files += [s["path"] for s in skills.values()]
    files += [w["path"] for w in workflows.values()]
    files += prompts
    files += [AGENT_DIR / "prompts" / "index.yaml"]
    digest = hashlib.sha256()
    for f in sorted({p for p in files if p.is_file()}):
        digest.update(str(f.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(f.read_bytes()).digest())
    return digest.hexdigest()


def check_source_of_truth_sync(rep: Report, workflows: dict):
    """O agente não inventa pin: o contrato tem de concordar com os objetos."""
    plan_p = ROOT / "objects" / "kernel-build-plan.json"
    if not plan_p.is_file():
        rep.pending("pins.objects", "kernel-build-plan.json ausente")
        return
    plan = json.loads(plan_p.read_text(encoding="utf-8"))
    kernel_pin = (plan.get("source") or {}).get("pin", "")

    corpus_parts = [w["path"].read_text(encoding="utf-8") for w in workflows.values()]
    for rel in sorted((AGENT_DIR / "skills").rglob("*.md")):
        corpus_parts.append(rel.read_text(encoding="utf-8"))
    corpus = "\n".join(corpus_parts)
    problems = []
    if kernel_pin and len(kernel_pin) == 40 and kernel_pin[:12] not in corpus:
        problems.append(f"nenhum workflow cita o pin do kernel ({kernel_pin[:12]}…)")
    for patch in (plan.get("build") or {}).get("patch_set") or []:
        sha = patch.get("sha256", "")
        f = ROOT / "kernel" / "patches" / patch.get("file", "")
        if f.is_file():
            real = hashlib.sha256(f.read_bytes()).hexdigest()
            if sha and real != sha:
                problems.append(f"sha256 divergente para {patch.get('file')}")
    rom_p = ROOT / "objects" / "rom-artifacts.json"
    if rom_p.is_file():
        rom = json.loads(rom_p.read_text(encoding="utf-8"))
        for variant in rom.get("variants") or []:
            sha = variant.get("sha256", "")
            if sha and not re.fullmatch(r"[0-9a-f]{64}", str(sha)):
                problems.append(f"rom-artifacts: sha256 inválido em {variant.get('id')}")
    if problems:
        rep.fail("pins.source_of_truth", "; ".join(problems))
    else:
        rep.ok("pins.source_of_truth", "pins do contrato batem com objects/")


def check_ao_compat(rep: Report, ao_cmd: str | None, base_url: str):
    """
    Compatibilidade com o motor agency-orchestrator: o MESMO contrato (papéis, DAG, acceptance,
    skills) roda no `ao` — sem pin de modelo, apontando o provider para o host.

    Dois níveis:
      * forma (sempre): gera o workflow no dialeto AO e valida o YAML gerado aqui;
      * real (--require-compat): roda `ao validate` de verdade, se o binário existir.
    """
    project = build_ao_project(base_url)
    problems = []
    for name, meta in project["workflows"].items():
        text = project["files"][meta["file"]]
        try:
            parsed = parse_yaml(text)
        except YamlError as exc:
            problems.append(f"{name}: YAML gerado inválido ({exc})")
            continue
        if not parsed.get("steps"):
            problems.append(f"{name}: sem steps após geração")
        llm = parsed.get("llm") or {}
        if llm.get("provider") != AO_PROVIDER:
            problems.append(f"{name}: provider do projeto AO deve ser {AO_PROVIDER} (endpoint do host)")
        if llm.get("model") != HOST_PROVIDER:
            problems.append(f"{name}: model do projeto AO deve ser '{HOST_PROVIDER}' (o host responde)")
    if problems:
        rep.fail("compat.ao_form", "; ".join(problems[:5]))
    else:
        rep.ok("compat.ao_form", f"{len(project['workflows'])} workflows no dialeto AO, provider={HOST_PROVIDER}")

    if not ao_cmd:
        # Compatibilidade com o motor é OPCIONAL: não roda em toda máquina e não pode
        # pintar de PENDENTE um contrato que está completo. `make agent-compat` exige.
        rep.skip("compat.ao_engine", "motor AO não exigido (use: make agent-compat)")
        return

    exe = shutil.which(ao_cmd)
    if not exe:
        rep.pending("compat.ao_engine", f"binário '{ao_cmd}' não encontrado → PENDENTE (exit 3)")
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for rel, content in project["files"].items():
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        results = []
        for name, meta in project["workflows"].items():
            proc = subprocess.run([exe, "validate", meta["arg"]], cwd=tmp, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                out = (proc.stdout + proc.stderr).strip().replace("\n", " ")[:220]
                results.append(f"{meta['arg']}: exit {proc.returncode} — {out}")
        if results:
            rep.fail("compat.ao_engine", "; ".join(results[:4]))
        else:
            rep.ok("compat.ao_engine", f"{len(project['workflows'])} workflows + papéis validados pelo motor real")


# ─────────────────────────────────────────────────────────────────────────────
# Projeção para o dialeto do AO (o mesmo contrato, outro transporte)
# ─────────────────────────────────────────────────────────────────────────────


def build_ao_project(base_url: str) -> dict:
    roles, skills, workflows, _ = discover()
    files: dict[str, str] = {}
    wf_projection: dict[str, dict] = {}

    for name, r in roles.items():
        meta = r["meta"]
        head = (
            "---\n"
            f"name: {meta.get('name')}\n"
            f"description: {json.dumps(meta.get('description', ''), ensure_ascii=False)}\n"
            f"emoji: {meta.get('emoji', '🤖')}\n"
            "---\n\n"
        )
        files[f"agents/pong/{name}.md"] = head + r["body"].lstrip()

    for name, s in skills.items():
        files[f"skills/{name}/SKILL.md"] = s["path"].read_text(encoding="utf-8")

    for name, wf in workflows.items():
        doc = wf["doc"]
        nodes = list(_iter_nodes(doc))
        inputs = [i for i in (doc.get("inputs") or []) if isinstance(i, dict)]

        # O motor AO liga variáveis por NOME DE SAÍDA declarado no passo de origem.
        # Então: para cada passo, a saída é o {{var}} que os passos a jusante consomem.
        referenced = set()
        for node in nodes:
            for var in re.findall(r"\{\{(\w+)\}\}", str(node.get("task") or "")):
                referenced.add(var)
        input_names = {str(i.get("name")) for i in inputs}
        produced = {}
        for node in nodes:
            nid = str(node["id"])
            downstream = set()
            for other in nodes:
                if nid in (other.get("depends_on") or []):
                    downstream |= set(re.findall(r"\{\{(\w+)\}\}", str(other.get("task") or "")))
            candidates = [v for v in downstream if v not in input_names and v in referenced]
            # Uma saída por passo: se duas variáveis apontam para o mesmo antecessor, o motor
            # rejeita a ambiguidade ("output produzido por vários steps") — fica a primeira.
            if len(candidates) > 1:
                pass
            produced[nid] = candidates[0] if candidates else f"{nid}_out"

        # Uma variável só pode ser produzida por UM passo (o motor reprova ambiguidade).
        # Então: saída = variável que o primeiro consumidor a jusante usa; quem consome sem ser
        # o primeiro (ou consome várias) ganha sufixo próprio e recebe a variável no task.
        takeover: dict[str, str] = {}
        produced: dict[str, str] = {}
        for node in nodes:
            nid = str(node["id"])
            downstream = set()
            for other in nodes:
                if nid in (other.get("depends_on") or []):
                    downstream |= set(re.findall(r"\{\{(\w+)\}\}", str(other.get("task") or "")))
            free = sorted(v for v in downstream if v not in input_names and v in referenced and v not in produced.values())
            if free:
                produced[nid] = free[0]
                for alias in free[1:]:
                    takeover[alias] = free[0]
            else:
                produced[nid] = f"{nid}_out"

        steps = []
        for node in nodes:
            nid = str(node["id"])
            criteria = node.get("pass_criteria") or []
            task = str(node.get("task") or "").strip()
            for alias, canonical in takeover.items():
                task = re.sub(r"\{\{" + re.escape(alias) + r"\}\}", "{{" + canonical + "}}", task)
            step = {
                "id": nid,
                "role": f"pong/{node['role']}",
                "task": task,
                "output": produced[nid],
                "acceptance": "\n".join(f"- {c}" for c in criteria),
            }
            deps = node.get("depends_on") or []
            if deps:
                step["depends_on"] = list(deps)
            skills_here = _skill_list(node)
            if skills_here:
                step["skills"] = skills_here
            steps.append(step)

        projected_inputs = []
        for i in inputs:
            item = {"name": str(i.get("name")), "required": bool(i.get("required", False))}
            if i.get("description"):
                item["description"] = str(i["description"])
            if i.get("default") is not None:
                item["default"] = str(i["default"])
            projected_inputs.append(item)

        files[f"workflows/{name}.yaml"] = dump_yaml(
            {
                "name": doc.get("name") or name,
                "description": doc.get("description", ""),
                "agents_dir": "agents",
                # Dialeto do motor: provider de endpoint customizado precisa de nome conhecido
                # + base_url; o "modelo" é o próprio host (host-agent), e o agente em AGENT.md
                # declara que qualquer nome serve — o contrato não depende dele.
                "llm": {"provider": AO_PROVIDER, "model": HOST_PROVIDER, "base_url": base_url},
                "concurrency": 1,
                "inputs": projected_inputs,
                "steps": steps,
            }
        )
        # O `ao validate` exige caminho com separador (sem ele, resolve como template embutido).
        wf_projection[name] = {"file": f"workflows/{name}.yaml", "arg": f"./workflows/{name}.yaml"}

    files["README.md"] = (
        "# Projeção do processo Pong para o dialeto agency-orchestrator\n\n"
        "Gerado por `scripts/ao_gate.py --project ao`.\n\n"
        f"- runtime: `{HOST_PROVIDER}` (o host é o modelo)\n"
        f"- base_url: `{base_url}`\n"
        "- papéis: `agents/pong/*.md` (autoridade no frontmatter)\n"
        "- skills: `skills/*/SKILL.md`\n"
        "- workflows: `workflows/*.yaml` (acceptance = pass_criteria)\n"
    )
    return {"files": files, "workflows": wf_projection}


def dump_yaml(value, indent: int = 0) -> str:
    """
    Serializador YAML mínimo, determinístico e compatível com o parser acima.
    Não tenta ser geral: emite só o que build_ao_project() produz — e o gate reparseia
    o resultado, então um erro aqui vira FAIL, não release silencioso.
    """
    pad = "  " * indent
    plain_ok = re.compile(r"^[A-Za-z0-9_./()\[\]-][^\n]*$")

    def scalar(v) -> str:
        if v is None:
            return '""'
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        text = str(v)
        needs_quote = (
            text == ""
            or text.strip() != text
            or text[0] in "-?:,[]{}#&*!|>'\"%@`"
            or ": " in text
            or " #" in text
        )
        return json.dumps(text, ensure_ascii=False) if needs_quote else text

    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, dict) and v:
                out.append(f"{pad}{k}:")
                out.append(dump_yaml(v, indent + 1).rstrip("\n"))
            elif isinstance(v, list) and v:
                out.append(f"{pad}{k}:")
                out.append(dump_yaml(v, indent).rstrip("\n"))
            elif isinstance(v, str) and "\n" in v:
                out.append(f"{pad}{k}: |")
                out.extend(f"{pad}  {line}" for line in v.splitlines())
            else:
                out.append(f"{pad}{k}: {scalar(v)}")
        return "\n".join(out) + "\n"

    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                rendered = dump_yaml(item, indent + 1).splitlines()
                out.append(f"{pad}- {rendered[0].strip()}")
                out.extend(rendered[1:])
            elif isinstance(item, str) and "\n" in item:
                out.append(f"{pad}- |")
                out.extend(f"{pad}  {line}" for line in item.splitlines())
            else:
                out.append(f"{pad}- {scalar(item)}")
        return "\n".join(out) + "\n"

    return f"{pad}{scalar(value)}\n"


# ─────────────────────────────────────────────────────────────────────────────
# Modos de uso
# ─────────────────────────────────────────────────────────────────────────────


def phase_plan(phase_filter: str | None) -> str:
    _, _, workflows, _ = discover()
    lines = []
    matched = []
    for name, wf in workflows.items():
        doc = wf["doc"]
        meta = doc.get("meta") or {}
        if phase_filter and str(meta.get("phase")) != phase_filter:
            continue
        matched.append((name, doc, meta))
    if not matched:
        return f"Nenhum workflow para a fase {phase_filter!r}."
    for name, doc, meta in matched:
        gate = meta.get("deterministic_gate") or {}
        lines.append(f"\n## {doc.get('name', name)}  [meta.phase={meta.get('phase')}]")
        lines.append(f"gate: `{gate.get('command')}` → {gate.get('expect')}")
        lines.append("")
        nodes = list(_iter_nodes(doc))
        ids = [n["id"] for n in nodes]
        depth = {}

        def d(nid):
            if nid in depth:
                return depth[nid]
            node = next(n for n in nodes if n["id"] == nid)
            deps = node.get("depends_on") or []
            depth[nid] = 0 if not deps else max(d(x) for x in deps) + 1
            return depth[nid]

        for nid in ids:
            d(nid)
        for layer in range(max(depth.values()) + 1 if depth else 0):
            for node in nodes:
                if depth[node["id"]] != layer:
                    continue
                sk = ", ".join(_skill_list(node)) or "—"
                lines.append(
                    f"  L{layer + 1}  [{node['id']}]  {node.get('role')}  (skill: {sk})"
                )
                for crit in node.get("pass_criteria") or []:
                    lines.append(f"        ✔ {crit}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate do processo do agente (não do modelo).")
    ap.add_argument("--json", action="store_true", help="saída legível por máquina")
    ap.add_argument("--phase", help="imprime o plano da fase (F0..F8)")
    ap.add_argument("--compose", metavar="NAME", help="imprime a composição (ex.: system-prompt)")
    ap.add_argument("--emit", metavar="FILE", help="grava a composição em arquivo")
    ap.add_argument("--project", choices=["ao"], help="gera o projeto no dialeto do agency-orchestrator")
    ap.add_argument("--out", metavar="DIR", help="diretório de saída para --project")
    ap.add_argument("--base-url", default=os.environ.get("PONG_HOST_BASE_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--require-compat", action="store_true", help="exige validação pelo motor real")
    ap.add_argument("--ao-cmd", default=None, help="binário do agency-orchestrator (ex.: ao, npx ao)")
    ap.add_argument("--fingerprint", action="store_true", help="imprime só o fingerprint do processo")
    ap.add_argument("--write-prompt", action="store_true",
                    help="regenera o prompt publicado (.claude/agents/pong-orchestrator.md)")
    args = ap.parse_args(argv)

    if args.write_prompt:
        text, sha = published_prompt_text()
        index = load_yaml(AGENT_DIR / "prompts" / "index.yaml")
        rel = ((index.get("compose") or {}).get("target") or {}).get("claude_agents_file")
        out = ROOT / str(rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[PASS] {rel} regenerado ({sha[:16]}…)")
        return EXIT_PASS

    if args.phase:
        print(phase_plan(args.phase.rstrip(".")), end="")
        return EXIT_PASS

    if args.compose or args.emit:
        text = compose_prompt()
        if args.emit:
            out = Path(args.emit)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"[PASS] composição gravada em {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
        else:
            print(text, end="")
        return EXIT_PASS

    if args.project:
        project = build_ao_project(args.base_url)
        out = Path(args.out) if args.out else (ROOT / "build" / "ao")
        for rel, content in project["files"].items():
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        print(f"[PASS] projeto AO gerado em {out} ({len(project['files'])} arquivos)")
        for meta in project["workflows"].values():
            print(f"  ao run {out / meta['file']}")
        return EXIT_PASS

    roles, skills, workflows, prompts = discover()
    rep = Report()
    try:
        check_identity(rep)
        check_roles(rep, roles)
        check_skills(rep, skills, roles)
        check_workflows(rep, workflows, roles, skills)
        check_prompts(rep, prompts)
        check_composed_prompt(rep)
        check_published_prompt(rep)
        check_install_sequence_aliases(rep, roles)
        check_source_of_truth_sync(rep, workflows)
        check_ao_compat(rep, (args.ao_cmd or "ao") if args.require_compat else None, args.base_url)
    except YamlError as exc:
        rep.fail("yaml.parse", f"YAML do contrato inválido: {exc}")

    fp = process_fingerprint(roles, skills, workflows, prompts)

    if args.json:
        print(json.dumps(
            {"schema": "pong-agent-gate/1", "status": rep.status, "process_fingerprint": fp,
             "counts": {"roles": len(roles), "skills": len(skills), "workflows": len(workflows)},
             "checks": rep.checks},
            indent=2, ensure_ascii=False))
    else:
        print("Gate do processo do agente — o modelo não entra na conta\n")
        for c in rep.checks:
            mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "PENDENTE": "[PENDENTE]", "SKIP": "[SKIP]"}[c["status"]]
            print(f"{mark} {c['check']}: {c['detail']}")
        print()
        print(f"[SUMMARY] {rep.status} — {len(roles)} papéis · {len(skills)} habilidades · "
              f"{len(workflows)} workflows")
        print(f"agent-process-fingerprint: {fp}")

    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
