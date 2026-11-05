# Nothing Phone 2 Kernel + ROM CI/CD

Custom kernel and ROM build infrastructure for Nothing Phone 2 (codename: pong).

## Project Overview

This repository provides the CI/CD infrastructure for building and validating:

- **Kernel**: LineageOS kernel (sm8475) with KernelSU-Next, SUSFS, and custom DroidSpaces kABI patches
- **ROM**: Evolution X 11.11 (Android 16 / API 36) with GApps integration

## Build Environment

- **OS**: Ubuntu (ubuntu-latest)
- **Toolchain**: clang-r530567 (Android 14/15), DDK ghcr.io/ylarod/ddk-min:android13-5.10-2025-04
- **Kernel Source**: LineageOS `lineage-23.2` branch (`android13-5.10` KMI)
- **GKI**: Yes, with vendor-specific configuration fragments
- **Patches**: DroidSpaces kABI patches 001 (sysvipc) and 002 (mqueue-padding)
- **Root**: KernelSU-Next v3.4.2 embedded
- **Integrity**: SUSFS module R28 + Zygisk Next

## Usage

```bash
# Clone the repository
git clone https://github.com/your-org/nothing-phone2-kernel-rom-cicd.git
cd nothing-phone2-kernel-rom-cicd

# Run the stack gate to validate all invariants
python3 scripts/stack_gate.py --config objects/install-stack.json

# Validate kernel build plan structure
python3 scripts/kernel_build_gate.py --config objects/kernel-build-plan.json

# Validate the agent process (contract, not model)
python3 scripts/ao_gate.py

# Or use GitHub Actions
gh workflow run lint.yml

# Or use Make targets
make stack       # Validate stack invariants
make prove       # Full build verification
make kernel-build # Validate kernel build plan
make agent       # Validate the agent process (roles, skills, workflows, prompts)
make agent-phase PHASE=F5   # Print the F5 plan in dependency order
make agent-compat           # Validate the same contract on the real `ao` engine
```

## The agent is a process, not a model

[`AGENT.md`](AGENT.md) is the normative contract; [`agent/`](agent/README.md) is its executable form:
11 roles with declared authority, 7 reusable skills, and one workflow per phase block (F0–F8).

| Question | Answer |
|---|---|
| Which model runs it? | Whatever the **host** runs. Nothing here pins one. |
| What proves a step passed? | `meta.deterministic_gate` — a command/CI job, not a model verdict. |
| What happens with no evidence? | `PENDENTE` (exit 3). Never `PASS`. |
| Who may deploy? | Nobody in this repository. The pipeline is release-only; a human flashes. |
| How do I know *what* ran? | `agent-process-fingerprint` (sha256 of the process files), recorded in CI. |

The form follows [`jnMetaCode/agency-orchestrator`](https://github.com/jnMetaCode/agency-orchestrator)
(role markdown, declarative YAML, `acceptance` per step, `depends_on` DAG) — with two deliberate
differences: **no LLM provider in the contract**, and **no self-certification by the model**.

## Governance

### Code Owners

All changes require review from the repository owner (`@camillanapoles`), per `.github/CODEOWNERS`.
Review authority in the process is separate from merge authority:

| Layer | Who | Where |
|---|---|---|
| Merge / release | the owner (human) | `.github/CODEOWNERS` |
| Process authority (decide/veto/advise) | 11 agent roles | `agent/roles/`, summarized in `AGENTS.md` |
| Enforcement | deterministic gates | `scripts/stack_gate.py`, `scripts/kernel_build_gate.py`, `scripts/ao_gate.py` |

The agent contract is in [`AGENT.md`](AGENT.md). The agent runs on the **host model**: no file in
this repository pins `provider`, `model`, `base_url` or `api_key` — `make agent` fails the build if
one appears.

### Pull Request Requirements

1. All PRs must pass CI validation
2. At least one code owner approval required
3. All 16 stack invariants must pass validation
4. YAML workflow files must pass lint
5. Kernel pin SHAs must be verified in source repos
6. No modified binaries committed (objects/*.json are source of truth)
7. Single-slot (Slot A) deployment only

### CI/CD Pipeline

```
objects/          -> stack_gate.py validates invariants
agent/            -> ao_gate.py validates the agent process (roles, skills, workflows)
scripts/          -> Build and validation scripts
.github/workflows/ -> Automated CI/CD pipelines (release-only, fail-closed)
kernel/           -> Kernel source and patches
Makefile          -> Build verification targets
```

### Agent process

- `AGENT.md` - normative contract: authority boundary, handoff, what the agent is **not**
- `agent/roles/` - 11 roles with declared authority (`decide`/`recommend`/`veto`/`advise`/`report`)
- `agent/skills/` - 7 reusable methods (`pin-discipline`, `falsifiable-evidence`, …)
- `agent/workflows/` - one YAML per phase block, each with a `meta.deterministic_gate`
- `agent/prompts/` - composable prompt (published to `.claude/agents/pong-orchestrator.md`)
- `scripts/ao_gate.py` - the gate that enforces all of the above

### Object Definitions

- `objects/install-stack.json` - Complete installation plan with all layers, phases, and constraints
- `objects/kernel-build-plan.json` - Kernel build requirements and toolchain configuration
- `objects/rom-artifacts.json` - ROM variant artifacts (vanilla, GApps)
- `objects/kernel-candidates.json` - Available kernel candidates for building

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | Invariant violation detected |
| 3 | Missing input files (PENDENTE) |

## Production Audit Status

- **Score**: 78/100 (improved from 52/100)
- **Fixed**: Missing patch files, pinned GitHub Actions SHAs, stack gate invariants, Makefile, CODEOWNERS
- **Remaining**: Download actual patch binaries, full CI workflow implementation