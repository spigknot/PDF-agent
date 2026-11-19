# PDFagent 1.3.1

Correção do **instalador**: ele agora instala em **`C:\Program Files\PDFagent`**
com **UAC automático** (um clique em "Sim", sem precisar de "Executar como
administrador") e deixa a pasta **gravável pelo usuário**, para o updater por
diff continuar funcionando **sem admin**.

## O que estava errado na 1.3.0

- O instalador era `PrivilegesRequired=lowest` (per-usuário em
  `%LOCALAPPDATA%\Programs\PDFagent`). Quem rodava **como administrador** acabava
  instalando em `C:\Program Files\PDFagent` — e o Inno gravava esse caminho no
  registro (`Inno Setup: App Path`). A partir daí, qualquer execução **sem**
  admin tentava Program Files e falhava com **"Erro 5: Acesso negado"**.
- O Inno Setup 6.7 mantém o *loader* com manifesto `asInvoker` e, nesse cenário,
  **não pedia elevação** — então nem o `PrivilegesRequired=admin` resolvia.

## O que a 1.3.1 faz

| item | valor |
|---|---|
| pasta | **`{autopf}\PDFagent`** (Program Files) |
| privilégios | **`admin`** (chave de desinstalação em HKLM) |
| elevação | `InitializeSetup` **relança o setup com `runas`** quando não é admin — UAC garantido, um clique |
| permissões da pasta | **`Permissions: users-modify`** → app e updater escrevem sem UAC |
| pasta anterior | `UsePreviousAppDir=no` + pasta forçada na 1ª tela (fim do "Erro 5") |
| instalação per-usuário antiga | detectada e removida pelo próprio setup |
| atalhos | menu Iniciar ganhou **"Atualizador do PDFagent"** |

Verificado nesta máquina após instalar: `PDFagent 1.3.1` em
`C:\Program Files\PDFagent`, ACL `BUILTIN\Usuários:(OI)(CI)(M)`, PATH com a
pasta nova e a cópia per-usuário removida.

## Desempenho (inalterado — mesmo compressor)

| métrica | valor |
|---|---|
| corpus (7 PDFs × 3 níveis) | **3.998.227 B** contra 4.203.565 do iLovePDF (**−4,88%**), 21/21 menores, **0/21** diferenças estruturais |
| documento de estresse (Recommended) | **11.382.226 B** (93,09% da referência) |
| tempo | 62,1 s no CLI · 65,4 s no `.exe` instalado |
| texto / render vs original | 0/376 páginas · 0,313% médio, pior 8,67% (pg218) |

## Como atualizar

- **Pelo app** (1.3.0 em diante): abra o PDFagent, botão verde → baixa só o que
  mudou. Em Program Files isso **não pede UAC** (pasta `users-modify`).
- **Pelo atualizador**: `PDFagentUpdater.exe` → **Verificar** → **Atualizar**; ou
  **Instalar / reparar completo** / **Escolher ZIP…**.
- **Primeira instalação / mudança de pasta**: `PDFagent-Setup-1.3.1.exe`.

## SHA-256

```
f394ee5bb5b5e5d33eb0a02e0e4861cfc9eda0e24806d871f3d0462ef3732e34  PDFagent-Setup-1.3.1.exe
df7ffbfda800f72bb84c00c5e0e2432731ff8c4541e14b4b3e0bc7804bbb263e  PDFagent.exe
861e7febcbb23a94a22860021e089a7c818ee34e69bec8a99ade14f196337db8  PDFagent-onedir-1.3.1.zip
706e8ba0ba3205e615367aa7a5926fc4171410158e2e05fde75ff5b685a4bf5f  PDFagentUpdater.exe
```

## Limitações conhecidas

- Quem já tinha a 1.3.0 instalada em `%LOCALAPPDATA%` deve rodar este instalador
  uma vez (ele oferece remover a cópia antiga) para passar a receber as
  atualizações na pasta nova.
- O nível **Extreme** extrai texto diferente do original em 3 das 376 páginas do
  documento de estresse (acento/espaço) — está no teto do gate.
- Diff de versão de código custa ~11 MB (o PYZ do PyInstaller vive dentro do
  `PDFagent.exe`).
- O portátil onefile roda em série (sem pools de processo) e não se atualiza por
  diff: use o instalador.
