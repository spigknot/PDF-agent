# PDFagent 1.1.0

Primeira atualização depois da 1.0.0: **velocidade** (21 rodadas de otimização),
**fidelidade** no bitonal e o **executável que finalmente usa os núcleos** — a
1.0.0 rodava a compressão inteira em série dentro do `.exe`.

## O que mudou

- **Executável usa processos de verdade.** O entrypoint passou a chamar
  `multiprocessing.freeze_support()` e os pools deixaram de ser desligados no
  PyInstaller: o `.exe` foi de **111,8 s para 65,4 s** no mesmo documento
  (o CLI faz 62,1 s). O portátil onefile continua em série de propósito (cada
  worker reextrairia o bundle).
- **Coleta de fontes em processos** (8,7 → 2,2 s) com reuso por assinatura: a
  segunda coleta do documento, depois do merge, cai de 2,4 s para 0,3 s.
- **Clip e DPI numa passada só** (`_draws_pagina` devolve os dois): saiu um pool
  inteiro por compressão. O clip continua usando o parser sem filtro, porque
  `_aplica_clip_imagens` edita `instrucoes[cm_idx]`.
- **Bitonal mais fiel e menor**: kernel LANCZOS no lugar de NEAREST (−4,4 KB e
  render mais perto do original) e JBIG2 também no nível Recommended
  (−78 KB no documento de estresse).
- **Correções**: o log do pipeline de imagem dizia "8 threads" mesmo rodando em
  processos; a coleta de fontes deixou de serializar `set` entre processos (a
  ordem de iteração numerava os glifos de forma diferente do caminho serial).

## Desempenho medido

### Corpus de paridade (7 PDFs reais × 3 níveis = 21 saídas)

| métrica | PDFagent 1.1.0 | iLovePDF |
|---|---|---|
| tamanho total | **3.998.227 B** | 4.203.565 B (**−4,88%**) |
| menor em | **21 / 21** arquivos | 0 |
| diferença estrutural | **0 / 21** | — |

Comparado com a 1.0.0 (4.040.429 B): **−42.202 B** só de fidelidade/bitonal.

### Documento de estresse (`processo.pdf`, 34 MB, 376 páginas)

| nível | PDFagent | iLovePDF | |
|---|---|---|---|
| Recommended | **11.382.226 B** | 12.227.010 B | 93,09% |
| Extreme | 8.651.585 B | 9.275.878 B | 93,27% |
| Low | 14.884.111 B | 16.565.289 B | 89,85% |

- **Texto**: 0/376 páginas diferentes do original (Extreme: 3/376, teto do gate).
- **Render contra o original**: 0,313% médio, pior caso 8,67% (pg218) — o
  iLovePDF fica em 12,76% na mesma página.
- **Tempo** (Recommended): **62,1 s** no CLI e **65,4 s** no `.exe` instalado;
  iLovePDF ~60 s.

## Instalação

1. Baixe `PDFagent-Setup-1.1.0.exe` e execute (per-usuário, **não pede admin**).
2. Duas opções já marcadas: adicionar ao PATH e **"PDFagent > Comprimir"** no
   menu de contexto de PDFs (comprime em Recommended e guarda o original como
   `<nome>_old.pdf`).
3. Alternativa portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos;
   abre em ~2,6 s e roda em série).

## SHA-256

```
2514ba666be9f103eec3271f36294da8360894e6df2b65150263f9da6be81939  PDFagent-Setup-1.1.0.exe
89efccccdd49bb56d0f68cf876278562c0520772e14f2a960f28386c8116e323  PDFagent.exe
```

## Limitações conhecidas

- O nível **Extreme** extrai texto diferente do original em 3 das 376 páginas
  do documento de estresse (acento/espaço) — está no teto do gate.
- O **portátil onefile** roda em série/threads (103,9 s no mesmo documento):
  no onefile cada worker reextrairia o bundle. Para velocidade, use o instalador.
- Não há updater: a atualização é baixar o instalador novo por cima.
- `PDFAGENT_PROC_OFF=1` desliga todos os pools de processo (diagnóstico).
