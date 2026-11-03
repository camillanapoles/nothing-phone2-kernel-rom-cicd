# Combo final e sequência de instalação — Pong (Nothing Phone 2) · A16

> **Fonte única:** `skills/evox-rom-ci-optimizer/references/install-stack.json`.
> Este documento é a leitura humana do mesmo contrato; quem cobra é `make stack`
> (`scripts/stack_gate.py`), que confere **16 invariantes** e amarra os pins estrangeiros ao
> `kernel-build-plan.json`, ao `rom-artifacts.json` e ao contrato do DroidSpaces.
> Se este texto divergir do JSON, **o JSON vence** e o gate reprova a divergência de pin.
>
> **Regra de execução:** um módulo por reboot, PASS antes do próximo (`rollout_gate.sh`).
> **Regra de prova:** todo passo tem critério falseável; insumo ausente é **PENDENTE (exit 3)**,
> nunca "verde".

## Decisões registradas (2026-11-02, `decided_by: user`)

| Chave | Valor | Por quê |
|---|---|---|
| `flavor` | **vanilla** | GApps da ROM traz Chrome/Velvet/Wellbeing privilegiados no `/system`; debloat systemless volta na OTA |
| `gapps` | **nikgapps-core** (5 componentes) | GmsCore + Phonesky + GSF + sync de contatos e calendário. Nada além |
| `integrity_engine` | **teesimulator-rs-enhanced** | substitui o TrickyStore (fechado, sem keybox válida embutida) |
| `keybox_automation` | **teesimulator-enhanced** (alternativa: specter) | um só dono da automação; nunca dois |
| `screen_search` | **circletosearch @ e4f4614** | tem motor de disparo próprio (pílula inferior) e OCR offline; tradução só neste ramo |
| `hiding` | **susfs + ksu app-profile + zygisk-next** | kernel-level primeiro; Shamiko e Zygisk Assistant fora |

## Combo (21 camadas)

| Camada | Pin | Papel | Status |
|---|---|---|---|
| `firmware-pong` | `pkg:nothingos-b4.0-251119-1654` | base do rádio/câmera do pin do kernel | required |
| `evox-vanilla` | `build:EvolutionX-16.0-20260915-Pong-11.11` | ROM A16 sem Google | required |
| `nikgapps-core` | `pkg:nikgapps-core-arm64-16` | os 5 componentes do Google | required |
| `webview-aosp` | `pkg:aosp-webview` | sem Chrome, o WebView é o AOSP | required |
| `kernel-build-e03` | `commit:4ec5491f…` | kernel com KSU-Next + SUSFS + namespaces | required |
| `ksu-next` | `tag:v3.4.2` | root em kernel (LKM) | required |
| `susfs-userspace` | `tag:v1.5.2+_R28` | `ksu_susfs`: casa com o patch do kernel | required |
| `ksu-app-profile` | `pkg:ksu-next-app-profile` | *Umount modules* por app | required |
| `zygisk-next` | `tag:v1.5.2` | Zygisk em `just_umount` + `linker builtin` + memória anônima | required |
| `pifork` | `tag:v16` | props/fingerprint (BASIC) | required |
| `teesimulator-rs` | `tag:v6.0.1-360-enhanced` | engine de atestação (DEVICE) | required |
| `keybox` | `pkg:keybox-xml` | raiz de confiança; revogável | required |
| `vbmeta-fixer` | `pkg:vbmeta-fixer` | depois do PIFork e do motor | required |
| `nohello` | `tag:v0.0.8` | só se a matriz de detecção falhar | conditional |
| `hma-oss` | `tag:hma-oss` | só se algum app enumerar pacotes | optional |
| `gemini` | `pkg:…apps.bard` | pedido da usuária | required |
| `drive` | `pkg:…apps.docs` | opcional; sem ele não há backup de dispositivo | optional |
| `circletosearch` | `commit:e4f4614…` | seleção de texto + tradução por gesto | required |
| `morphe` | `tag:v2.3.0` | YouTube patcheado + detach | required |
| `gms-doze` | `tag:1.9.11` | Play Services dormindo, FCM intacto | required |

**Vetados com justificativa no JSON:** shamiko · zygisk-assistant · yurikey · integrity-box ·
tricky-store · mindthegapps · microg · chrome · velvet · wellbeing.

---

## F0 · Contratos e cesta (nada no aparelho)

| # | Ação | PASS |
|---|---|---|
| 0.1 | E03: árvore pinada + build do kernel | 7 artefatos + sha256 conferido |
| 0.2 | baixar firmware B4.0-251119-1654 | versão e hash registrados |
| 0.3 | baixar ROM vanilla + NikGapps Core | hash das duas variantes conferido |
| 0.4 | baixar 6 zips de módulo + 4 APKs | todo item com versão pinada e sha256 |
| 0.5 | backup do `boot.img` stock + ADB/fastboot | `fastboot devices` responde + `.sha256` |
| 0.6 | gates do repo verdes | `make -s prove` e `make -s arch` = 0 |

## F1 · Base do sistema (mesma sessão de recovery)

| # | Ação | PASS |
|---|---|---|
| 1.1 | flash do firmware nos dois slots | base atualizada no About |
| 1.2 | **format data** (não dirty flash) | storage limpo |
| 1.3 | flash da ROM vanilla | About mostra 11.11 |
| 1.4 | flash do NikGapps Core **sem reboot no meio** | Play Store presente e excluídos ausentes |
| 1.5 | reboot | primeiro boot sem loop |

