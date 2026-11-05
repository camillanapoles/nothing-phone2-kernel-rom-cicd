---
schema: pong-agent-skill/1
name: artifact-integrity
description: Identify an artifact by hash, attest it, verify it before publishing, and never repackage after attestation.
applies_to: [rom-integrator, pipeline-engineer, evidence-auditor, release-steward]
---

# Artifact integrity

## Regra

Um artefato é **o hash**, não o nome do arquivo. Nome de arquivo é rótulo; hash é identidade.

```
collect  → sha256 canônico confere contra objects/rom-artifacts.json
build    → artifacts + .config + SOURCE.tar.gz
attest   → attest-build-provenance, uma vez, sobre o conjunto final
verify   → gh attestation verify <arquivo> --repo <owner/repo>
publish  → SHA256SUMS + draft RC (nunca stable)
```

## Procedimento

1. Mirror (Drive, espelho, cache) é conveniência. Se o sha256 diverge, **falha a coleta**; não existe
   "baixar de novo e seguir".
2. `SHA256SUMS` é gerado do diretório final e conferido com `sha256sum -c` **antes** do upload.
3. Atestação vem depois do último byte mudar. Repack depois de atestar invalida a prova — e reempacotar
   "para arrumar um detalhe" é o erro que mais aparece em release amador.
4. Release tem limite: cada asset < 2 GiB e no máximo 1000 assets. Acima disso, storage externo
   verificado, não "comprime mais".
5. Nada de binário modificado no repositório (`INV-08`): objeto JSON é fonte, `img`/`zip` são saída.

## Anti-padrões

- Confiar em MD5 de metadados de terceiro.
- Publicar `boot.img` sem `SHA256SUMS` na mesma release.
- Atestar o zip e publicar os arquivos extraídos sem hash.
- Artefato grande em GitHub Release (>2 GiB) "porque o upload aceitou".
