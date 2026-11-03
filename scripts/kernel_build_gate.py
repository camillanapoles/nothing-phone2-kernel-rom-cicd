#!/usr/bin/env python3
"""
Kernel Build Gate Validator - Validates kernel-build-plan.json requirements
Schema: evox-kernel-build-plan/1
Exit codes: 0=PASS, 1=FAIL, 3=PENDENTE (missing input)
"""

import json
import sys
import os
from pathlib import Path

def load_json(path):
    """Load and parse JSON file."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[FAIL] Failed to load {path}: {e}")
        return None

def validate_schema(data):
    """Validate schema field matches expected."""
    if data.get("schema") != "evox-kernel-build-plan/1":
        print(f"[FAIL] schema: expected 'evox-kernel-build-plan/1', got '{data.get('schema')}'")
        return False
    print("[PASS] schema: evox-kernel-build-plan/1")
    return True

def validate_target(data):
    """Validate target device, soc, android version."""
    target = data.get("target", {})
    required_keys = ["device", "model", "soc", "android", "kernel_base", "gki"]
    for key in required_keys:
        if key not in target:
            print(f"[FAIL] target missing required key: {key}")
            return False
    print(f"[PASS] target: {target.get('model')} ({target.get('soc')}) Android {target.get('android')}")
    return True

def validate_source(data):
    """Validate kernel source configuration."""
    source = data.get("source", {})
    required_keys = ["id", "url", "branch", "pin", "license_check"]
    for key in required_keys:
        if key not in source:
            print(f"[FAIL] source missing required key: {key}")
            return False
    pin = source.get("pin", "")
    if not pin or len(pin) != 40:
        print(f"[FAIL] source.pin: expected 40-char commit SHA, got '{pin}'")
        return False
    print(f"[PASS] source: {source.get('id')} @ {pin[:14]}...")
    return True

def validate_toolchain(data):
    """Validate build toolchain configuration."""
    toolchain = data.get("toolchain", {})
    if not toolchain.get("image"):
        print("[FAIL] toolchain missing image")
        return False
    print(f"[PASS] toolchain: {toolchain.get('image')}")
    return True

def validate_build(data):
    """Validate build configuration."""
    build = data.get("build", {})
    if not build.get("defconfig"):
        print("[FAIL] build missing defconfig")
        return False
    # Check patch_set (list of patches with IDs) - fallback to patches field for compatibility
    patch_source = build.get("patch_set", build.get("patches", []))
    patch_ids = [p.get("id") for p in patch_source]
    required_patches = ["001-kabi-sysvipc", "002-mqueue-padding"]
    # Also check module_specific configs for KSU and SUSFS
    configs = data.get("configs", {})
    module_specific = configs.get("module_specific", [])
    has_ksu = any(m.get("config") == "CONFIG_KSU" for m in module_specific)
    has_susfs = any(m.get("config") == "CONFIG_SUSFS" for m in module_specific)
    # Check required patches from patch_set
    for patch in required_patches:
        if patch not in patch_ids:
            print(f"[FAIL] build missing required patch: {patch}")
            return False
    # Verify KSU and SUSFS are configured via module_specific
    if not has_ksu:
        print("[FAIL] build missing CONFIG_KSU in module_specific")
        return False
    if not has_susfs:
        print("[FAIL] build missing CONFIG_SUSFS in module_specific")
        return False
    print(f"[PASS] build: {build.get('defconfig')} with {len(patch_ids)} patches + KSU/SUSFS configs")
    return True

def validate_configs(data):
    """Validate kernel configuration contract and modules."""
    configs = data.get("configs", {})
    contract = configs.get("contract", [])
    module_specific = configs.get("module_specific", [])

    if len(contract) < 10:
        print(f"[FAIL] configs.contract: expected at least 10 configs, got {len(contract)}")
        return False

    # Required contract configs (base GKI configs)
    required_contract = ["CONFIG_SYSVIPC", "CONFIG_USER_NS", "CONFIG_PID_NS", "CONFIG_IPC_NS", "CONFIG_NET_NS"]
    for cfg in required_contract:
        if cfg not in contract:
            print(f"[FAIL] configs.contract missing required: {cfg}")
            return False

    # Required module-specific configs (KSU, SUSFS, etc.)
    required_modules = ["CONFIG_KSU", "CONFIG_SUSFS"]
    module_ids = {m.get("config"): m for m in module_specific}
    for cfg in required_modules:
        if cfg not in module_ids:
            print(f"[FAIL] configs.module_specific missing required: {cfg}")
            return False

    print(f"[PASS] configs: {len(contract)} contract configs + {len(module_specific)} module configs")
    return True

def validate_requirements(data):
    """Validate functional and non-functional requirements."""
    reqs = data.get("requirements", {})
    functional = reqs.get("functional", [])
    non_functional = reqs.get("non_functional", [])
    if len(functional) < 5:
        print(f"[FAIL] requirements.functional: expected at least 5, got {len(functional)}")
        return False
    if len(non_functional) < 5:
        print(f"[FAIL] requirements.non_functional: expected at least 5, got {len(non_functional)}")
        return False
    print(f"[PASS] requirements: {len(functional)} functional, {len(non_functional)} non-functional")
    return True

def validate_actions(data):
    """Validate GitHub Actions are properly pinned."""
    actions = data.get("actions", [])
    for action in actions:
        sha = action.get("sha", "")
        name = action.get("use", "")
        if not sha or len(sha) != 40:
            print(f"[FAIL] actions: {name} has invalid SHA: '{sha}'")
            return False
    print(f"[PASS] actions: {len(actions)} actions with valid SHAs")
    return True

def validate_artifacts(data):
    """Validate output artifacts specification."""
    artifacts = data.get("artifacts", [])
    required = ["Image", "boot.img", "SHA256SUMS"]
    for art in required:
        found = any(a.get("name") == art for a in artifacts)
        if not found:
            print(f"[FAIL] artifacts missing: {art}")
            return False
    print(f"[PASS] artifacts: {len(artifacts)} artifacts including required outputs")
    return True

def validate_deploy(data):
    """Validate deployment steps."""
    deploy = data.get("deploy", {})
    if not deploy.get("steps"):
        print("[FAIL] deploy missing steps")
        return False
    print(f"[PASS] deploy: {len(deploy.get('steps', []))} deployment steps")
    return True

def validate_validation(data):
    """Validate validation requirements."""
    validations = data.get("validation", [])
    if len(validations) < 10:
        print(f"[FAIL] validation: expected at least 10 validation steps, got {len(validations)}")
        return False
    print(f"[PASS] validation: {len(validations)} module validation steps")
    return True

def validate_risks(data):
    """Validate risk register."""
    risks = data.get("risks", [])
    if len(risks) < 3:
        print(f"[FAIL] risks: expected at least 3 risks, got {len(risks)}")
        return False
    print(f"[PASS] risks: {len(risks)} risks with mitigations")
    return True

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "--config":
        print("Usage: python3 kernel_build_gate.py --config <path/to/kernel-build-plan.json>")
        return 3

    config_path = sys.argv[2]
    if not os.path.exists(config_path):
        print(f"[PENDENTE] Config file not found: {config_path}")
        return 3

    data = load_json(config_path)
    if data is None:
        return 1

    validators = [
        validate_schema,
        validate_target,
        validate_source,
        validate_toolchain,
        validate_build,
        validate_configs,
        validate_requirements,
        validate_actions,
        validate_artifacts,
        validate_deploy,
        validate_validation,
        validate_risks,
    ]

    print(f"Running {len(validators)} kernel build checks...")
    all_pass = True
    for validator in validators:
        if not validator(data):
            all_pass = False

    if all_pass:
        print("\n[SUMMARY] KERNEL BUILD PLAN VALID ✓")
        return 0
    else:
        print("\n[SUMMARY] KERNEL BUILD PLAN INVALID ✗")
        return 1

if __name__ == "__main__":
    sys.exit(main())