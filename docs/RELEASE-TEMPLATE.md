# PDFagent <versao>

Réquiem do compressor de PDF com os 3 níveis do iLovePDF (Extreme / Recommended / Low).

## O que mudou

- <mudança 1 — com o porquê, não só o quê>
- <mudança 2>

## Desempenho medido (7 PDFs reais × 3 níveis)

| métrica | PDFagent | iLovePDF |
|---|---|---|
| tamanho total | **<X> B** | 4.203.565 B (**<Δ>%**) |
| menor em | **21 / 21** | 0 |
| render médio por página | **<%>** | <%> |
| PSNR por imagem (158) | **<X> dB** | <Y> dB |
| SSIM médio | **<X>** | <Y> |
| texto / hyperlinks | idênticos ao original | — |

Saída do gate (`python scripts/verificar.py`):

```
[OK] testes de nivel (3 niveis)
[OK] CLI falha com exit code != 0
[OK] launcher .bat (sintaxe e caminho)
[OK] paridade estrutural vs iLovePDF        0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. Baixe `PDFagent-Setup-<versao>.exe` e execute (per-usuário, **não pede admin**).
2. Duas opções já marcadas: adicionar ao PATH e "PDFagent > Comprimir" no menu
   de contexto de PDFs.
3. Alternativa portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos).

## SHA-256

```
<hash>  PDFagent.exe
<hash>  PDFagent-Setup-<versao>.exe
```

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 (não há codificador open-source no
projeto), subsetter CFF próprio e `ClipImages` de paths curvos. Diferenças
residuais medidas contra o iLovePDF: 15 nós de `/StructElem` e 18 bytes de
filtro em imagens `1×1`.
