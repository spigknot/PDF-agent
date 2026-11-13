# COMANDOS.md — como adicionar funções ao PDFagent

> Contrato para que toda função nova (split, merge, rotate, extrair páginas…)
> entre pelo mesmo caminho: **um binário, N subcomandos, shims no PATH**.

## 0. O desenho

```
PDFagent.exe                     → GUI (sem argumentos)
PDFagent compress a.pdf -n low   → subcomando
PDFagent a.pdf -n low            → retrocompatível (equivale a compress)
pdfcompress.cmd a.pdf -n low     → shim no PATH (chama `PDFagent compress`)
```

- **Uma cópia das dependências** (pikepdf, PyMuPDF, fontTools) shared by todos.
- **Instalador leva o onedir** (`dist/PDFagent/`): start ~0,3 s.
- **Onefile** (`dist/PDFagent.exe`) existe só como portátil: start ~2,6 s, porque
  extrai o bundle a cada execução. Não é o canal de instalação.
- Shims são `.cmd` de ~40 bytes gerados a partir do registro — **nunca** crie um
  exe por função (cada um custaria 20–60 MB e continuaria lento).

## 1. Registrar o comando (`cli.py`)

```python
COMMANDS = {
    "split": {
        "help": "divide um PDF em arquivos por página ou por intervalo",
        "alvo": ("commands.split", "main"),   # (módulo, função)
        "shim": "pdfsplit",                   # None = sem shim
    },
    ...
}
```

Regras:
- `alvo` aponta para `main(argv) -> int | None` (None = sucesso, 0).
- `shim` é o nome do executável no PATH (`pdfsplit` → `pdfsplit.cmd`).
- Nome do comando em minúsculas, sem acento; sinônimos em `SINONIMOS`.

## 2. Criar o módulo

```python
# commands/split.py
"""split — divide um PDF."""
import argparse, sys

def main(argv=None):
    ap = argparse.ArgumentParser(prog="PDFagent split", description=__doc__)
    ap.add_argument("entrada")
    ap.add_argument("-o", "--saida-dir", default=".")
    args = ap.parse_args(argv)
    ...
    return 0
```

- `import` de bibliotecas pesadas **dentro** da função quando possível (startup).
- Sai com `0` sucesso, `1` falha de execução, `2` erro de uso (argparse já faz).
- Escreve em `stdout` o que o humano precisa; erro em `stderr`.
- **Nunca** abre GUI, nunca pede input interativo (o menu de contexto roda sem
  console).
- Toda operação que sobrescreve arquivo segue o padrão do `compress`:
  original vira `<nome>_old.<ext>`, saída assume o nome original, e **se não
  melhorar nada, não toca no arquivo**.

## 3. Testes (obrigatório)

- `tests/test_<comando>.py` com um fixture gerado na hora (sem depender de
  arquivos do usuário).
- Adicione o caso ao gate `scripts/verificar.py` se ele for rápido (<30 s);
  caso contrário, deixe no `pytest`/script próprio e cite no UPDATE.md.

## 4. Build e shim

```bash
python scripts/build_exe.py --onedir   # gera dist/PDFagent/ + shims
python scripts/build_exe.py            # onedir + onefile portátil
```

- `scripts/gerar_shims.py` lê `cli.COMMANDS` e escreve `dist/PDFagent/<shim>.cmd`.
- O instalador (`instalador/PDFagent.iss`) copia a pasta inteira:
  `Source: "..\dist\PDFagent\*"`.
- PATH aponta para `{app}`; os shims entram junto (tarefa `addpath`).

## 5. Orçamento de tamanho (não regredir)

| item | regra |
|---|---|
| `pymupdf` | **nunca** `--collect-all` (puxa 41 MB de ONNX de layout + `.lib/.h`) |
| módulos não usados | excluir no `build_exe.py` (`sympy`, `pygments`, `_pytest`, `PIL._avif`) |
| dependência nova | justificar no PR/release **e** medir o exe antes/depois |

Referência: 58,6 MB (onefile) / 134 MB (onedir em disco) após o enxugamento.

## 6. Checklist de uma função nova

- [ ] comando registrado em `cli.py` (com `help`, `alvo`, `shim`)
- [ ] `main(argv) -> int|None` implementado e testado
- [ ] `PDFagent <comando> --help` funciona
- [ ] retrocompatibilidade intacta (`PDFagent a.pdf -n low`, `--in-place`)
- [ ] shim gerado e testado (`pdfsplit.cmd`)
- [ ] gate verde (`0/21`) e testes novos passando
- [ ] tamanho do exe medido (sem regressão grosseira)
- [ ] README/UPDATE.md/este documento atualizados se algo mudou
