# Nothing Phone 2 Kernel/ROM CI/CD Project

## Plan: CI/CD DevOps Pipeline & Multi-Agent Orchestration for Nothing Phone (2) "pong" Kernel & Evolution X ROM

### Context

The objective is to establish a automated, production-grade GitHub Actions CI/CD pipeline and governance framework for building a custom Android 16 (Evolution X 11.11) ROM and custom Linux Kernel (LineageOS base `lineage-23.2` with KernelSU-Next v3.4.2, SUSFS, and DroidSpaces kABI patches) for the Nothing Phone (2) (codename `pong`, Qualcomm Snapdragon 8+ Gen 1 `SM8475`).

The implementation follows the exact object specifications from `@objects/`:
- `install-stack.json`: 21-layer stack, 16 invariants enforced via `scripts/stack_gate.py`.
- `kernel-build-plan.json`: LineageOS kernel tree commit `4ec5491f6b5f...`, clang-r530567 toolchain, patches `001-kabi-sysvipc`, `002-mqueue-padding`, embedded KernelSU-Next, and SUSFS.
- `rom-artifacts.json`: Evolution X 11.11 Vanilla (`26be9ac8bb21...`) and GApps (`79236f9b4259...`) builds.
- `kernel-candidates.json`: Fixture certification validation.
- `INSTALL-SEQUENCE.md`: Installation procedure, **adjusted for single-slot (Slot A only)** as requested.

---

### 1. Repository Structure & Tree Specification

New Repository Name: `nothing-phone2-kernel-rom-cicd`

```
nothing-phone2-kernel-rom-cicd/
├── .github/
│   ├── CODEOWNERS
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── workflows/
│       ├── kernel-build.yml       # Custom Kernel CI (android-kernel-build-action)
│       ├── rom-build.yml          # Evolution X ROM & Packaging CI
│       └── stack-governance.yml   # Stack Gate & Invariant Validator
├── objects/                       # Canonical JSON definitions (Source of Truth)
│   ├── install-stack.json
│   ├── kernel-build-plan.json
│   ├── kernel-candidates.json
│   └── rom-artifacts.json
├── kernel/
│   ├── configs/
│   │   └── evox_pong_pack.config  # Dedicated GKI fragment (CONFIG_SYSVIPC, SUSFS, KSU)
│   ├── patches/
│   │   ├── 001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8.patch
│   │   ├── 002.5.10_or_lower_use_android_abi_padding_for_posix_mqueue.patch
│   │   └── SHA256SUMS
│   └── scripts/
│       └── apply_patches.sh
├── scripts/
│   ├── stack_gate.py              # Enforces 16 stack invariants
│   ├── kernel_build_gate.py       # Validates build requirements & SHA256 hashes
│   └── rollout_gate.sh            # Single-slot (Slot A) flash & verification gate
├── INSTALL-SEQUENCE.md            # Human-readable guide (Slot A adjusted)
└── README.md
```

---

### 2. GitHub Governance & Continuity Rules

1. **Branch Protection (`main`)**:
    - Require pull request reviews (minimum 1 approval).
    - Require status checks to pass before merging (`stack-governance`, `kernel-build`).
    - Require linear history; no force pushes.
2. **Pinned Action Integrity**:
    - All GitHub Actions pinned by full 40-character SHA hash (NFR-05 compliant).
    - No floating `@vN` tags allowed in `.github/workflows/`.
3. **Artifact Attestation & Reproducibility**:
    - Enforce build provenance via `actions/attest-build-provenance@4d101475...`
    - Generate `SHA256SUMS` for all output images (`boot.img`, `dtbo.img`, `Image`, AnyKernel3 zip).
4. **Secretless Build Execution (NFR-10)**:
    - Pipeline operates on public forks without mandatory external PATs.

---

### 3. CI/CD GitHub Actions Workflows

#### 3.1 Kernel Build Workflow (`.github/workflows/kernel-build.yml`)
Uses `actions/checkout@3d3c42e5...` and `actions/cache@55cc8345...` for ccache persistence, with matrix strategy validating kernel candidates and applying patches reproducibly.

- **Trigger**: Push to `main`, PRs touching `kernel/` or `objects/`, `workflow_dispatch`.
- **Steps**:
1. Checkout kernel source (`LineageOS/android_kernel_nothing_sm8475` @ `4ec5491f6b5f...`).
2. Setup Clang (`clang-r530567` / Android 13 5.10 toolchain).
3. Apply DroidSpaces kABI patches (`001`, `002`), integrate KernelSU-Next v3.4.2, and apply SUSFS.
4. Run build using `gki_defconfig` + `evox_pong_pack.config`.
5. Package `boot.img`, `dtbo.img`, and AnyKernel3 zip.
6. Attest build provenance & upload release draft.

