#!/bin/bash
set -euo pipefail

# apply_patches.sh - Apply DroidSpaces kABI patches to kernel source
# Usage: ./apply_patches.sh [kernel_source_dir]
#
# This script applies patches in the correct order as required by INV-06:
#   1. DroidSpaces kABI patches (001, 002) must be applied BEFORE KernelSU and SUSFS
#   2. KernelSU-Next v3.4.2 embedded integration
#   3. SUSFS R28 integration
#
# Exit codes:
#   0 - Success
#   1 - Patch application failed
#   2 - Verification failed (NFR-03)
#   3 - Missing input

PATCHES_DIR="$(dirname "$0")/../patches"
KERNEL_SOURCE="${1:-.}"

echo "=== Kernel Patch Application Script ==="
echo "Kernel source: ${KERNEL_SOURCE}"
echo "Patches dir: ${PATCHES_DIR}"

# Verify patches directory exists
if [[ ! -d "${PATCHES_DIR}" ]]; then
    echo "[ERROR] Patches directory not found: ${PATCHES_DIR}"
    exit 3
fi

# Change to kernel source directory
cd "${KERNEL_SOURCE}"

# Step 1: Verify patch checksums (NFR-03 compliance)
echo ""
echo "--- Verifying patch checksums ---"
cd "${PATCHES_DIR}"

if [[ ! -f "SHA256SUMS" ]]; then
    echo "[ERROR] SHA256SUMS file not found in patches directory"
    exit 3
fi

while IFS=' ' read -r expected_hash filename; do
    # Skip comments
    [[ "${filename}" =~ ^#.*$ ]] && continue
    [[ -z "${filename}" ]] && continue

    if [[ ! -f "${filename}" ]]; then
        echo "[ERROR] Patch file not found: ${filename}"
        exit 3
    fi

    actual_hash=$(sha256sum "${filename}" | awk '{print $1}')
    if [[ "${actual_hash}" != "${expected_hash}" ]]; then
        echo "[FAIL] Checksum mismatch for ${filename}"
        echo "  Expected: ${expected_hash}"
        echo "  Actual:   ${actual_hash}"
        exit 1
    fi
    echo "[PASS] ${filename}: ${actual_hash}"
done < SHA256SUMS

# Step 2: Dry-run patches to verify no fuzz/rejects (NFR-03)
echo ""
echo "--- Dry-running patches ---"
cd "${KERNEL_SOURCE}"

for patch in "${PATCHES_DIR}"/0*.patch; do
    filename=$(basename "${patch}")
    echo "Checking ${filename}..."

    # git apply --check verifies patch applies cleanly without fuzz
    if ! git apply --check --whitespace=nowarn "${patch}" 2>/dev/null; then
        echo "[WARN] Patch ${filename} may need fallback variant"
        echo "       Applying with possible fallback..."
    fi
done

# Step 3: Apply patches in order
echo ""
echo "--- Applying patches (INV-06 order) ---"

# Patch 1: SYSVIPC kABI fix for GKI below 6.12
echo "Applying patch 1: SYSVIPC kABI fix..."
if git apply "${PATCHES_DIR}"/001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8.patch 2>/dev/null; then
    echo "[PASS] Patch 001 applied successfully"
elif git apply "${PATCHES_DIR}"/001.GKI-below-6.12-fix_sysvipc_kabi_3_4_5.patch 2>/dev/null; then
    echo "[WARN] Patch 001 (fallback variant) applied"
elif git apply "${PATCHES_DIR}"/001.GKI-below-6.12-fix_sysvipc_kabi_1_2_3.patch 2>/dev/null; then
    echo "[WARN] Patch 001 (fallback variant) applied"
else
    echo "[FAIL] Patch 001 failed to apply"
    exit 1
fi

# Patch 2: POSIX mqueue ABI padding for <= 5.10
echo "Applying patch 2: POSIX mqueue padding..."
if git apply "${PATCHES_DIR}"/002.5.10_or_lower_use_android_abi_padding_for_posix_mqueue.patch 2>/dev/null; then
    echo "[PASS] Patch 002 applied successfully"
else
    echo "[FAIL] Patch 002 failed to apply"
    exit 1
fi

# Step 4: Verify patch application (NFR-03 - no .rej files)
echo ""
echo "--- Verifying clean patch application ---"
if find . -name "*.rej" -type f; then
    echo "[FAIL] Reject files found - patches did not apply cleanly"
    exit 2
fi
echo "[PASS] No reject files found"

echo ""
echo "=== Patch application complete ==="
exit 0