# Nothing Phone 2 Kernel + ROM CI/CD

Custom kernel and ROM build infrastructure for Nothing Phone 2 (codename: pong).

## Project Overview

This repository provides the CI/CD infrastructure for building and validating:

- **Kernel**: LineageOS kernel (sm8475) with KernelSU-Next, SUSFS, and custom patches
- **ROM**: Evolution X 11.11 (Android 16 / API 36) with GApps integration

## Build Environment

- **OS**: Ubuntu (ubuntu-latest)
- **Toolchain**: clang-r530567 (Android 14/15), DDK ghcr.io/ylarod/ddk-min:android13-5.10-2025-04
- **Kernel Source**: LineageOS `lineage-23.2` branch (`android13-5.10` KMI)
- **GKI**: Yes, with vendor-specific configuration fragments

## Usage

```bash
# Clone the repository
git clone https://github.com/your-org/nothing-phone2-kernel-rom-cicd.git
cd nothing-phone2-kernel-rom-cicd

# Run the stack gate to validate all invariants
python3 scripts/stack_gate.py

# Validate kernel build plan structure
python3 scripts/kernel_build_gate.py

# Or use GitHub Actions
gh workflow run lint.yml
```

## Governance

### Code Owners

All changes require review from the designated code owners:

- `@mechanical-coder` - Primary maintainer
- `@android-architect` - Architecture review
- `@security-reviewer` - Security validation

### Pull Request Requirements

1. All PRs must pass CI validation
2. At least one code owner approval required
3. All 16 stack invariants must pass validation
4. YAML workflow files must pass lint
5. Kernel pin SHAs must be verified in source repos

### CI/CD Pipeline

```
objects/          -> stack_gate.py validates invariants
scripts/          -> Build and validation scripts
.github/workflows/ -> Automated CI/CD pipelines
kernel/           -> Kernel source and patches
```

## Object Definitions

- `objects/install-stack.json` - Complete installation plan with all layers, phases, and constraints
- `objects/kernel-build-plan.json` - Kernel build requirements and toolchain configuration
- `objects/rom-artifacts.json` - ROM variant artifacts (vanilla, GApps)
- `objects/kernel-candidates.json` - Available kernel candidates for building

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | Invariant violation detected |
| 3 | Missing input files (PENDENTE) |
