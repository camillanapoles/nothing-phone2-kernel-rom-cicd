# INITIAL PLAN

 Goal: Create CI/CD pipeline for Nothing Phone 2 kernel/ROM builds with GitHub Actions and multi-agent orchestration. Plan created with 3 orchestration steps. Next: run Step 1 /orchestrate command to initialize repo governance. Summary

  I've created a comprehensive CI/CD DevOps plan for the Nothing Phone (2) "pong" custom kernel and Evolution X ROM build. Here's what was delivered:

  Plan File Created

  /home/cnmfs/.claude/plans/usando-habilidades-github-ops-uma-glowing-bonbon.md

  ```markdown
  # Plan: CI/CD DevOps Pipeline & Multi-Agent Orchestration for Nothing Phone (2) "pong" Kernel & Evolution X ROM
  
  ## Context
  
  The objective is to establish a automated, production-grade GitHub Actions CI/CD pipeline and governance framework for building a custom Android 16 (Evolution X 11.11) ROM and custom Linux Kernel (LineageOS base `lineage-23.2` with KernelSU-Next v3.4.2, SUSFS, and DroidSpaces kABI patches) for the Nothing Phone (2) (codename `pong`, Qualcomm Snapdragon 8+ Gen 1 `SM8475`).
  
  The implementation follows the exact object specifications from `@objects/`:
  - `install-stack.json`: 21-layer stack, 16 invariants enforced via `scripts/stack_gate.py`.
  - `kernel-build-plan.json`: LineageOS kernel tree commit `4ec5491f6b5f...`, clang-r530567 toolchain, patches `001-kabi-sysvipc`, `002-mqueue-padding`, embedded KernelSU-Next, and SUSFS.
  - `rom-artifacts.json`: Evolution X 11.11 Vanilla (`26be9ac8bb21...`) and GApps (`79236f9b4259...`) builds.
  - `kernel-candidates.json`: Fixture certification validation.
  - `INSTALL-SEQUENCE.md`: Installation procedure, **adjusted for single-slot (Slot A only)** as requested.
  
  ---
  
  ## 1. Repository Structure & Tree Specification
  
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
  
  ## 2. GitHub Governance & Continuity Rules
  
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
  
  ## 3. CI/CD GitHub Actions Workflows
  
  ### 3.1 Kernel Build Workflow (`.github/workflows/kernel-build.yml`)
  Uses `actions/checkout@3d3c42e5...` and `actions/cache@55cc8345...` for ccache persistence, with matrix strategy validating kernel candidates and applying patches reproducibly.
  
  - **Trigger**: Push to `main`, PRs touching `kernel/` or `objects/`, `workflow_dispatch`.
  - **Steps**:
    1. Checkout kernel source (`LineageOS/android_kernel_nothing_sm8475` @ `4ec5491f6b5f...`).
    2. Setup Clang (`clang-r530567` / Android 13 5.10 toolchain).
    3. Apply DroidSpaces kABI patches (`001`, `002`), integrate KernelSU-Next v3.4.2, and apply SUSFS.
    4. Run build using `gki_defconfig` + `evox_pong_pack.config`.
    5. Package `boot.img`, `dtbo.img`, and AnyKernel3 zip.
    6. Attest build provenance & upload release draft.
  
  ### 3.2 Stack Governance Workflow (`.github/workflows/stack-governance.yml`)
  - **Trigger**: Every PR and push.
  - **Steps**:
    1. Execute `python3 scripts/stack_gate.py` to verify the 16 stack invariants.
    2. Validate JSON schemas for `install-stack.json` and `kernel-build-plan.json`.
    3. Verify pinned commit SHAs against GitHub APIs.
  
  ---
  
  ## 4. Single-Slot (Slot A) Installation Adaptation (`INSTALL-SEQUENCE.md`)
  
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
  
  ## 5. Multi-Agent Orchestration Plan (`/orchestrate` Commands)
  
  The orchestration uses the `plan-orchestrate` skill chain pattern with direct agent delegation:
  
  ```bash
  # Step 1: Repository & Governance Setup
  /orchestrate custom "planner,architect,security-reviewer" "[Plan: plans/usando-habilidades-github-ops-uma-glowing-bonbon.md#step-1] Initialize GitHub repo nothing-phone2-kernel-rom-cicd with CODEOWNERS, branch protection rules, and stack_gate.py governance script; Acceptance: stack_gate.py passes 16 invariants; GitHub Actions lint clean; Out of scope: actual compilation"
  
  # Step 2: Kernel Build Workflow Implementation
  /orchestrate custom "tdd-guide,cpp-build-resolver,code-reviewer" "[Plan: plans/usando-habilidades-github-ops-uma-glowing-bonbon.md#step-2] Implement .github/workflows/kernel-build.yml using pinned actions and LineageOS sm8475 tree with KSU-Next and SUSFS; Acceptance: workflow syntax valid; patch application dry-run passes; SHA256 checksums generated; Out of scope: ROM full build"
  
  # Step 3: ROM Artifact & Delivery Pipeline
  /orchestrate custom "tdd-guide,doc-updater,code-reviewer" "[Plan: plans/usando-habilidades-github-ops-uma-glowing-bonbon.md#step-3] Configure rom-build.yml and Single-Slot (Slot A) INSTALL-SEQUENCE.md documentation; Acceptance: Slot A flash steps fully documented; release provenance attestation integrated; Out of scope: dirty flashing"
  ```
  
  ---
  
  ## 6. Verification & Validation Steps
  
  1. **Local Schema & Invariant Check**:
     ```bash
     python3 scripts/stack_gate.py --config objects/install-stack.json
     ```
  2. **GitHub Workflow Verification**:
     ```bash
     gh workflow run kernel-build.yml --ref main
     gh run view --log-failed
     ```
  3. **Artifact Integrity Check**:
     - Confirm generated `SHA256SUMS` match output binaries.
     - Verify `boot.img` size does not exceed stock partition size + 5% (NFR-08).
  
  ---
  
  ## A. JSON Schema References
  
  ### `install-stack.json` (excerpt)
  ```json
  {
    "schema": "evox-install-stack/1",
    "decisions": { "flavor": { "value": "vanilla", "rationale": "..." } },
    "forbidden": [{ "id": "shamiko", "why": "..." }],
    "layers": [{ "id": "kernel-build-e03", "kind": "kernel", "pin": "commit:4ec5491f..." }],
    "phases": [{ "id": "F0", "title": "Contratos e cesta", "steps": [...] }],
    "invariants": ["schema", "unique_ids", "steps_have_pass", ...]
  }
  ```
  
  ### `kernel-build-plan.json` (excerpt)
  ```json
  {
    "schema": "evox-kernel-build-plan/1",
    "target": { "device": "pong", "soc": "SM8475", "android": "16", "gki": true },
    "source": { "id": "lineageos-sm8475", "branch": "lineage-23.2", "pin": "4ec5491f..." },
    "toolchain": { "image": "ghcr.io/ylarod/ddk-min:android13-5.10-2025-04", "clang": "clang-r530567" },
    "requirements": { "functional": [{ "id": "FR-01", "statement": "kernel boots" }], "non_functional": [...] }
  }
  ```
  
  ### `rom-artifacts.json` (excerpt)
  ```json
  {
    "schema": "evox-rom-artifacts/2",
    "device": "Pong", "build": "2026-09-15", "version": "11.11",
    "variants": [{ "id": "vanilla", "sha256": "26be9ac8bb21..." }, { "id": "gapps", "sha256": "79236f9b4259..." }]
  }
  ```
  ````

  Architecture Overview

  ┌────────────┬────────────────────────────────────────────────┐
  │ Component  │                 Specification                  │
  ├────────────┼────────────────────────────────────────────────┤
  │ Repository │ nothing-phone2-kernel-rom-cicd                 │
  ├────────────┼────────────────────────────────────────────────┤
  │ Kernel     │ LineageOS lineage-23.2 @ 4ec5491f6b5f...       │
  ├────────────┼────────────────────────────────────────────────┤
  │ Toolchain  │ clang-r530567 (Android 13 5.10)                │
  ├────────────┼────────────────────────────────────────────────┤
  │ Root       │ KernelSU-Next v3.4.2 + SUSFS R28               │
  ├────────────┼────────────────────────────────────────────────┤
  │ Patches    │ DroidSpaces kABI fixes (SYSVIPC, POSIX_MQUEUE) │
  ├────────────┼────────────────────────────────────────────────┤
  │ Slot Mode  │ Slot A only (per your requirement)             │
  └────────────┴────────────────────────────────────────────────┘

  Three-Step Orchestration Commands

  Step 1 (governance setup):
  /orchestrate custom "planner,architect,security-reviewer" "[Plan: plans/...#step-1] Initialize GitHub repo..."

  Step 2 (kernel workflow):
  /orchestrate custom "tdd-guide,cpp-build-resolver,code-reviewer" "[Plan: plans/...#step-2] Implement kernel-build.yml..."

  Step 3 (ROM delivery):
  /orchestrate custom "tdd-guide,doc-updater,code-reviewer" "[Plan: plans/...#step-3] Configure rom-build.yml..."

  Session State Preserved

  - Created /home/cnmfs/nothing-phone2.1/session-log.md with key decisions
  - Created /home/cnmfs/nothing-phone2.1/state.md with current task status

  Ready to execute when you are — paste the /orchestrate commands to start building the pipeline.

  ✻ Sautéed for 8m 55s · done 13:39

  ※ recap: Goal: Create CI/CD pipeline for Nothing Phone 2 kernel/ROM builds with GitHub Actions and multi-agent orchestration. Plan created with 3 orchestration steps. Next: run Step 1 /orchestrate command to initialize repo governance. (disable recaps in /config)

  ❯  Goal: Create CI/CD pipeline for Nothing Phone 2 kernel/ROM builds with GitHub Actions and multreated with 3 orchestration steps. Next: run Step 1 /orchestrate command to initialize repo
  governance.
  2 async Stop hooks completed, 6 async PostToolUse hooks completed

  I'll execute Step 1 of the orchestration plan to initialize the GitHub repository and governance
  Initializing…
  Error: InputValidationError: Agent failed due to the following issue:
  The required parameter description is missing
