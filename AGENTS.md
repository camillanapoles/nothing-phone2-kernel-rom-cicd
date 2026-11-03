# Agent Instructions for Nothing Phone 2 Kernel/ROM CI/CD

## Agent Roles & Responsibilities

### mechanical-coder
- Primary maintainer of CI/CD workflows and validation scripts
- Implements `scripts/stack_gate.py` and `scripts/kernel_build_gate.py`
- Manages `.github/workflows/` linting and deployment

### android-architect  
- Kernel build configuration (`kernel/configs/`, `kernel/patches/`, `kernel/fragments/`)
- LineageOS source integration (`lineage-23.2` branch)
- Toolchain: clang-r530567 (Android 13 5.10)
- KernelSU-Next v3.4.2 + SUSFS R28 integration

### security-reviewer
- Reviews all kernel patches for security implications
- Validates PIFork + TEESimulator-RS integrity chain
- Ensures no secrets leaked in CI artifacts

## Workflow Patterns
- **Never edit `objects/*.json` directly** - these are canonical source of truth
- All schema changes must update corresponding validation scripts
- CI runs on every PR; merge requires passing `stack-governance` + `kernel-build` checks
- Single-slot (Slot A) flash sequence - no dual-slot support needed