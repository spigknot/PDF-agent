# HANDOFF — CompressPDF × iLovePDF

> Prompt de continuidade. Cole num agente novo para retomar sem perder contexto.
> Estado em: 13 rodadas de investigação concluídas.

---

## Objetivo do projeto

Temos um app próprio de compressão de PDF (`D:\Projetos\PDF-agent`) cujo
algoritmo foi **replicado por engenharia reversa** do iLovePDF Desktop. A meta
declarada pelo usuário, repetida em todas as rodadas:

> **"deixar o algoritmo o mais idêntico possível, aceitando tamanho de arquivo
> final igual ou menor — nunca maior", com qualidade "extremamente similar".**

Regra de ouro: **se não der para igualar, ficar menor; nunca ficar maior.

---

## Alvo da replicação

```
C:\Program Files\WindowsApps\ILOVEPDFS.L.iLovePDF-PDFReaderandEditor_2.3.6.0_x64__0q01bhdkqq106\iLovePDF\
```

| arquivo | SHA-256 | papel |
|---|---|---|
| `PdfOptimizeAPI.dll` | `d74e91dec7e857862e8338db383083d62036b3af9e3edeb6b9536f97c0083a83` | motor 3-Heights PDF Optimizer (idêntico à 2.3.4) |
| `iLovePdfTools.dll` | `802937dbb38b701ae7fe8a939d979a87bed2ffc320456f232b80ad9628c9a4e2` | fachada C++ com os presets (mudou na 2.3.6, presets iguais) |
| `iLovePDF.exe` | — | UI Qt/QML, sem CLI nem scheme de URL |

**Atenção:** a versão anterior (2.3.4) foi desinstalada no meio do processo e
depois reinstalada como 2.3.6. Os arquivos de referência em `REA-lab` foram
gerados com a 2.3.4, mas o motor é byte-idêntico, então servem.

---

## Presets extraídos por disassembly (capstone + pefile)

Mapeamento de nível: `0=Low`, `1=Recommended (padrão)`, `2=Extreme`
(`CompressPdf` lê `[rdi+0x50]` com `SetCompressLevel` validando `<=2`).

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

`SetImageStratConserv` e `SetForceRecompression` **não são importados** pelo
wrapper — motor roda com defaults. `CJBIG2EncodeFilter` **existe** (o motor
codifica JBIG2).

---

## O que já está implementado e validado

`compress.py` (~2.700 linhas) replica, com `pikepdf` + `Pillow` + `fontTools`:

1. **JPEG embrulhado em Flate** — `Filter=[/FlateDecode /DCTDecode]`,
   `DecodeParms=[null {Quality}]`, tabelas IJG do `Quality`.
2. **Downsample** `px = pt/72 × ResolutionDPI` quando `DPI_efetivo >
   ThresholdDPI` (regra explica **239 de 243** desenhos; as 4 exceções são
   imagens cujo resultado não ficaria menor — o motor mantém bytes e dims).
3. **Kernel duplo por imagem**: gera LANCZOS e BILINEAR (o motor usa filtro
   triangular — identificado em 3 saídas sem perda) e fica com o menor JPEG.
4. **`ReduceColorComplexity`** com detecção estrita de cinza (NEAREST +
   diferença entre canais ≤ 8).
5. **`RemoveStandardFonts`** (Low/Extreme): troca fonte embutida equivalente a
   padrão‑14 por `{Type, Subtype=/Type1, Encoding, BaseFont}` sem `/Widths`;
   zera o programa de fonte desanexado (qpdf grava objetos inalcançáveis).
6. **Subset de fonte simples** por nome de glifo (encoding do PDF) com
   verificação; **subset Type0/CIDFontType2** preservando CIDs e reconstruindo
   `/CIDToGIDMap`; clona stream de fonte compartilhado antes de mexer.
7. **`ClipImages`**: recorta à área visível (clip retangular ∩ página), remove
   clip em espaço unitário posterior ao `cm`.
8. **`Strip`**: docinfo, threads, pieceinfo, thumbs, spider, alternates,
   structtree, anotações invisíveis — conforme o nível.
9. **Marcadores `BDC/BMC/EMC`** sem `/OC` removidos quando `/StructTreeRoot` sai
   (~12% do content stream).
10. **Content stream compactado** (`Tm 1 0 0 1 x y` → `Td`, separadores mínimos),
    aplicado **só quando o stream fica menor**.
11. **XMP regenerado** (stamp próprio de 857 B; o motor sempre regenera o dele
    de ~1.414 B) e docinfo com datas+Producer atualizados.

Garantias embutidas no `comprimir()`:
- **nunca maior**: se a saída não ficar menor, copia o original byte a byte;
- **nunca divergente**: compara render a 110 dpi com o original; acima de 2%
  (rec/low) ou 4% (extreme) refaz **sem** `ClipImages` e sem subset CFF.

---

## Corpus e instrumentos

```
C:\Users\Gustavo\Desktop\REA-lab\
  originais\                    7 PDFs reais
  ilovepdf - {recommended,extreme,low}\    referências do motor
  compresspdf - ...-v11\        nossa saída final
  _sonda\sonda.pdf              PDF-sonda (ver abaixo)
```

