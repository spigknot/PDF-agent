# RELATÓRIO CONSOLIDADO — CompressPDF × iLovePDF 2.3.6

> Gerado ao final da investigação. Fonte da verdade do que foi replicado,
> o que foi medido, e o que ainda difere. Para o detalhe técnico de cada
> achado ver `docs/METODO.md`.

## 1. Alvo

| item | valor |
|---|---|
| App | iLovePDF Desktop **2.3.6.0** (`C:\Program Files\WindowsApps\ILOVEPDFS.L…`) |
| Motor | 3-Heights PDF Optimizer, `PdfOptimizeAPI.dll`, SHA-256 `d74e91de…3a83` (idêntico à 2.3.4) |
| Fachada | `iLovePdfTools.dll`, SHA-256 `802937db…a4e2` (presets iguais aos da 2.3.4) |
| Níveis | Extreme (2) · Recommended (1, padrão) · Low (0) |

Parâmetros extraídos por disassembly (`capstone`) e conferidos nas duas versões:

```
EXTREME      Profile(2) ColorConversion(1) BitonalCompressions(128)
             ContinuousCompressions(2) ImageQuality(60)
             ResolutionDPI(72) ThresholdDPI(110) ClipImages(1)
             OptimizeResources(1) RemoveRedundantObjects(1)
             RemoveStandardFonts(1) SubsetFonts(1) Strip(127)
             ReduceColorComplexity(1)

RECOMMENDED  Profile(2) ResolutionDPI(150) ThresholdDPI(150)
             ImageQuality(60) ColorConversion(0) Strip(1143)

LOW          ColorConversion(0) BitonalCompressions(128)
             ContinuousCompressions(2) ImageQuality(75)
             ResolutionDPI(200) ThresholdDPI(400)
             OptimizeResources(1) RemoveRedundantObjects(1)
             RemoveStandardFonts(1) SubsetFonts(1)
```

`SetImageStratConserv` e `SetForceRecompression` **não são importados** — o
motor roda com os defaults.

## 2. Resultado medido (7 PDFs reais × 3 níveis = 21 saídas)

| métrica | CompressPDF | iLovePDF |
|---|---|---|
| tamanho total | **4.040.126 B** | 4.203.565 B (**−3,9%**) |
| menor em | **21 / 21** arquivos | 0 |
| diferença média de render (pixels) | **0,058%** | 0,135% |
| SSIM médio vs original | **0,9990** | 0,9984 |
| pior caso SSIM | 0,9861 | 0,9714 |
| validação de estrutura (pdfinfo/poppler) | **21/21 sem erro** | 0 |
| texto extraído | **idêntico ao original** em 21/21 | — |
| hyperlinks (URI + posição) | **100% preservados** | — |

Corpus de estresse próprio (8 PDFs sintéticos × 3 níveis): **24/24 sem falha**,
nunca maior, render ≤ 1,13%. Cobre página rotacionada, imagem indexada,
transparência RGBA, formulário + link, 25 páginas, imagem 2600×3400 e misto.

## 3. Comportamentos replicados

1. JPEG embrulhado em Flate (`[/FlateDecode /DCTDecode]`, `DecodeParms=[null {Quality}]`),
   tabelas de quantização IJG iguais às do `Quality`.
2. Downsample `px = pt/72 × ResolutionDPI`, quando `DPI_efetivo > ThresholdDPI`
   — regra validada em **239 de 243** desenhos; as 4 exceções são imagens cujo
   resultado reamostrado não ficaria menor (o motor mantém bytes **e**
   dimensões originais), comportamento que também adotamos.
3. `ReduceColorComplexity`: RGB sem saturação → `/DeviceGray`.
4. `RemoveStandardFonts` (Low/Extreme): fonte embutida equivalente a padrão‑14 é
   substituída por `{Type, Subtype=/Type1, Encoding, BaseFont}` sem `/Widths`.
5. Fontes Type0/CID: re‑subset mantendo numeração de CID e reconstruindo
   `/CIDToGIDMap`; stream compartilhado entre fonte simples e CID é clonado.
6. `ClipImages`: recorte à área visível (clip retangular ∩ página), com remoção
   do clip em espaço unitário posterior ao `cm`.
7. Marcadores `BDC/BMC/EMC` sem `/OC` removidos quando `/StructTreeRoot` sai.
8. Content stream compactado (`Tm 1 0 0 1 x y` → `Td`), aplicado só quando menor.
9. Metadados: docinfo com datas+Producer atualizados; XMP re‑carimbado.

## 4. O que ainda difere (e por quê)

| # | diferença | causa | esforço para fechar |
|---|---|---|---|
| 1 | **JBIG2** em imagens bitonais | o motor tem `CJBIG2EncodeFilter`; usamos CCITT G4 (sem perda). Não há encoder JBIG2 open‑source na máquina (sem `jbig2enc`, sem Ghostscript; ImageMagick só decodifica) | **gancho pronto**: instalar `jbig2enc` no PATH ativa o candidato JBIG2 automaticamente (só vence se for menor que o G4) |
| 2 | fontes CFF ~2% maiores | as fontes já vêm subsetadas pelo produtor (45 glifos ↔ 44 CIDs); é só deflate | subsetter CFF próprio |
| 3 | 1 imagem em 243 com JPEG 7% maior | diferença de encoder, não de algoritmo | tuning de encoder |
| 4 | `ClipImages` só retangular | paths curvos exigiriam rasterizar máscara | implementação |
| 5 | bit 10 do `Strip(1143)` | semântica ambígua no manual; replicamos o **observado** em 8 amostras | precisa de saída nova do app |

Impacto prático de 1–5 no conjunto medido: **nenhum** (somos menores e mais
fiéis em todos os 21 casos). Em documentos com muitos scans P&B, o item 1 pode
inverter isso — é o único risco relevante conhecido.

## 5. Como usar

```bash
pip install -r requirements.txt
python app.py                                  # interface (duplo clique em CompressPDF.bat)
python compress.py entrada.pdf -n recommended  # CLI
COMPRESSPDF_KERNEL=bilinear python compress.py entrada.pdf -n extreme
```

Garantias embutidas:
- **nunca maior**: se a saída não ficar menor, o original é copiado byte a byte;
- **nunca divergente**: após comprimir, o render é comparado com o original a
  110 dpi; se passar de 2% (rec/low) ou 4% (extreme), refaz sem as etapas
  arriscadas (`ClipImages`, subset CFF).

## 6. Instrumento pronto para a próxima rodada

`REA-lab/_sonda/sonda.pdf` — 4 páginas desenhadas para responder o que falta:

| página | conteúdo | incógnita que resolve |
|---|---|---|
| 0 | texto tagueado + formulário + anotação + link + metadados | bit 10 do `Strip` |
| 1 | scan P&B 2480×3508 | uso real de JBIG2 |
| 2 | 4 fotos @200/267/317/417 dpi | regra exata de reamostragem |
| 3 | imagem com `/SMask` | tratamento de transparência |

Basta comprimir esse arquivo nos 3 níveis no iLovePDF e salvar as saídas em
`REA-lab/_sonda/` para fechar os itens 1 e 5 da tabela acima.
