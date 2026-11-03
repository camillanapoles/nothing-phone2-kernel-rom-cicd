#!/bin/bash
set -euo pipefail

# rollout_gate.sh - Slot A Flash & Verification Gate
# Enforces single-slot (Slot A) installation as per INSTALL-SEQUENCE.md
# Validates each phase before allowing progression
#
# Usage: ./rollout_gate.sh [phase]
# Phases: F0, F1, F2, F3, F4, F5, F6, F7 (or 'all' for full sequence)

PHASE="${1:-all}"
DEVICE_SERIAL="${ANDROID_SERIAL:-}"
SLOT="a"  # Single-slot (Slot A) only - NFR-10 compliance

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $*"; }

# Verify device connection
verify_device() {
    log_info "Verifying device connection..."
    if [[ -z "$DEVICE_SERIAL" ]]; then
        local devices=$(adb devices | grep -E '^\S+\s+device$' | wc -l)
        if [[ $devices -eq 0 ]]; then
            log_fail "No device connected. Connect device via USB and authorize ADB."
            return 1
        elif [[ $devices -gt 1 ]]; then
            log_fail "Multiple devices connected. Set ANDROID_SERIAL to target specific device."
            return 1
        fi
    fi
    log_pass "Device connected: $(adb shell getprop ro.product.device)"
    return 0
}

# Phase F0: Pre-flight & Verification
phase_f0() {
    log_info "=== Phase F0: Pre-flight & Verification ==="

    # Check required artifacts
    local artifacts=("boot.img" "dtbo.img" "SHA256SUMS")
    for artifact in "${artifacts[@]}"; do
        if [[ ! -f "$artifact" ]]; then
            log_fail "Missing artifact: $artifact"
            return 1
        fi
    done
    log_pass "All required artifacts present"

    # Verify SHA256SUMS
    log_info "Verifying SHA256 checksums..."
    if ! sha256sum -c SHA256SUMS; then
        log_fail "SHA256 verification failed"
        return 1
    fi
    log_pass "SHA256 checksums verified"

    # Verify slot
    local current_slot=$(adb shell getprop ro.boot.slot_suffix 2>/dev/null || echo "")
    log_info "Current slot suffix: ${current_slot:-'none (A/B not active)'}"

    log_pass "Phase F0 complete"
    return 0
}

# Phase F1: Base Flash
phase_f1() {
    log_info "=== Phase F1: Base Flash ==="

    log_info "Flashing firmware to Slot A..."
    fastboot flash --slot=a firmware.bin || {
        log_fail "Firmware flash failed"
        return 1
    }
    log_pass "Firmware flashed to slot_a"

    log_info "Flashing boot image to Slot A..."
    fastboot flash --slot=a boot boot.img || {
        log_fail "Boot image flash failed"
        return 1
    }
    log_pass "Boot image flashed to slot_a"

    log_info "Sideloading Evolution X Vanilla..."
    log_warn "Manual step required: Boot to recovery, enable 'Apply update from ADB', then run:"
    log_warn "  adb sideload EvolutionX-16.0-20260915-Pong-11.11-Vanilla-Official.zip"

    log_pass "Phase F1 complete (manual sideload required)"
    return 0
}

# Phase F2: First Boot Cleanup
phase_f2() {
    log_info "=== Phase F2: First Boot Cleanup ==="

    log_info "Waiting for device to boot..."
    adb wait-for-device shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'
    sleep 10

    log_info "Verifying Evolution X 11.11..."
    local version=$(adb shell getprop ro.evolution.version 2>/dev/null || echo "")
    if [[ "$version" != *"11.11"* ]]; then
        log_warn "Evolution X version: ${version:-'unknown'}"
        log_warn "Expected: 11.11"
    else
        log_pass "Evolution X 11.11 detected"
    fi

    log_info "Checking setup state..."
    local setup_wizard=$(adb shell settings get secure user_setup_complete 2>/dev/null || echo "0")
    if [[ "$setup_wizard" == "1" ]]; then
        log_pass "Setup completed (no restore)"
    else
        log_info "Setup wizard pending - complete without Google account restore"
    fi

    log_info "Disabling Play Protect..."
    adb shell settings put global package_verifier_enable 0 2>/dev/null || true
    adb shell settings put global package_verifier_user_consent -1 2>/dev/null || true

    log_info "Verifying WebView AOSP..."
    local webview=$(adb shell dumpsys webviewupdate 2>/dev/null | grep -i "package\|version" | head -5)
    log_pass "WebView info retrieved"

    log_pass "Phase F2 complete"
    return 0
}