Scripts de avaliação (em `C:\Users\Gustavo\AppData\Local\Temp\rea_lab2\`):
`regera.py`, `audit_final.py`, `psnr_img.py`, `size_img.py`, `valida.py`,
`stress.py`, `textpos.py`, `estrutura.py`, `deriva_regra.py`,
`presets236.py`, `orfaos.py`.

---

## Placar final (21 pares = 7 PDFs × 3 níveis)

| eixo | nosso | iLovePDF |
|---|---|---|
| tamanho total | **4.040.126 B** | 4.203.565 B (**−3,9%**) |
| menor em | **21 / 21** | 0 |
| algum arquivo maior | **nenhum** | — |
| PSNR por imagem (158) | **33,22 dB** | 30,79 dB |
| imagens >0,5 dB pior | **0** | — |
| imagens >8% maiores | **0** | — |
| deslocamento de texto | **0,00 pt** | 0,00 pt |
| render médio/página | **0,058%** | 0,135% |
| SSIM | **0,9990** | 0,9984 |
| texto extraído | idêntico ao original | — |
| hyperlinks | 100% preservados | — |
| validação (pdfinfo/poppler) | 21/21 sem erro | 21/21 |
| Root/páginas/anotações | sem divergência | — |
| corpus de estresse (24) | aprovado | — |

Detalhe importante: no `teste.pdf` os 3 níveis trocam a fonte por padrão‑14 e o
deslocamento de texto resultante é **2,43 pt em 422 de 426 palavras** — o mesmo
número e a mesma contagem que o iLovePDF produz.

---

## Bugs reais encontrados (para não reintroduzir)

1. `parse_content_stream` devolve `Decimal`/`Name`/`Operator` — comparar como
   string quebrava o rastreio de DPI.
2. LANCZOS em imagem de traço gera ringing e infla o Flate 8–10× (8.593 vs 913 B).
3. Subset de fonte por Unicode apagava o glifo de "ú" (string `"/Dúvidas"`
   descartada por começar com `/` — sempre distinguir por **tipo de token**).
4. Stream de fonte compartilhado entre fonte simples e Type0: subsetar uma
   corrompe a outra — **clonar antes**.
5. `_usos_por_fonte` descartava ocorrências da mesma fonte em páginas
   posteriores — somar os conjuntos.
6. Clip em espaço unitário (após o `cm`) precisa ser removido depois do recorte.
7. Flate com preditor fixo era maior que zlib cru em imagens pequenas.
8. Detecção de cinza por média (downsample 32×32) mascarava cor — imagens com
   saturação 184 viravam `/DeviceGray` (PSNR 20,9 dB).
9. **Subset CFF reprovado duas vezes** (fontTools reescreve o charset CID):
   8,5–9,4% de divergência, mesmo com `retain_gids`. `_TENTA_CFF = False`.

---

## O que falta (e por quê)

| # | gap | situação |
|---|---|---|
| 1 | **JBIG2** em scans P&B | motor codifica (`CJBIG2EncodeFilter`); usamos CCITT G4. **Gancho pronto** (`_jbig2_bytes`): instalar `jbig2enc` no PATH ativa o candidato automaticamente (só vence se for menor). |
| 2 | Fontes **CFF** ~2% maiores | já vêm subsetadas pelo produtor (45 glifos ↔ 44 CIDs); é só deflate. Exigiria subsetter CFF próprio. |
| 3 | **bit 10 do `Strip(1143)`** | semântica ambígua no manual; replicamos o observado. Strings do motor ficam num *pool* sem struct `(bit,nome)` — mapear estaticamente não saiu. |
| 4 | 1 imagem em 243 | encoder JPEG deles 7% melhor no mesmo tamanho; sem causa isolada. |
| 5 | `ClipImages` não retangular | paths curvos exigiriam rasterizar máscara. |

---

## Como destravar o que falta (3 caminhos)

1. **`jbig2enc` instalado** → item 1 resolvido sem tocar em código.
2. **Comprimir a sonda nos 3 níveis** e salvar em `REA-lab\_sonda\`:
   `sonda.pdf` tem 4 páginas desenhadas para responder (a) bit 10 do `Strip`
   (texto tagueado + formulário + anotação + link), (b) uso real de JBIG2
   (scan P&B A4), (c) regra exata de reamostragem (escada de DPI
   200/267/317/417), (d) tratamento de `/SMask`.
3. **Autorização para operar a GUI** do app (abre com `CompressPDF` na tela) —
   um clique foi bloqueado por falta de consentimento no passado; **não
   repetir sem autorização**.

---

## Como rodar e verificar

```bash
cd D:\Projetos\PDF-agent
pip install -r requirements.txt          # pikepdf, Pillow, fonttools, pymupdf

python app.py                            # GUI (ou duplo clique em CompressPDF.bat)
python compress.py entrada.pdf -n recommended
python tests/test_levels.py              # deve imprimir TUDO OK

python scripts/build_exe.py              # gera dist/PDFagent.exe (GUI + CLI)
                                         # sem args: GUI | com args: CLI | --version

python scripts/verificar.py              # GATE UNICO: niveis + paridade vs
                                         # iLovePDF + launcher .bat + exit code
```

Verificação completa (recomendada após qualquer mudança):

```bash
python C:/Users/Gustavo/AppData/Local/Temp/rea_lab2/regera.py      # 21 saídas
python C:/Users/Gustavo/AppData/Local/Temp/rea_lab2/audit_final.py # tamanho+texto+links
python C:/Users/Gustavo/AppData/Local/Temp/rea_lab2/psnr_img.py    # qualidade por imagem
python C:/Users/Gustavo/AppData/Local/Temp/rea_lab2/stress.py      # 24 casos sintéticos
python C:/Users/Gustavo/AppData/Local/Temp/rea_lab2/textpos.py     # drift de layout
```

Critérios de aceitação antes de qualquer entrega:
- **nenhum** dos 21 arquivos maior que o do iLovePDF;
- `falhas: nenhuma` no `audit_final.py`;
- `piores que eles: NENHUM` no PSNR/render;
- `tests` e `stress` verdes.

---

## Orientações para o próximo agente

- **Prioridade absoluta**: nunca entregar arquivo maior nem visualmente pior.
  Se uma otimização não puder ser validada com medição, não aplicar.
- Toda mudança exige re-rodar a bateria acima. Já houve regressão silenciosa
  (perda de cor) que só apareceu na métrica **por imagem**.
- O histórico completo das 31 descobertas está em `docs/METODO.md`; o resumo
  executivo em `docs/RELATORIO.md`.
- Não inventar conclusão: se um eixo não foi medido, dizer "não medido".
- Os eixos mensuráveis já estão todos empatados ou melhores. Ganho novo exige
  uma das três destravas acima — o resto é engenharia de implementação
  (encoder JBIG2 próprio, subsetter CFF), não investigação.

---

## Rodada REA (Ghidra 12.1.4) — o que o binário provou

Ferramental: REA 6.7.0 + Ghidra **12.1.4** (`%LOCALAPPDATA%\rea\ghidra_12.1.4`;
o REA só aceita a linha 12.1.x — 12.2 é rejeitado como `unsupported`).
Alvo: `PdfOptimizeAPI.dll` 7,72 MB (`d74e91de…`, o mesmo do SHA-256 acima),
copiado para `%LOCALAPPDATA%\rea\targets\` (a ponte exige NTFS local, fora de
`WindowsApps`). 207 ferramentas MCP; a análise custa ~7 min e fica em cache
por processo — para investigação iterativa vale manter um daemon MCP.

**Bloco de opções** (objeto `operator_new(0x14c8)`, offsets no handle):
`ImageQuality` +0x1400 · `ForceRecompression` +0x142c · `ReduceColorComplexity`
+0x143c · **`Strip` +0x1440** · `SubsetFonts` +0x1448 · `MergeEmbeddedFonts`
+0x1449 · `OptimizeResources` +0x144f · `ClipImages` +0x1450 · `ConvertToCFF`
+0x1452. Resoluções/limiares por tipo: bitonal +0x13d0/+0x13d8, mono
+0x13e0/+0x13e8, cor +0x13f0/+0x13f8 (todos `double`; `SetThresholdDPI` grava
nos **três**).

**Bit 10 do `Strip(1143)`**: não é strip de conteúdo. Única leitura da máscara
em todo o binário: `FUN_1800b00e0` (pré-save), `0x1800b01ae` →
`test dword ptr [doc+0xBE8], 0x400` + `& 8`, alimentando diagnóstico com os
códigos `0x1401/0x1702/0x1712`. A implementação anterior ("remove anotação
invisível") foi removida; o corpus não tem nenhuma (`/F` bit 1 = 0 em 29
anotações, todas `/Link`).

**Pipeline de imagem**: `FUN_1800a6720` calcula `dpi = px * 72 / largura_pt`
(com fallback 92 dpi) e decide por `threshold`/`resolution` que vêm do handle.
Censo do corpus: **0% bitonal**, 84,8% dos bytes de imagem em Flate RGB 8-bit.

**Efeito medido no app** (teste `tests/test_paridade.py`, 21 combinações):
**21/21 estruturalmente idênticas** ao iLovePDF (antes: 8/21), **nenhum arquivo
maior** em nenhum nível e total **−3,9%**. Correções que vieram dessa rodada:
`/MarkInfo` removido com o `StructTree`; docinfo preservado nos 3 níveis;
reamostragem com o kernel do motor (triangular), variante escolhida pelo menor
stream final **do perfil** (JPEG ou Flate); redução de cor sempre que a imagem é
re-codificada; fim do "Flate de resgate" (extreme/low são só JPEG); corte de
60 pt no lado menor desenhado; alvo de pixels em float32 com `round` do C; e
`ceil` no alvo de imagem recortada pelo ClipImages (não perde a última linha).
Ver `METODO.md` §4b.
