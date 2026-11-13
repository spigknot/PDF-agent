# UPDATE.md — Procedimento de release (PDFagent / PDF-agent)

> **FONTE DA VERDADE** para gerar e publicar uma versão do PDFagent.
> Siga a ordem. Cada passo tem o comando literal, a verificação e os pitfalls já
> vividos neste projeto. Se um passo falhar, **pare** e resolva pela seção
> "Pitfalls" — não invente caminho alternativo.

---

## 0. Visão geral do fluxo

```
bump (2 lugares) → gate → build do .exe → build do instalador → smoke test
→ SHA-256 → commit + push → release no GitHub (metadados, depois assets) → verificação
```

- **Canal de distribuição**: **GitHub Releases** (`spigknot/PDF-agent`). Não há
  updater nem R2 — o usuário baixa o instalador e pronto.
- **Assets da release**: `PDFagent-Setup-<versao>.exe` (instalador, canal
  principal) e `PDFagent.exe` (portátil, sem instalação). Mais nada.
- **`dist/` e `build/` nunca vão para o git** (ver `.gitignore`): binário só
  existe na release.

## 0.1 Contexto essencial

- **Repositório**: `D:\Projetos\PDF-agent` (GitHub: `spigknot/PDF-agent`, privado).
- **Python do build**: `C:\Users\Gustavo\AppData\Local\Programs\Python\Python311\python.exe`
  (3.11 + PyInstaller 6.21 + pikepdf/Pillow/fontTools/PyMuPDF).
- **Inno Setup**: `C:\Users\Gustavo\AppData\Local\Programs\Inno Setup 6\ISCC.exe`
  (6.7.3, instalado per-usuário).
- **Terminal**: bash/MSYS. Para passar argumentos com `/` a programas Windows
  (ex.: `/VERYSILENT`) use `MSYS2_ARG_CONV_EXCL='*'` — sem isso o MSYS come as
  barras e as tarefas do instalador **não são aplicadas**.

## 0.2 Regras obrigatórias (não negociáveis)

1. **Nunca gerar release sem pedido explícito** do usuário.
2. A versão DEVE ser a mesma em **dois** lugares: `compress.py` (`VERSAO`) e
   `instalador/PDFagent.iss` (`#define Versao`). Divergência = release errada.
3. O **gate tem de passar com `0/21`** (tolerância zero de diferença
   estrutural) antes de empacotar. Qualquer `FAIL` impede a release.
4. **Nunca commitar** `dist/`, `build/`, `*.spec` gerado, `dist/*.exe`.
5. **Nunca deletar releases anteriores** — o histórico é o changelog.
6. Subir **somente** os dois assets previstos (instalador + exe portátil).
7. Não inventar número: todo dado do release (tamanho, % vs iLovePDF, PSNR) sai
   da execução real do gate/bateria.
8. Ao terminar, atualize este documento se algo divergiu (seção 8).

## 1. Pré-requisitos

```bash
cd /d/Projetos/PDF-agent
"$LOCALAPPDATA/Programs/Python/Python311/python.exe" -c "import PyInstaller, pikepdf, fitz, PIL, fontTools; print('deps ok', PyInstaller.__version__)"
ls "/c/Users/Gustavo/AppData/Local/Programs/Inno Setup 6/ISCC.exe"
gh auth status | head -3          # conta: spigknot, escopo repo
git status --short                # deve estar vazio (árvore limpa)
```

- Corpus de paridade em `C:\Users\Gustavo\Desktop\REA-lab` precisa existir (o
  gate pula a paridade se não existir, mas release sem paridade **não** vale).
- A instalação local do app (`%LOCALAPPDATA%\Programs\PDFagent`) é sobrescrita
  pelo instalador durante o smoke test — normal.

## 2. Bump da versão (dois lugares)

```bash
# 1) compress.py
VERSAO = "1.0.1"            # <-- nova versão (semver)

# 2) instalador/PDFagent.iss
#define Versao "1.0.1"      # <-- MESMA string
```

Conferir:

```bash
grep -n 'VERSAO =' compress.py
grep -n '#define Versao' instalador/PDFagent.iss
```

