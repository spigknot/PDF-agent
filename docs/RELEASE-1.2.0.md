# PDFagent 1.2.0

**Atualizações dentro do app.** Esta versão embute o `PDFagentUpdater.exe`: o
PDFagent passa a verificar sozinho se há versão nova, mostra um botão verde
"Atualizar" e baixa **só os arquivos que mudaram** — com manifesto assinado,
validação de hash e rollback automático se o app novo não subir.

## O que mudou

- **Verificação automática ao abrir** (e no botão "Verificar atualizações" quando
  o usuário quer conferir na hora).
- **Botão verde "Atualizar para X.Y.Z"** aparece quando existe versão nova, com
  o número de arquivos a baixar.
- **Diff por arquivo via Cloudflare R2**: o app compara o manifesto publicado
  (`sync_manifest.json`, schema 2) com a instalação, baixa apenas o que mudou
  para `%TEMP%\pdfagent_update\<versao>\staged`, confere o SHA-256 de cada
  arquivo e entrega ao updater.
- **Updater transacional** (`PDFagentUpdater.exe`): espera o app fechar, move os
  arquivos com backup e journal, valida a estrutura, reinicia o app e **desfaz
  tudo** se o app novo não permanecer em execução.
- **Manifesto assinado** (RSA-4096, PKCS#1 v1.5/SHA-256). Chave pública embutida
  no app e no updater; a privada nunca sai da máquina de publicação.
- **Pacote completo para reparo** (`PDFagent-onedir-<versao>.zip`), aplicável por
  `PDFagentUpdater.exe --full` ou `--zip <arquivo>` quando o diff não serve.
- `PDFAGENT_PROC_OFF=1` desliga todos os pools de processo (diagnóstico).

## Desempenho (inalterado em relação à 1.1.0 — mesmo compressor)

### Corpus de paridade (7 PDFs reais × 3 níveis = 21 saídas)

| métrica | PDFagent 1.2.0 | iLovePDF |
|---|---|---|
| tamanho total | **3.998.227 B** | 4.203.565 B (**−4,88%**) |
| menor em | **21 / 21** arquivos | 0 |
| diferença estrutural | **0 / 21** | — |

### Documento de estresse (`processo.pdf`, 376 páginas)

| nível | PDFagent | iLovePDF | |
|---|---|---|---|
| Recommended | **11.382.226 B** | 12.227.010 B | 93,09% |
| Extreme | 8.651.585 B | 9.275.878 B | 93,27% |
| Low | 14.884.111 B | 16.565.289 B | 89,85% |

- **Texto**: 0/376 páginas diferentes do original (Extreme: 3/376, teto do gate).
- **Render contra o original**: 0,313% médio, pior caso 8,67% (pg218) — o
  iLovePDF fica em 12,76% na mesma página.
- **Tempo** (Recommended): 62,1 s no CLI e 65,4 s no `.exe` instalado.

## Instalação e atualização

1. **Primeira instalação**: baixe `PDFagent-Setup-1.2.0.exe` e execute
   (per-usuário, não pede admin). A partir daí o app se atualiza sozinho.
2. **Atualizar pelo app**: abra o PDFagent — se houver versão nova, o botão verde
   aparece no topo; clique e aguarde o app reabrir atualizado.
3. **Reparo**: baixe `PDFagent-onedir-<versao>.zip` e rode
   `PDFagentUpdater.exe --full --target "%LOCALAPPDATA%\Programs\PDFagent" --log updater.log`.
4. **Portátil** (`PDFagent.exe` onefile): funciona, mas **não** se atualiza por
   diff — use o instalador.

O log da atualização fica em `%LOCALAPPDATA%\Programs\PDFagent\updater.log`.

## SHA-256

```
8b74752515a55aa844330b1d094f12b04d014a75c381ab47499afff57c5a5254  PDFagent-Setup-1.2.0.exe
ba4b8de5663c5034023c254cc804b3a3db493e3086ddb3bb8f2aa135ea8664f7  PDFagent.exe
32668b2e5dc86452f7c96860f1e3d19d86fe33e29ddeafcae7755ad17f7a6836  PDFagent-onedir-1.2.0.zip
```

## Limitações conhecidas

- O nível **Extreme** extrai texto diferente do original em 3 das 376 páginas do
  documento de estresse (acento/espaço) — está no teto do gate.
- **Diff de versão de código custa ~11 MB**: o `PDFagent.exe` carrega o PYZ do
  PyInstaller, então qualquer mudança de código reescreve o exe inteiro. Ainda
  assim é bem menos que os ~54 MB do instalador.
- O manifesto publicado no R2 deve sempre conter `PDFagentUpdater.exe`; uma
  versão publicada sem ele deixaria os clientes sem como se atualizar.
- O portátil onefile roda em série (sem pools de processo) por decisão de
  projeto: no onefile cada worker reextrairia o bundle.
