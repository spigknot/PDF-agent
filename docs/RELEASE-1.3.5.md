# PDFagent 1.3.5

Nova Release: motor de divisão reescrito, saída organizada e identidade visual nova.

## O que mudou

- **Motor de divisão novo (`commands/split.py`)**: `pikepdf` (QPDF) com
  **busca exponencial + busca binária** em memória (`io.BytesIO`) e **uma
  escrita em disco por parte**. Sem rasterização, sem recompressão de imagens,
  fontes ou vetores (`compress_streams=False`, `recompress_flate=False`,
  `object_stream_mode=preserve`). Páginas continuam sendo unidades atômicas.
  - Caso real (`processo.pdf`, 376 páginas, 11,38 MB, limite 1,7 MB):
    **2,4 s**, 8 partes, todas dentro do limite. O motor anterior levava
    ~1:43 no mesmo tipo de cenário.
- **Saída organizada**: as partes vão para uma **subpasta com o nome do
  arquivo de entrada, sem extensão** (ex.: `Nova pasta\processo\
  processo_parte1.pdf`). Nada mais é espalhado na pasta do PDF.
- **Limite padrão do diálogo: 1,6 MB** (antes 1,7). A janela continua igual;
  o usuário ainda precisa clicar em **Dividir** para executar. A caixa
  **Comprimir** continua desmarcada por padrão.
- **Ícone novo**: página em origami com setas convergindo (compressão) e
  linha tracejada (divisão), em degradê índigo → ciano. Aplicado ao exe, ao
  updater, ao instalador e às janelas (`assets/pdfagent.ico`, gerado por
  `scripts/make_icon.py`).
- **Robustez**: `.exe --windowed` com argumento inválido não estoura mais
  `AttributeError: 'NoneType' object has no attribute 'write'` no argparse;
  a saída vai para `%TEMP%\pdfagent_saida.log`.
- **Vacina do atalho**: `tests/test_menu_contexto.py` garante a cadeia
  `menu de contexto → cli → commands.split → motor novo`.

## Desempenho medido (documento de estresse, 376 páginas, 34,1 MB)

| nível | PDFagent | iLovePDF (referência) | razão | texto ≠ original | render (pior página) |
|---|---|---|---|---|---|
| recommended | **11.382.226 B** | 12.227.010 B | **93,09%** | 0/3 | 8,67% |
| extreme | **8.646.927 B** | 9.275.878 B | **93,22%** | 3/3¹ | 16,35% |
| low | **14.884.110 B** | 16.565.289 B | **89,85%** | 0/3 | 1,74% |

¹ bug conhecido do extrator (GID 304 do Calibri e NBSP) — ver `docs/METODO.md` §5.

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
[OK] menu de contexto (atalho -> motor split)
[OK] updater (rótulo do check)
[OK] paridade no documento de estresse          0/3 combinacoes com problema
[OK] paridade estrutural vs iLovePDF            0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. `PDFagent-Setup-1.3.5.exe` — instala em `C:\Program Files\PDFagent` (UAC uma
   vez; a pasta fica gravável para o atualizador aplicar diffs sem novo UAC).
2. Portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos).
3. Quem já tem instalado recebe por **diff** (botão verde) ou pelo
   `PDFagentUpdater.exe`.

## SHA-256

Ver `SHA256SUMS-1.3.5.txt` no anexo da release.

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 (sem codificador open-source no
projeto), subsetter CFF próprio e `ClipImages` de paths curvos.
