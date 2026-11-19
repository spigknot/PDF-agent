# PDFagent 1.3.3

Compressor de PDF com os 3 níveis do iLovePDF (Extreme / Recommended / Low).

**Para quem vem da 1.3.1, esta é a versão com a interface nova do menu de
contexto.** A 1.3.2 já a trouxe; a 1.3.3 republica o pacote pelo procedimento
completo do `UPDATE.md` (gate → smoke → harness do updater → R2 → release) e
serve de ponto de atualização para quem está na 1.3.1 ou anterior.

## O que mudou (desde a 1.3.1)

- **Fim das janelinhas de prompt**: o `.exe` é `--windowed` e, vindo do
  Explorer, cada worker de `multiprocessing` abria um `conhost` próprio — 22
  janelas medidas. `compress._console_oculta()` aloca uma console escondida no
  start e os filhos a herdam: **22 → 0** janelas visíveis.
- **Um único diálogo com progresso e cronômetro**: barra que avança pelas fases
  `[1]`…`[6]`, cronômetro `m:ss,d` congelado no fim e resultado na mesma
  janela (bytes, %, tempo) — em comprimir **e** dividir.
- **Dividir pergunta antes**: limite em MB (1 casa, **1,7** já preenchido, piso
  **1,0**, teto 2.000; aceita `1,5` e `1.5`) e caixa **“Comprimir” desmarcada**;
  marcada, aparecem `low` / `recommended` / `extreme`. O app não comprime mais
  sozinho.
- **Erro não morre mais em silêncio**: `sys.excepthook` grava
  `%TEMP%\pdfagent_erro.log` (com argv + traceback) e mostra um diálogo.

## Desempenho medido (documento de estresse, 376 páginas, 34,1 MB)

| nível | PDFagent | iLovePDF (referência) | razão | texto ≠ original | render (pior página) |
|---|---|---|---|---|---|
| recommended | **11.382.226 B** | 12.227.010 B | **93,09%** | 0/3 | 8,67% |
| extreme | **8.646.929 B** | 9.275.878 B | **93,22%** | 3/3¹ | 16,35% |
| low | **14.884.111 B** | 16.565.289 B | **89,85%** | 0/3 | 1,74% |

¹ as 3 páginas do extreme são o bug conhecido do extrator (GID 304 do Calibri e
NBSP), não diferença de conteúdo — ver `docs/METODO.md` §5.

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
[OK] paridade no documento de estresse          0/3 combinacoes com problema
[OK] paridade estrutural vs iLovePDF            0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. `PDFagent-Setup-1.3.3.exe` — instala em `C:\Program Files\PDFagent` (pede
   admin uma vez; o diretório fica gravável para o atualizador aplicar diffs
   sem novo UAC). Opções já marcadas: PATH e “PDFagent” no menu de contexto.
2. Portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos).
3. Quem já tem instalado recebe a atualização por **diff** pelo próprio app
   (botão verde) ou pelo `PDFagentUpdater.exe`.

## SHA-256

Ver `SHA256SUMS-1.3.3.txt` no anexo da release.

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 (sem codificador open-source no
projeto), subsetter CFF próprio e `ClipImages` de paths curvos. Dividir em
limites muito pequenos (1–2 MB) num arquivo grande gera muitas partes e é
lento: cada parte re-serializa os recursos compartilhados.