## F2 · Saneamento do primeiro boot

| # | Ação | PASS |
|---|---|---|
| 2.1 | setup **sem restaurar backup** | nenhum app restaurado |
| 2.2 | auto-update do Play **off** | toggle desligado |
| 2.3 | auto-sync e scan do Play Protect **off** | ambos off |
| 2.4 | conferir WebView AOSP | `dumpsys webviewupdate` com provider válido |
| 2.5 | congelar OTA até o fim do ciclo | updater sem download em fila |

## F3 · Root

| # | Ação | PASS |
|---|---|---|
| 3.1 | flash do `boot.img` com KSU-Next LKM | `su -c id` = uid 0 |
| 3.2 | instalar manager do KSU-Next | manager concede root |
| 3.3 | backup do boot já com root | arquivo e hash guardados |

## F4 · Ocultação de Root (um por reboot)

| # | Ação | PASS |
|---|---|---|
| 4.1 | `susfs4ksu` R28 | `ksu_susfs show version` = patch do kernel |
| 4.2 | SUSFS: logs off, spoof de uname, make it sus | sem "susfs not found" |
| 4.3 | KSU-Next: **Umount modules** por app alvo | toggle ativo por app |
| 4.4 | Zygisk Next + `just_umount` + `linker builtin` + `memory-type anonymous` | os três aplicados sem reboot |
| 4.5 | NoHello **condicional** | só se 4.6 falhar; nunca junto com Shamiko |
| 4.6 | matriz de detecção (Ruru/Duck Detector + 2 apps reais) | sem root, sem zygisk, sem mount inconsistency, sem sus path |
| 4.7 | HMA-OSS **opcional** | só se algum app enumerar pacotes |

> Por que SUSFS primeiro: o unmount por app esconde **os módulos**; o SUSFS esconde
> **paths, mounts, kstat e uname** no kernel. Sem ele, apps que varrem o kernel continuam
> detectando — e o custo é ~zero (sem daemon).

## F5 · Integridade (um por reboot)

| # | Ação | PASS |
|---|---|---|
| 5.1 | PlayIntegrityFork | BASIC verde |
| 5.2 | TEESimulator-RS Enhanced | engine carregada, `keystore2` interceptado |
| 5.3 | `keybox.xml` não revogada | status não revogado — **revogada = PENDENTE exit 3** |
| 5.4 | `target.txt` com `com.android.vending` + apps de One/Workspace | apps listados |
| 5.5 | `security_patch` dentro de 12 meses | data coerente |
| 5.6 | VBMeta Fixer (depois de 5.1 e 5.2) | boot sem erro de vbmeta |
| 5.7 | checker de integridade | DEVICE verde (STRONG só se necessário) |
| 5.8 | app real de One/Workspace | abre e autentica |

## F6 · Apps

| # | App | PASS |
|---|---|---|
| 6.1 | Gemini | loga e responde |
| 6.2 | Drive (se mantido) | sync de um arquivo ok |
| 6.3 | CircleToSearch @ `e4f4614` | os 7 critérios (abaixo) |
| 6.4 | Morphe v2.3.0 + YouTube patcheado + detach | sem ads e update do Play não sobrescreve |

**Critérios do CircleToSearch:** funciona **sem GMS** · pílula responde ao long-press ·
**não engole o swipe-up** para home · role de assistente concedido sem app Google ·
cópia de texto **com rede desligada** · **tradução presente no commit pinado** (se não → PENDENTE) ·
nenhuma notificação persistente.

## F7 · Performance e bateria

| # | Ação | PASS |
|---|---|---|
| 7.1 | Universal GMS Doze 1.9.11 | GMS otimizável e FCM intacto |
| 7.2 | restringir background de Drive/Gemini; Find My Device off | apps restritos sem perder notificação |
| 7.3 | baseline de idle noturno e RAM | drain alvo e OTP chegando |

## F8 · Fechamento por tópico

| # | Tópico | PASS |
|---|---|---|
| 8.1 | Sistema | chrome/velvet/wellbeing ausentes |
| 8.2 | Ocultação | SUSFS ativo + matriz de detecção limpa |
| 8.3 | Integridade | BASIC + DEVICE verdes; STRONG documentado |
| 8.4 | Apps | Gemini, Drive (se mantido), YouTube patcheado e busca por gesto |
| 8.5 | Notificações | só canais escolhidos ativos |
| 8.6 | Backup e OTA | backup funciona **ou** está declarado como limitação; `addon.d` preserva GApps |

---

## O que este combo **não** promete

- `DEVICE` permanente: keybox pública é material vazado e compartilhado; a revogação é questão de
  tempo. O desenho correto é **falhar visível** (PENDENTE exit 3) e re-buscar, não fingir verde.
- `STRONG` sem custo: existe com keybox + patch recente, mas é o nível mais frágil.
- Ocultação "perfeita": sempre há superfície de detecção. O que é demonstrável é o conjunto de
  apps testados com resultado PASS — e é isso que a matriz de 4.6 mede.
- Kernel do E03 que compile de primeira: se os patches kABI do DroidSpaces colidirem com o SUSFS,
  a build declara o fallback em vez de esconder o conflito.