> Dívida conhecida: a versão está duplicada. Se um dia unificar, que seja num
> arquivo lido pelos dois (ex.: `version.txt`) — e atualize esta seção.

## 3. Gate (obrigatório, antes de empacotar)

```bash
"$LOCALAPPDATA/Programs/Python/Python311/python.exe" -u scripts/verificar.py
```

Saída esperada (as quatro linhas `[OK]`):

```
[OK] testes de nivel (3 niveis)
[OK] CLI falha com exit code != 0
[OK] launcher .bat (sintaxe e caminho)
[OK] paridade estrutural vs iLovePDF        0/21 com diferenca
PASS — tudo dentro do esperado
```

- Roda ~4 min (recomprime 21 PDFs). Se estourar o tempo do terminal, rode em
  background com `notify_on_complete` e leia o log.
- `FAIL` em qualquer item: **não** empacote.

## 4. Build do executável e do instalador

```bash
"$LOCALAPPDATA/Programs/Python/Python311/python.exe" scripts/build_exe.py
# → dist/PDFagent/        onedir, com _internal (é o que o instalador leva; start ~0,3 s)
# → dist/PDFagent.exe     portátil onefile (start ~2,6 s)
# → dist/PDFagent/*.cmd   shims por subcomando (gerar_shims.py)

"/c/Users/Gustavo/AppData/Local/Programs/Inno Setup 6/ISCC.exe" instalador/PDFagent.iss
# → dist/PDFagent-Setup-<versao>.exe (~44 MB)
```

**Smoke test (obrigatório — não confie no build):**

```bash
./dist/PDFagent/PDFagent.exe --version                 # onedir
./dist/PDFagent.exe --version                          # onefile portátil
./dist/PDFagent/PDFagent.exe compress arquivo.pdf -n low
cmd /c "dist\\PDFagent\\pdfcompress.cmd arquivo.pdf -n low"   # shim
T="$LOCALAPPDATA/Temp/rel"; rm -rf "$T"; mkdir -p "$T"
cp "C:/Users/Gustavo/Desktop/REA-lab/x/x.pdf" "$T/r.pdf"
./dist/PDFagent/PDFagent.exe --in-place -n recommended "$T/r.pdf"   # linha do menu
ls "$T"                                                # r.pdf (menor) + r_old.pdf
```

Instalador (testa tarefas PATH + menu de contexto):

```bash
MSYS2_ARG_CONV_EXCL='*' ./dist/PDFagent-Setup-<versao>.exe /VERYSILENT /SUPPRESSMSGBOXES \
  /NORESTART /TASKS="addpath,contextmenu"
sleep 5
powershell -NoProfile -Command "Test-Path 'HKCU:\Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent'"
"$LOCALAPPDATA/Programs/PDFagent/PDFagent.exe" --version
```

## 5. SHA-256 dos artefatos

```bash
cd /d/Projetos/PDF-agent/dist
sha256sum PDFagent.exe PDFagent-Setup-<versao>.exe | tee SHA256SUMS-<versao>.txt
```

Guarde os hashes: entram nas notas da release e servem para conferir o download.

## 6. Commit e push (antes da release)

```bash
cd /d/Projetos/PDF-agent
git status --short          # deve mostrar só código/docs, nunca dist/
git add -A
git commit -m "Release <versao>: <resumo em uma linha>"
git push
git log --oneline -1
```

> A tag da release é criada a partir do `origin/main` **já com este commit**.
> Se a release sair antes do push, ela aponta para o commit anterior.

## 7. Release no GitHub

Crie **primeiro só os metadados**; depois suba cada asset em um comando próprio
(se a janela morrer no meio, evita release parcial):

```bash
cd /d/Projetos/PDF-agent/dist
# notas: copie docs/RELEASE-TEMPLATE.md para docs/RELEASE-<versao>.md e preencha
gh release create v<versao> --repo spigknot/PDF-agent \
  --title "PDFagent <versao>" \
  --notes-file ../docs/RELEASE-<versao>.md

gh release upload v<versao> ./PDFagent-Setup-<versao>.exe --repo spigknot/PDF-agent
gh release upload v<versao> ./PDFagent.exe --repo spigknot/PDF-agent
gh release upload v<versao> ./SHA256SUMS-<versao>.txt --repo spigknot/PDF-agent
```

