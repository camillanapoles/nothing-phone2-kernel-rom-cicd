# Pong: investigação da falha depois de `LTO vmlinux.o`

Data: 2026-11-05. Escopo: checkout `7486feda`, workflow único, contratos JSON,
fontes pinadas e referências externas abaixo. **Diagnóstico parcial confirmado;
correção do kernel ainda não comprovada.** Nenhum build ARM64 completo, flash,
teste físico ou publicação foi executado nesta investigação.

## 1. Acontecimento verificado, não inferido pela última linha

As APIs de jobs e de annotations estão acessíveis. O download dos logs completos
redirecionou para hosts de armazenamento fora do acesso de rede deste ambiente
(`EOF`). Não foi possível ler os artefatos `.cmd` da execução anterior.

| Execução | Job kernel | Resultado observado |
|---|---|---|
| [41957107483](https://github.com/camillanapoles/nothing-phone2-kernel-rom-cicd/actions/runs/41957107483) / main | 127015184934 | `undefined symbol: __stack_chk_guard`, referências a `init/main.c` |
| [41958208028](https://github.com/camillanapoles/nothing-phone2-kernel-rom-cicd/actions/runs/41958208028) / PR #5 | 127018242798 | mesmo símbolo e mesmas referências |

Anotações de ambos os jobs:

```text
CONFIG_CC_HAVE_STACKPROTECTOR_SYSREG=y
CONFIG_STACKPROTECTOR_PER_TASK=y
CONFIG_HAVE_STACKPROTECTOR=y
CONFIG_STACKPROTECTOR=y
CONFIG_STACKPROTECTOR_STRONG=y
CONFIG_LTO_CLANG=y
CONFIG_LTO_CLANG_FULL=y
ld.lld: error: undefined symbol: __stack_chk_guard
>>> referenced by main.c:248 (../init/main.c:248)
>>> referenced by main.c:256 (../init/main.c:256)
>>> referenced by main.c:0 (../init/main.c:0)
```

O último job passou pelo preflight de swap e falhou na action de build. Os jobs
de collection/governance passaram; repack, SUSFS LKM e reproducibilidade não
rodaram. O período entre início do job kernel e conclusão global foi cerca de
28 minutos, inferior ao timeout de 95 minutos da action. Não há evidência
nessas anotações de OOM ou timeout; há evidência positiva de erro de símbolo.
Não se deve extrapolar isso para todas as execuções históricas.

A sugestão da action de baixar Clang para 12/10 é uma classificação heurística,
não um diagnóstico demonstrado. Não justifica violar o pin r530567.

## 2. Correlação com as últimas linhas fornecidas

1. `CC drivers/kernelsu/...` e `AR drivers/kernelsu/built-in.a` mostram que a
   compilação desses objetos e seu arquivamento avançaram. Não provam resolução
   dos símbolos, funcionamento dos hooks ou SUSFS no aparelho.
2. `AR drivers/built-in.a` encerra o agregado de drivers. A proximidade textual
   de KernelSU não o transforma automaticamente em causador.
3. No fonte pinado, `scripts/link-vmlinux.sh`, função `modpost_link`, imprime
   `LTO vmlinux.o` antes de executar `${LD} ${KBUILD_LDFLAGS} -r ...`. É a
   transição para processamento/ligação global de bitcode, não uma mensagem de
   erro. Depois há modpost e outras ligações do vmlinux. Sem log completo não
   se afirma em qual dessas invocações o símbolo foi rejeitado.
4. Em `arch/arm64/kernel/process.c:62–66`, `__stack_chk_guard` só é definido
   quando STACKPROTECTOR está ativo **e PER_TASK está desativado**.
5. Em `arch/arm64/Makefile:59–67`, PER_TASK acrescenta às flags de compilação:
   `-mstack-protector-guard=sysreg`, `-mstack-protector-guard-reg=sp_el0` e
   offset extraído de `TSK_STACK_CANARY` em `include/generated/asm-offsets.h`.
6. Em `arch/arm64/include/asm/stackprotector.h`, o canário é inicializado em
   `current->stack_canary`; a escrita na variável global também é condicional.
7. As linhas 248/256 de `init/main.c` pertencem a `loglevel`, que usa variável
   local cujo endereço passa a `get_option`. É compatível com instrumentação
   do stack protector, mas só o objeto/IR confirma a origem da referência.

**Conclusão sustentada:** há uma referência ao modelo global de canário num
build configurado para canário por tarefa. **Ainda não se sabe** se vem de
flags efetivas ausentes, bitcode/atributos incompatíveis na otimização,
objeto/cache indevido ou outro comportamento da toolchain. Não adicionar uma
variável global fictícia: isso poderia esconder uma violação de hardening.

## 3. Estudo das referências e aplicação ao projeto

### dabao1955/kernel_build_action

Revisão efetivamente usada: `c61fc39e72624a641caf23b71660aa4de2bff036`.
Inspecionados `action.yml`, `src/index.ts`, `builder.ts`, `cache.ts` e fluxo de
configuração/empacotamento.

- `builder.ts` já divide internamente a configuração em defconfig, merge com
  `merge_config.sh -m`, olddefconfig, depois `make ... all`. Não é correto
  dizer que o workflow atual não faz merge nem substituí-lo por outro solver.
- Propaga ambiente LLVM e seleciona Clang/GCC, cross prefixes e ccache.
  O comando principal usa `-j` baseado em `os.cpus().length`, não literalmente
  `nproc`; em runners com restrição de afinidade esses valores podem divergir.
- O build grava `out/build.log`; os arquivos `.cmd` são evidência mais direta
  das flags reais que as opções declaradas no workflow.
- O cache restaura por prefixo do nome do defconfig; nosso defconfig contém
  fingerprint de inputs. A receita e o novo coletor entram na identidade.
- O post-action exige preservar evidência **antes** da limpeza. O workflow já
  salvava `.config` e log, mas não salvava comando de `init/main.o`, comando de
  `process.o` ou offsets de canário. Essa era uma lacuna concreta.

Fonte: https://github.com/dabao1955/kernel_build_action/tree/c61fc39e72624a641caf23b71660aa4de2bff036

### XiaoleGun/KernelSU_Action — referência principal

Revisão consultada: `26c1b95532549d4cb57ab152f5650003d89c6efb`.
Inspecionados README_EN, workflow, config, build, toolchain e integração/patches.

- É build integrado ao source via `make`, não um substituto DDK para o kernel
  completo. Isso se correlaciona com nosso KernelSU embutido; nosso SUSFS LKM
  separado deve continuar sendo construído contra o output exato desse kernel.
- Separa resolução/validação de config, fonte, toolchain, patches, defconfig,
  compile, check e package. Essa separação é útil para diagnóstico; trocar de
  action inteira não corrige, por si só, `__stack_chk_guard`.
- Tem 8 GiB de swap para LTO. Nosso último job já passou por equivalente:
  repetir swap como “fix” ignora a evidência do linker.
- Permite desativar LTO e mudar toolchain. São opções genéricas, não autorização
  para mudar nosso contrato FullLTO/CFI/r530567.
- Alerta para tarball de Clang válido porém vazio e valida refs antes do setup,
  evitando fallback silencioso. Nosso build chegou a compilar milhares de
  objetos; “Clang ausente” não explica esta falha. Validar versão/binários
  antecipadamente ainda é melhoria útil, não causa comprovada.
- O mapeamento automático SUSFS para 5.10 escolhe android12-5.10; nosso KMI é
  **android13-5.10**. Não copiar o default nem confundir Android 16 da ROM com
  geração KMI do kernel. Também não copiar o exemplo android15-6.6.
- KPM é específico de variante; não inventar CONFIG_KPM no Next v3.4.2. Hooks
  variam por versão; a política auto de um wrapper não prova o mecanismo do
  commit Next pinado. Não aplicar patches legados por proximidade do log.
- SUSFS kernel-side + KSU-side é outra arquitetura que o SUSFS LKM deste
  projeto. Não reaplicar `10_enable_susfs_for_ksu.patch` incompatível para
  resolver um símbolo de canário em `init/main.c`.

Fonte: https://github.com/XiaoleGun/KernelSU_Action/tree/26c1b95532549d4cb57ab152f5650003d89c6efb

### awesome-android-root

Revisão consultada: `96e773aaca7d07d625c0f2c1a74e72080706cdff`.
Inspecionados índice, guia Nothing e troubleshooting de kernel/root/módulos.
É catálogo/guia operacional, não evidência de flags do linker do nosso build.

- Reforça compatibilidade firmware/kernel/KMI, backup da imagem exata e
  recuperação da partição realmente alterada. Correlaciona-se com collection,
  rollback boot e repack local, não com adicionar símbolos no kernel.
- `su` oculto de um app não prova ausência de root; detecção/Play Integrity e
  root funcional são testes diferentes. Manter M01/M07/M08 independentes.
- Recomendações genéricas de Magisk/Nothing OS não substituem o contrato
  EvoX/Next. Não misturar frameworks no mesmo slot nem automatizar flash.
- O guia tem afirmações abrangentes sobre modelos; devem ser confirmadas por
  firmware/dispositivo real, não usadas como prova de suporte universal.

Fonte: https://github.com/awesome-android-root/awesome-android-root/tree/96e773aaca7d07d625c0f2c1a74e72080706cdff

## 4. Pendências prévias e decisão sobre o fix

Ordem de investigação necessária:

1. Obter `out/init/.main.o.cmd`, `out/arch/arm64/kernel/.process.o.cmd`,
   `.config` e `TSK_STACK_CANARY`. O novo coletor preserva isso automaticamente.
2. Comparar o comando real com as três flags sysreg e conferir o offset.
   Se ausentes/incorretas: corrigir propagação/ordem de Kbuild, com patch mínimo
   revisado; não desativar o stack protector.
3. Se presentes: usar **o llvm-dis da toolchain pinada** em `out/init/main.o`
   (quando bitcode), examinar flags/atributos de guard e referências; reproduzir
   numa unidade mínima + LTO antes de afirmar bug do Clang. Verificar quais
   símbolos indefinidos são introduzidos em `vmlinux.o` com llvm-nm.
4. Recompilar limpo, sem ccache, para distinguir bitcode/cache de configuração.
   Alterações de toolchain/receita precisam invalidar identidade e output.
5. Só então escolher patch de compatibilidade ou propor revisão formal do pin.
   Clang 10/12, ThinLTO, `STACKPROTECTOR=n` e definição artificial do símbolo
   **não são fixes aprovados**. Preservar CFI e proteção por tarefa.
6. Validar kernel completo, módulos e SUSFS LKM, repack e comparação binária;
   depois testes físicos. Um link verde não prova segurança do canário.

Outras lacunas observadas, fora da correção imediata:

- `make all` faz gates estruturais, não build. O stack gate explicitamente
  executa apenas 4 checks básicos e lista 16 invariantes declaradas. Não
  anunciar “16 invariantes verificadas”.
- README ainda menciona `lint.yml` inexistente, patches ausentes apesar de
  presentes e implementação de workflow pendente apesar de existente.
- `SHA256SUMS` também contém comentário obsoleto de patches não incluídos.
- O gate descreve DDK/patches canônicos enquanto a execução usa Marketplace e
  SUSFS LKM. Essa divergência documental exige reconciliação governada; os
  `objects/*.json` não foram alterados diretamente.
- Reprodutibilidade, M01–M15, soak de 72 h e desempenho continuam pendentes;
  jobs de staging que calculam PENDING podem passar sem certificar dispositivo.

## 5. Mudanças desta investigação e validação

- Coletor Python com allowlist de textos pequenos; não salva objetos/binários,
  não altera source/output e explicita arquivos ausentes. Preserva comandos,
  configs, offsets e erros para primeiro build e rebuild.
- Coleta ligada ao step de diagnóstico `always()`, antes do post-action.
- Rebuild independente dividido em olddefconfig → prepare → `V=1 init/main.o`
  → all → comparação existente. **O primeiro build permanece na action pinada;
  o rebuild só será alcançado depois de corrigir o primeiro build.** Os nomes
  dos steps não devem sugerir que essa divisão já isolou a falha primária.
- Fingerprint inclui o coletor. Contratos JSON, pins, hardening e política
  release-only preservados.
- Testes locais: unittest do coletor, gates estruturais e `git diff --check`.
  Esses resultados não são prova de correção do erro de link.
