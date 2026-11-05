#!/usr/bin/env python3
"""Preserve small Kbuild evidence before action post-cleanup; never modify outputs."""
import argparse
import json
from pathlib import Path
import re
import shutil


def collect(source: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    evidence = {}
    configs = {}
    commands = {}
    # Explicit allowlist: do not accidentally upload source trees or multi-GB objects.
    paths = [
        'out/.config', 'out/init/.main.o.cmd',
        'out/arch/arm64/kernel/.process.o.cmd',
        'out/include/generated/asm-offsets.h',
        'out/.vmlinux.o.cmd', 'out/.vmlinux.cmd',
        'out-repro/.config', 'out-repro/init/.main.o.cmd',
        'out-repro/arch/arm64/kernel/.process.o.cmd',
        'out-repro/include/generated/asm-offsets.h',
        'out-repro/.vmlinux.o.cmd', 'out-repro/.vmlinux.cmd',
    ]
    for relative in paths:
        path = source / relative
        if not path.is_file():
            evidence[relative] = 'missing (stage may not have run)'
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            evidence[relative] = 'omitted: exceeds 8 MiB text limit'
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        text = path.read_text(errors='replace')
        evidence[relative] = 'collected'
        if path.name == '.config':
            configs[relative] = [line for line in text.splitlines()
                                 if any(key in line for key in
                                        ('STACKPROTECTOR', 'CONFIG_LTO', 'CONFIG_CFI', 'CONFIG_CC_VERSION_TEXT'))]
        if path.name.endswith('.o.cmd'):
            # Only the compile command, not dependency filenames containing flags.
            command = next((line for line in text.splitlines() if line.startswith('cmd_')), '')
            commands[relative] = {
                'command_present': bool(command),
                'stack_flags': re.findall(r'-(?:mstack-protector-[\w-]+(?:=[^\s;]+)?|f(?:no-)?stack-protector(?:-strong|-all)?)', command),
                'lto_flags': re.findall(r'-f(?:no-)?lto(?:=[^\s;]+)?', command),
            }
    errors = []
    for output in ('out', 'out-repro'):
        log = source / output / 'build.log'
        if log.is_file():
            # Stream the log; FullLTO builds can emit very large logs.
            with log.open(errors='replace') as stream:
                for line in stream:
                    if re.search(r'undefined symbol|ld\.lld: error|out of memory|killed|LLVM ERROR', line, re.I):
                        errors.append(line.strip()[:1500])
            errors = errors[-40:]
    report = {
        'schema': 'pong-kernel-link-diagnostics/1',
        'evidence': evidence, 'configs': configs, 'compile_commands': commands,
        'errors': errors,
        'interpretation': (
            'An undefined __stack_chk_guard with PER_TASK=y is a guard-model mismatch. '
            'Inspect init/main.o flags and LLVM IR before blaming RAM or changing Clang. '
            'These diagnostics are not proof of a successful build or a root-cause fix.'
        ),
    }
    (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('kernel-source'))
    parser.add_argument('--destination', type=Path, default=Path('logs/kernel/link-evidence'))
    args = parser.parse_args()
    print(json.dumps(collect(args.source, args.destination), indent=2))