Notas da release (mínimo): o que mudou, tabela de desempenho medida (21/21,
% vs iLovePDF, PSNR/render) e limitações conhecidas (ver `docs/METODO.md` §4b).

**Verificação final (obrigatória):**

```bash
gh release view v<versao> --repo spigknot/PDF-agent --json tagName,url,assets \
  --jq '{tag:.tagName, url:.url, assets:[.assets[]|{name, size}]}'
```

Deve listar exatamente os três assets. Depois, baixe e confira o hash:

```bash
T="$LOCALAPPDATA/Temp/dl"; rm -rf "$T"; mkdir -p "$T"
gh release download v<versao> --repo spigknot/PDF-agent --dir "$T"
sha256sum -c "$T/SHA256SUMS-<versao>.txt" --ignore-missing
```

## 8. Entrega e manutenção

Relatório final ao usuário: versão, tag, URL da release, tamanho dos assets,
SHA-256, saída do gate (4× `[OK]` + `PASS`) e o resultado do smoke test.
Se algum passo deste documento divergiu do real, **corrija aqui** na mesma
rodada.

## Pitfalls já vividos (não repetir)

| sintoma | causa | resolução |
|---|---|---|
| exe com vários GB / build eterno | `--collect-all pymupdf` arrasta `pymupdf.features/layout` → **torch + onnxruntime** | o `scripts/build_exe.py` já exclui `torch`, `onnxruntime`, `pymupdf.features`, `pymupdf.layout`; não remova essas linhas |
| exe com ~120 MB | `--collect-all pymupdf` copia `pymupdf/layout/resources/onnx` (**41 MB de modelos**) e `mupdf-devel`; `sympy`/`pygments`/`_pytest`/`PIL._avif` vinham no grafo | `build_exe.py` usa `--collect-binaries pymupdf` + `--collect-submodules pymupdf` e exclui `sympy`, `mpmath`, `pygments`, `_pytest`, `pytest`, `IPython`, `PIL._avif` → **58,6 MB** (medido: mesma saída byte a byte)|
| instalador silencioso não cria PATH nem menu | MSYS converteu `/VERYSILENT`/`/TASKS` em caminho | rodar com `MSYS2_ARG_CONV_EXCL='*'` |
| `[FALHA] launcher .bat` no gate | o `.bat` passou a lançar `dist\PDFagent.exe`; a GUI herda os pipes e o subprocess espera EOF | o teste já neutraliza os **dois** launches; se voltar, ver `teste_launcher()` |
| `gh release create` com tag no commit errado | release criada antes do push | sempre seção 6 antes da 7; se preciso: `git push origin +<SHA>:refs/tags/v<versao>` |
| release com asset faltando | upload interrompido | `gh release upload` do asset faltante; nunca recriar a release |
| `PDFagent.exe --version` não imprime nada | exe `--windowed` sem console | o app anexa o console do pai (`AttachConsole`); se falhar, rode a partir de um terminal real, não de um launcher que descarta stdio |
| arquivo comprimido maior que o original | garantia "nunca maior" copia o original | não é bug; o app reporta 0% e mantém os bytes |
| `dist/` aparece no `git status` | `.gitignore` alterado | restaurar as entradas `dist/`, `build/`, `*.spec` |

## Checklist rápido (copiar no topo do PR/release)

- [ ] `VERSAO` == `#define Versao`
- [ ] `scripts/verificar.py` → PASS, `0/21`
- [ ] `dist/PDFagent.exe` gerado e `--version` correto
- [ ] `dist/PDFagent-Setup-<v>.exe` gerado, instala e cria PATH + menu
- [ ] smoke `--in-place` deixou `<nome>_old.pdf`
- [ ] `SHA256SUMS-<v>.txt` gerado
- [ ] commit + push feitos **antes** da release
- [ ] release com 3 assets e `gh release view` conferido
- [ ] download + `sha256sum -c` conferido
