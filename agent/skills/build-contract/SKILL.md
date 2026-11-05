---
schema: pong-agent-skill/1
name: build-contract
description: Kernel build shape is a contract — tree pin, patch order, config merge and toolchain. Deviate only by written decision.
applies_to: [kernel-architect, pipeline-engineer]
---

# Build contract

## Regra

O build do kernel é **um contrato fechado**, não uma receita ajustável. Qualquer desvio é decisão
registrada no objeto, não improviso no comando.

```
tree pin    : LineageOS/android_kernel_nothing_sm8475 @ 4ec5491f…   (lineage-23.2 / android13-5.10)
patch order : 001 kABI sysvipc → 002 mqueue padding → KernelSU-Next v3.4.2 → SUSFS 2.3.0-gki LKM
config      : gki_defconfig + vendor/waipio_GKI + vendor/nothing/waipio_GKI + vendor/debugfs + evox_pong_pack
toolchain   : clang-r530567 (android13-5.10), LLVM=1 LLVM_IAS=1
artifacts   : Image, boot.img, dtbo.img, AnyKernel3 zip, .config, SOURCE.tar.gz, SHA256SUMS
```

## Por que a ordem não é negociável

Os patches kABI do DroidSpaces mudam a superfície que o módulo SUSFS e o KernelSU-Next enxergam.
Aplicar o patch de SUSFS antes produz um build que **compila e falha em runtime** — o pior tipo de
falha, porque o build verde esconde o defeito (`INV-06`).

## Procedimento

1. Leia o plano em `objects/kernel-build-plan.json`; não reconstrua de memória.
2. `on_reject: fail_build` → falhou, falhou. `--fuzz`/`--force` está proibido, não é estilo.
3. Fallback kABI só em bootloop, um por vez, com o sintoma registrado.
4. Compile com o toolchain pinado; publique `.config` e `SOURCE.tar.gz` junto do `Image` (GPL).
5. Duas builds do mesmo pin devem produzir o mesmo `Image` — se não, `SOURCE_DATE_EPOCH`, `KBUILD_*`
   e versão de `ccache` entram no relatório antes de qualquer release.

## Anti-padrões

- "Compilou, então o patch aplicou certo."
- Fragmento vendor editado para caber no GKI (some a compatibilidade, aparece o bootloop).
- Trocar clang para "resolver" erro de ABI.
- Publicar `boot.img` sem o `.config` que o gerou.
