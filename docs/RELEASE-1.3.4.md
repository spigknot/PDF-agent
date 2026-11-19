# PDFagent 1.3.4

Correção de interface no verificador de atualizações.

## O que mudou

- **“verificando…” não fica mais preso na tela.** Ao clicar em *Verificar
  atualizações*, o rótulo só era limpo quando havia uma atualização para
  oferecer — se o app já estava na versão nova (ou se o check falhava), o
  `update_fim` apenas religava o flag interno e o texto ficava para sempre.
  Agora existe um ponto único de limpeza (`_limpa_verificando()`), chamado no
  `update_fim` **e antes** de abrir o diálogo de aviso — o texto sai no instante
  da resposta, não depois do modal fechar.

- Regressão travada por `tests/test_updater_ui.py` (3 casos: aviso, `update_fim`
  e a oferta preservada) e por uma checagem nova no gate:
  `updater (rótulo do check)`.

## Instalador

- A elevação automática agora repassa a linha de comando original
  (`GetCmdTail`): antes, a instância elevada perdia `/DIR`, `/TASKS` e
  `/VERYSILENT`. Não muda nada no fluxo normal (duplo clique), mas permite
  instalação dirigida sem quebrar os parâmetros.

## Desempenho medido (documento de estresse, 376 páginas, 34,1 MB)

| nível | PDFagent | iLovePDF (referência) | razão | texto ≠ original | render (pior página) |
|---|---|---|---|---|---|
| recommended | **11.382.226 B** | 12.227.010 B | **93,09%** | 0/3 | 8,67% |
| extreme | **8.646.929 B** | 9.275.878 B | **93,22%** | 3/3¹ | 16,35% |
| low | **14.884.111 B** | 16.565.289 B | **89,85%** | 0/3 | 1,74% |

¹ bug conhecido do extrator (GID 304 do Calibri e NBSP) — não é diferença de
conteúdo. Ver `docs/METODO.md` §5.

Saída do gate (`py -3.11 scripts/verificar.py`):

```
[OK] testes de nivel (3 niveis)
[OK] CLI falha com exit code != 0               rc=1
[OK] CLI: subcomandos + retrocompatibilidade
[OK] launcher .bat (sintaxe e caminho)
[OK] consolidacao de objetos (ToUnicode)
[OK] coleta de fontes (pool x serial)
[OK] DPI efetivo (pacote x serial)
[OK] executavel (freeze_support / onefile)
[OK] progresso (janela única / console oculta)
[OK] updater (rótulo do check)
[OK] paridade no documento de estresse          0/3 combinacoes com problema
[OK] paridade estrutural vs iLovePDF            0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. `PDFagent-Setup-1.3.4.exe` — instala em `C:\Program Files\PDFagent` (UAC uma
   vez; a pasta fica gravável para o atualizador aplicar diffs sem novo UAC).
2. Portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos).
3. Quem já tem instalado recebe por **diff** (botão verde) ou pelo
   `PDFagentUpdater.exe`.

## SHA-256

Ver `SHA256SUMS-1.3.4.txt` no anexo da release.

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 (sem codificador open-source no
projeto), subsetter CFF próprio, `ClipImages` de paths curvos. Dividir em
limites muito pequenos (1–2 MB) num arquivo grande gera muitas partes e é
lento: cada parte re-serializa os recursos compartilhados.
