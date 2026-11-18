# PDFagent 1.2.1

Correção do **updater** — o app em si não muda (mesmo compressor da 1.2.0).

## O que corrige

- **Abrir o `PDFagentUpdater.exe` direto (duplo clique) não dá mais traceback.**
  O executável é `--windowed`, então `sys.stdout`/`sys.stderr` vêm `None` e o
  `argparse` estourava em `'NoneType' object has no attribute 'write'` ao
  imprimir o uso. Agora:
  - o updater tenta **anexar ao console do processo pai** (quem chama de um
    terminal vê a mensagem normalmente);
  - sem console, os fluxos vão para `os.devnull` — nunca ficam `None`;
  - **sem argumentos**, mostra uma caixa explicando o uso (o caminho normal é o
    botão "Atualizar" dentro do app) em vez de despejar erro.

Nada muda no fluxo normal: o app continua chamando o updater com
`--sync-staged/--removals/--target/--pid/--log`, e o reparo com `--full`/`--zip`.

## Desempenho (inalterado — mesmo compressor)

| métrica | valor |
|---|---|
| corpus (7 PDFs × 3 níveis) | **3.998.227 B** contra 4.203.565 do iLovePDF (**−4,88%**), 21/21 menores, **0/21** diferenças estruturais |
| documento de estresse (Recommended) | **11.382.226 B** (93,09% da referência) |
| tempo | 62,1 s no CLI · 65,4 s no `.exe` instalado |
| texto / render vs original | 0/376 páginas · 0,313% médio, pior 8,67% (pg218) |

## Como atualizar

Quem já tem a 1.2.0 (ou 1.1.0) **não precisa fazer nada**: abra o app, o botão
verde aparece e a atualização baixa só os 3 arquivos que mudaram
(`PDFagent.exe`, `PDFagentUpdater.exe`, `_internal/base_library.zip`) — o
updater antigo aplica a troca com rollback e o app reabre na 1.2.1.

Primeira instalação ou reparo: `PDFagent-Setup-1.2.1.exe` ou
`PDFagentUpdater.exe --full --target "%LOCALAPPDATA%\Programs\PDFagent" --log updater.log`.

## SHA-256

```
5d743373815561e5c5e17ac1c6377518102c07efcb420b24b7148f4917526a5d  PDFagent-Setup-1.2.1.exe
963e2f2557b53b1b63341616569bad145f129d79c8fdf518a3dfa66452a4a387  PDFagent.exe
9fd2d53523d1657df8c0363e0be139578363d4d1fc9487147a84d587ac159ec1  PDFagent-onedir-1.2.1.zip
288fd57f3ec4d4352c1eb64c8251f1c1402c1811d0554c2e818d59fe825b7492  PDFagentUpdater.exe
```

## Limitações conhecidas

- O nível **Extreme** extrai texto diferente do original em 3 das 376 páginas do
  documento de estresse (acento/espaço) — está no teto do gate.
- Diff de versão de código custa ~11 MB (o PYZ do PyInstaller vive dentro do
  `PDFagent.exe`).
- O portátil onefile roda em série (sem pools de processo) e não se atualiza por
  diff: use o instalador.