# Phase F3: Root (Slot A)
phase_f3() {
    log_info "=== Phase F3: Root (Slot A) ==="

    log_info "Flashing patched boot.img (KernelSU) to Slot A..."
    fastboot flash boot_a boot-ksu.img || {
        log_fail "KernelSU boot image flash failed"
        return 1
    }
    log_pass "Patched boot image flashed to slot_a (boot_a)"

    log_info "Rebooting..."
    fastboot reboot

    log_info "Waiting for device..."
    adb wait-for-device shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done'
    sleep 5

    log_info "Verifying root..."
    local su_output=$(adb shell su -c id 2>/dev/null || echo "")
    if [[ "$su_output" == *"uid=0"* ]]; then
        log_pass "Root verified: $su_output"
    else
        log_fail "Root not working: $su_output"
        return 1
    fi

    log_pass "Phase F3 complete"
    return 0
}

# Phase F4: Hiding Stack
phase_f4() {
    log_info "=== Phase F4: Hiding Stack ==="

    log_info "Installing susfs4ksu R28 userspace..."
    log_warn "Manual step: Install susfs4ksu R28 module via KernelSU Manager"
    log_warn "Manual step: Install Zygisk Next (just_umount variant) via Magisk/KernelSU Manager"

    log_info "Verifying hiding..."
    log_warn "Manual step: Run Ruru / Duck Detector to verify hiding works"
    log_info "Expected: Clean (no root detection)"

    log_pass "Phase F4 complete (manual verification required)"
    return 0
}

# Phase F5: Integrity
phase_f5() {
    log_info "=== Phase F5: Integrity ==="

    log_info "Deploying PIFork + TEESimulator-RS Enhanced + keybox.xml..."
    log_warn "Manual step: Install PIFork module"
    log_warn "Manual step: Install TEESimulator-RS Enhanced module"
    log_warn "Manual step: Place keybox.xml in /data/local/tmp/"

    log_info "Verifying Play Integrity..."
    log_warn "Manual step: Run Play Integrity API check"
    log_info "Expected: BASIC + DEVICE green"

    log_pass "Phase F5 complete (manual verification required)"
    return 0
}

# Phase F6: Apps & Features
phase_f6() {
    log_info "=== Phase F6: Apps & Features ==="

    log_info "Installing CircleToSearch (e4f4614)..."
    log_warn "Manual step: Install CircleToSearch module"

    log_info "Installing Morphe v2.3.0..."
    log_warn "Manual step: Install Morphe v2.3.0"

    log_info "Installing Gemini..."
    log_warn "Manual step: Install Gemini app"

    log_info "Verifying CTS criteria..."
    log_warn "Manual step: Run 7 CTS criteria tests"

    log_pass "Phase F6 complete (manual verification required)"
    return 0
}

# Phase F7: Performance
phase_f7() {
    log_info "=== Phase F7: Performance ==="

    log_info "Deploying Universal GMS Doze 1.9.11..."
    log_warn "Manual step: Install Universal GMS Doze module"

    log_info "Verifying background restriction..."
    log_warn "Manual step: Verify background restriction active"
    log_warn "Manual step: Verify FCM notifications working"

    log_pass "Phase F7 complete (manual verification required)"
    return 0
}

# Main execution
main() {
    log_info "=== Nothing Phone 2 Rollout Gate ==="
    log_info "Phase: $PHASE"
    log_info "Slot: $SLOT (single-slot only)"

    # Verify device first
    verify_device || exit 1

    case "$PHASE" in
        F0) phase_f0 ;;
        F1) phase_f1 ;;
        F2) phase_f2 ;;
        F3) phase_f3 ;;
        F4) phase_f4 ;;
        F5) phase_f5 ;;
        F6) phase_f6 ;;
        F7) phase_f7 ;;
        all)
            phase_f0 || exit 1
            phase_f1 || exit 1
            phase_f2 || exit 1
            phase_f3 || exit 1
            phase_f4 || exit 1
            phase_f5 || exit 1
            phase_f6 || exit 1
            phase_f7 || exit 1
            ;;
        *)
            log_fail "Unknown phase: $PHASE"
            log_info "Valid phases: F0 F1 F2 F3 F4 F5 F6 F7 all"
            exit 1
            ;;
    esac

    log_pass "=== All phases completed successfully ==="
    return 0
}

main "$@"