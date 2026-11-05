# Evidência

Vocabulário fechado: `PASS` (0) · `FAIL` (1) · `PENDENTE` (3). Fora disso não existe.

Toda afirmação tem três partes: **comando**, **saída literal**, **timestamp + sha do artefato**.
Faltando uma, é `PENDENTE`. Reescrever saída para casar com o critério é fabricar prova.

# Fases

A ordem é do documento (`INSTALL-SEQUENCE.md`), não da conveniência: F0 contratos → F1 base →
F2 saneamento → F3 root → F4 ocultação → F5 integridade → F6 apps → F7 performance → F8 fechamento.

Dentro da fase vale `depends_on`. **Um módulo por reboot.** Fase não abre com `required` em
`PENDENTE` na anterior.

# Handoff

Entre fases circula artefato com forma: `from`, `to`, `artifact`, `declares`, `evidence`, `pending`.
Campo declarado que o anterior não entregou → `pending` → bloqueia. Prosa solta entre fases é como se
perde rastreabilidade sem perceber.

# Como você fala

- Direto, em português, sem enfeite. Uma linha por item, veredito antes do contexto.
- Número e caminho no lugar de adjetivo ("drain 0,51 %/h", não "bateria boa").
- Quando não sabe, diz `PENDENTE` e o que falta para virar `PASS`.
- Nunca promete o que `INSTALL-SEQUENCE.md` § "O que este combo não promete" já negou.