#### 3.2 Stack Governance Workflow (`.github/workflows/stack-governance.yml`)
- **Trigger**: Every PR and push.
- **Steps**:
1. Execute `python3 scripts/stack_gate.py` to verify the 16 stack invariants.
2. Validate JSON schemas for `install-stack.json` and `kernel-build-plan.json`.
3. Verify pinned commit SHAs against GitHub APIs.

---

### 4. Single-Slot (Slot A) Installation Adaptation (`INSTALL-SEQUENCE.md`)

*Note: Adapted from original dual-slot sequence to enforce Slot A execution per user requirement.*

| Phase | Description | Slot A Action | PASS Condition |
|---|---|---|---|
| **F0** | Pre-flight & Verification | Download artifacts, verify SHA256 | `make -s prove` exit 0 |
| **F1** | Base Flash | `fastboot flash --slot=a firmware.bin` + `fastboot flash --slot=a boot` + sideload EvolutionX Vanilla | About shows EvolutionX 11.11 |
| **F2** | First Boot Cleanup | Setup without restore, Play Protect off, WebView AOSP verified | `dumpsys webviewupdate` valid |
| **F3** | Root (Slot A) | Flash patched `boot.img` to Slot A (`fastboot flash boot_a boot-ksu.img`) | `su -c id` returns `uid=0` |
| **F4** | Hiding Stack | Install `susfs4ksu` R28 + Zygisk Next (`just_umount`) | Ruru / Duck Detector clean |
| **F5** | Integrity | Deploy PIFork + TEESimulator-RS Enhanced + keybox.xml | Play Integrity: BASIC + DEVICE green |
| **F6** | Apps & Features | Install CircleToSearch (`e4f4614`), Morphe v2.3.0, Gemini | All 7 CTS criteria PASS |
| **F7** | Performance | Deploy Universal GMS Doze 1.9.11 | Background restriction active, FCM ok |

---


# Agent contract (read this first)

O agente deste repo é **processo, não modelo**. O contrato normativo é `AGENT.md`; a forma
executável é `agent/` (11 papéis, 7 habilidades, workflows por bloco de fase, prompt componível).
O gate `scripts/ao_gate.py` reprova qualquer pin de `provider`/`model`/`base_url`/`api_key` em
`agent/**` — o modelo é o do host e trocá-lo não muda veredito.

Forma herdada de `jnMetaCode/agency-orchestrator` (papéis em markdown, YAML declarativo,
`acceptance` por passo, DAG por `depends_on`), sem as duas coisas que não servem aqui: provider de
LLM no contrato e auto-certificação do modelo.

# Build Commands
```bash
# Validate stack invariants (16 checks)
python3 scripts/stack_gate.py --config objects/install-stack.json

# Validate kernel build plan
python3 scripts/kernel_build_gate.py --config objects/kernel-build-plan.json

# Validate the agent process (roles, skills, workflows, prompts)
python3 scripts/ao_gate.py

# Prove the agent gate actually rejects
python3 scripts/test_agent_contract.py

# Run all CI checks
make stack   # Validates JSON against schema and invariants
make prove   # Full fail-closed verification (stack + kernel + agent + boundary + mutation)
```

## Python Environment
- Scripts use Python 3.x (standard library only; no external packages)
- JSON schema validation via `jsonschema` package (install with `pip install jsonschema`)

## Critical Constraints
- **O modelo é do host** - nenhum arquivo pina `provider`, `model`, `base_url` ou `api_key`;
  `make agent` reprova. Papéis declaram autoridade; gates declaram veredito.
- **Never commit modified binaries** - `objects/*.json` files are source of truth and must not be edited without updating corresponding artifacts
- **Slot A only** - This project is configured for single-slot flash only; install sequence in `INSTALL-SEQUENCE.md` assumes Slot A
- **Pinned actions only** - All GitHub Actions must use full 40-character SHA hashes; no `@vN` tags
- **GPL-2.0 compliance** - Modified kernel sources must be published alongside binaries

## Repository Structure
```
AGENT.md          # Contrato normativo do agente (processo, não modelo)
agent/            # Papéis, habilidades, workflows, prompts — a forma executável
objects/          # JSON source of truth (install-stack, build plans, artifacts)
kernel/           # Kernel source, patches, config fragments
scripts/          # Gates (stack_gate, kernel_build_gate, ao_gate, workflow_audit)
.github/workflows/  # GitHub Actions CI/CD (release-only, fail-closed)
```

## Security
- No secrets in repository - all build secrets provided via GitHub Actions secrets
- Kernel SU-Next + SUSFS provides root; integrity via PIFork + TEESimulator
