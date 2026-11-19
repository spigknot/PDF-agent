# PDFagent 1.3.2

Rodada de **interface e desempenho percebido**: fim das janelinhas de console
piscando, um único diálogo com progresso e cronômetro, e o dividir passa a
perguntar o que fazer em vez de comprimir sozinho.

## O que mudou

### 1. Fim das "telinhas" de prompt

O `.exe` é `--windowed`. Vindo do **menu de contexto** (sem console pai), cada
worker de `multiprocessing` fazia o Windows abrir uma janela `conhost` — até
**22 janelinhas** piscando durante uma compressão.

- `compress._console_oculta()` aloca **uma** console oculta no start
  (`AllocConsole` + `SW_HIDE`); os filhos a herdam e nada aparece.
- Medido no mesmo cenário (Explorer): **22 → 0** janelas visíveis.

### 2. Um único diálogo, com progresso e cronômetro

O `--avisar` mostrava um MessageBox no fim. Agora é **uma janela só**:

- barra de progresso que avança pelas fases `[1]`…`[6]` do motor;
- **cronômetro** rodando (`12,3 s` → `1:02,3`) e **congelado no fim**;
- resultado na mesma janela (bytes antes/depois, %, tempo total);
- o botão Fechar fica travado durante o trabalho (sem fechar no meio);
- em **comprimir** e em **dividir**.

### 3. Dividir pergunta — e não comprime sozinho

O menu de contexto abria a compressão direto. Agora o diálogo pergunta:

- **limite por parte em MB**, uma casa decimal, **já preenchido com 1,7**;
- **caixa "Comprimir" DESMARCADA** por padrão; marcada, aparecem
  `low` / `recommended` / `extreme`;
- limites absurdos são recusados: **mínimo 1,0 MB** (uma página com imagem já
  passa disso) e máximo 2.000 MB — aceita vírgula (`1,5`) e ponto (`1.5`);
- Enter confirma, Esc/Cancelar fecha sem gerar nada.

Mesmo com a caixa desmarcada, o resultado continua na mesma janela, com as
partes geradas, o limite usado e o tempo.

## Compatibilidade

- CLI inalterado: `PDFagent split arquivo.pdf -l 5M --avisar` continua igual;
  `--sem-comprimir` segue valendo. A pergunta só aparece quando não há `-l`.
- Sem mudança de saída para `compress` (mesmo pipeline, mesmos bytes).

## Verificação

- `tests/test_progresso.py` — 9 testes: console oculta chamada no entrypoint,
  mapeamento fase→barra, formatação do cronômetro, janela única em comprimir e
  dividir, padrões do diálogo (1,7 MB / Comprimir desmarcada), recusa de limite
  inválido e cronômetro congelado.
- Gate completo (`scripts/verificar.py`): unitários + paridade no documento de
  estresse + DPI + executável + progresso.
