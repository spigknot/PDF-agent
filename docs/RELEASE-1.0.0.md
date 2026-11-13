# PDFagent 1.0.0

Primeira release oficial. Compressor de PDF com os **3 níveis do iLovePDF**
(Extreme / Recommended / Low), replicados por engenharia reversa do motor
3‑Heights usado pelo iLovePDF Desktop 2.3.6, com bibliotecas open-source
(pikepdf + Pillow + fontTools + PyMuPDF).

## O que vem nesta versão

- **Compressão em 3 níveis**, com as duas garantias do projeto: **nunca maior**
  que o original (se não reduzir, o arquivo é mantido byte a byte) e **nunca
  visualmente pior** (verificação de render com refazimento automático).
- **GUI** (Tkinter) e **CLI com subcomandos**: `PDFagent compress`, `PDFagent gui`,
  `PDFagent arquivo.pdf` (atalho) e `pdfcompress` como shim no PATH.
- **Instalador per-usuário** (não pede admin) com duas opções marcadas:
  adicionar ao PATH e **"PDFagent > Comprimir"** no menu de contexto de PDFs
  (comprime em `recommended`, guarda o original como `<nome>_old.pdf`).
- **Dois formatos**: pasta `onedir` (abre em ~0,3 s) e `PDFagent.exe` portátil.

## Desempenho medido (7 PDFs reais × 3 níveis = 21 saídas)

| métrica | PDFagent | iLovePDF |
|---|---|---|
| tamanho total | **4.040.429 B** | 4.203.565 B (**−3,9%**) |
| menor em | **21 / 21** arquivos | 0 |
| render médio por página | **0,058%** | 0,135% |
| PSNR por imagem (158) | **33,22 dB** | 30,79 dB |
| SSIM médio | **0,9990** | 0,9984 |
| texto extraído / hyperlinks | idênticos ao original | — |

Gate de verificação (`python scripts/verificar.py`):

```
[OK] testes de nivel (3 niveis)
[OK] CLI falha com exit code != 0
[OK] CLI: subcomandos + retrocompatibilidade
[OK] launcher .bat (sintaxe e caminho)
[OK] paridade estrutural vs iLovePDF        0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. Baixe **`PDFagent-Setup-1.0.0.exe`** e execute (instala em
   `%LOCALAPPDATA%\Programs\PDFagent`, sem UAC).
2. Marque/desmarque as duas opções (ambas vêm marcadas): PATH e menu de contexto.
3. Alternativa portátil: **`PDFagent.exe`** — sem instalação, mas abre em ~2,6 s
   (extrai o bundle a cada execução).

## Uso

```bash
PDFagent                                   # GUI
PDFagent compress entrada.pdf -n extreme    # CLI
pdfcompress entrada.pdf -n low              # shim (se instalado)
PDFagent --version | --help
```

Menu de contexto: botão direito num PDF → **PDFagent → Comprimir**.

## SHA-256

```
6b95eabbf3be52ef4faf8eb325e459c867ed67c13fb2f1df1790d1885433984d  PDFagent.exe
6fcb3188a63e3867cb4003522e55035b24cb9c5638f0b3ec2fb5047f39f9738e  PDFagent-Setup-1.0.0.exe
```

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 sem codificador open-source no projeto
(fallback CCITT G4, sem perda), subsetter CFF próprio e `ClipImages` limitado a
paths retangulares. No `x.pdf` (fontes Type0) as saídas diferem do iLovePDF em
~15 nós de `/StructElem` e 18 bytes de filtro em imagens `1×1`.
