# PDFagent 1.3.0

**O atualizador agora tem interface gráfica**, igual à do SIG Windows: abrir o
`PDFagentUpdater.exe` (duplo clique) mostra a janela com versão instalada,
pacotes disponíveis e os botões para atualizar por diff, instalar/reparar pelo
pacote completo ou escolher um ZIP local.

## O que mudou

- **GUI do atualizador** (`StandaloneUpdaterUI`, portada do SIG Windows com a
  mesma lógica):
  - **Pasta do PDFagent** com "Escolher…";
  - **Versão instalada** (lida de `build-info.json`, gerado no build);
  - **Versão do pacote completo** (lista as releases do GitHub, com tamanho);
  - botões **Verificar**, **Atualizar** (diff), **Instalar / reparar completo**
    e **Escolher ZIP…**;
  - barra de progresso, status e console de log com timestamp;
  - fecha o app aberto antes de aplicar, aplica com transação e **reabre**,
    com rollback se o app novo não subir.
- **`build-info.json`** no pacote (`{"version": ..., "built_at": ...}`): é de
  onde o updater lê a versão instalada — sem executar o app.
- A checagem automática do **app** continua **só no boot** (decisão do usuário).

## Desempenho (inalterado — mesmo compressor)

| métrica | valor |
|---|---|
| corpus (7 PDFs × 3 níveis) | **3.998.227 B** contra 4.203.565 do iLovePDF (**−4,88%**), 21/21 menores, **0/21** diferenças estruturais |
| documento de estresse (Recommended) | **11.382.226 B** (93,09% da referência) |
| tempo | 62,1 s no CLI · 65,4 s no `.exe` instalado |
| texto / render vs original | 0/376 páginas · 0,313% médio, pior 8,67% (pg218) |

## Como atualizar

- **Pelo app**: abra o PDFagent, o botão verde aparece e baixa só o que mudou.
- **Pelo atualizador**: abra `PDFagentUpdater.exe` (na pasta do app) → **Verificar**
  → **Atualizar**. Para reparar, **Instalar / reparar completo** (baixa o
  `PDFagent-onedir-*.zip` da release) ou **Escolher ZIP…**.
- **Primeira instalação**: `PDFagent-Setup-1.3.0.exe`.

## SHA-256

```
a575ccdef92b0f358e78136510741d1164cc149f85cd471cc29d38cd4f5caad4  PDFagent-Setup-1.3.0.exe
6ee0574f0d63733f78c1ddcd6ae1bbe282515b0e5177fd0bf2f723de6a59969d  PDFagent.exe
445cb927850f534bdaa66f5884b3cf218a5a3646fe1062d1a8a1707100bb75fd  PDFagent-onedir-1.3.0.zip
80b571123b85740f249cb5fdb76e3a7834d2e646f4c0642c113ad7fdcc157d60  PDFagentUpdater.exe
```

## Limitações conhecidas

- O nível **Extreme** extrai texto diferente do original em 3 das 376 páginas do
  documento de estresse (acento/espaço) — está no teto do gate.
- Diff de versão de código custa ~19 MB (o PYZ do PyInstaller vive dentro do
  `PDFagent.exe`); nesta 1.3.0 o app e o updater mudaram.
- O portátil onefile roda em série (sem pools de processo) e não se atualiza por
  diff: use o instalador.
