# HANDOFF — CompressPDF × iLovePDF

> Prompt de continuidade. Cole num agente novo para retomar sem perder contexto.
> Estado em: 20 rodadas de investigação concluídas.

---

## ESTADO ATUAL (fim da rodada 20, 22/11)

| métrica | valor | referência (motor) |
|---|---|---|
| recommended | **11.382.226 B** | 12.227.010 (93,09%) |
| extreme | 8.651.585 B | 9.275.878 (93,27%) |
| low | 14.884.111 B | 16.565.289 (89,85%) |
| tempo recommended | **62,1 s** (CLI, 8 pares) · **65,4 s** no `.exe` onedir (era **111,8 s**: rodava tudo em série) | ~60 s |
| texto | 0/376 (extreme 3/376, bug do extrator) | 0/376 |
| render vs **original** | média 0,3131%, pior 8,67% (pg218) | pior 12,76% (motor é pior) |
| gate | **PASS** — 0/3 + 0/21 + "coleta de fontes", "DPI efetivo" e "executável" | — |

Branch `paridade/rodada-5`, árvore limpa. **Release `v1.1.0` publicada** (tag no
commit `bebffc3`, 3 assets: instalador, portátil e `SHA256SUMS-1.1.0.txt`;
`main` == `paridade/rodada-5`). Rodadas 17-21: coleta de fontes em processos,
reuso por assinatura, DPI em processos, DPI dentro da passada do clip e
`freeze_support()` no executável — a saída segue estruturalmente idêntica.

**A rodada 20 quase foi revertida:** o merge do DPI no clip rendeu só **−0,35 s**
(0,6%) e introduziu um bug que o gate pegou (2/21: o DPI precisa ser o estado
PÓS-clip, porque o clip reescreve o `cm` e recorta os pixels). Corrigido e
vacinado (`test_dpi_e_recalculado_depois_do_clip`); fica pelo spawn de pool que
economiza. Se quiser o código mínimo: `git revert` do commit da rodada 20 devolve
a 19 inteira, sem perda de qualidade de saída.

**Atenção ao medir:** o run completo varia ±2 s entre janelas. Compare mudanças
com **A/B alternado no mesmo momento** (binário antigo × novo, um após o outro)
ou pela fase instrumentada; medianas de sessões diferentes mentem.

**Onde está o tempo agora (medido):** imagens ~30 s (piso de núcleos: ~500 s de
CPU em 24 workers), `normaliza_conteudo` 14,4 s, clip+DPI 5,7 s, coleta de
fontes 2,5 s, subset ~3 s, save ~5,5 s. **Não há mais alavanca grande
conhecida:** o que sobra é piso de CPU ou exigiria parser próprio (descartado na
rodada 12 por quebrar a paridade byte a byte com o motor).

**Ferramentas que economizam tempo:**
- `PDFAGENT_DEBUG_TEMPO=1` → tempo por fase, com "fontes: coleta pacotes X
  (cache|pool) Y replay Z" e "dpi: ... (do clip)".
- `scripts/mede_tempo.py recommended 3 --fases` → mediana (cuidado com a deriva).
- `COMPRESSPDF_MERGE=0`, `COMPRESSPDF_CASAS=N`, `PDFAGENT_FONTES_SERIAL=1`,
  `PDFAGENT_FONTES_CACHE=0`, `PDFAGENT_DPI_SERIAL=1` (força o DPI fora do clip e
  em série), `PDFAGENT_KERNEL_BITONAL`, `PDFAGENT_BITONAL`,
  `PDFAGENT_PROC_*` → A/B sem editar código (`docs/COMANDOS.md` §4b).

**Seis lições que custaram rodadas inteiras:**
1. O gate de render comparava com o **motor**; o correto é o **original** — em
   22 páginas somos mais fiéis a ele. E cobria 10 páginas fixas, escondendo a
   pior (pg218).
2. Paralelizar o parser **que já existe** é seguro; trocar por um equivalente
   (ou filtrar operadores) desalinha índices usados em outra etapa — foi 2/21 no
   gate. Quando duas fases leem a mesma página, **junte as passadas sem trocar
   os parsers** (rodada 20).
3. Não atravessar `set` de códigos entre processos: a ORDEM DE ITERAÇÃO depende
   do histórico de inserção, e `_cod2glifo` numera glifos iterando esse set — o
   arquivo saía 20 B diferente com conjuntos iguais. `sorted()` esconde isso;
   compare `list(set)`. E não reusar `ProcessPoolExecutor` dentro de worker de
   `ProcessPoolExecutor` (Windows/spawn): trava com 0% de CPU.
4. Cache de coleta precisa de assinatura **estável**: `id()` de dicionário
   direto muda entre duas chamadas do mesmo arquivo. Use caminho/rótulo
   (`"p7/Fm1"`) e nomes, nunca identidade de objeto.
5. Em `ProcessPoolExecutor`, "economizar pickle" pode sair caro: `initializer`
   com um mapa de 0,58 MB ficou **2,6× mais lento** que mandar o mapa em cada
   tarefa (6,30 × 2,38 s), e `chunksize=4` também perdeu (4,65 s) por
   desbalancear tarefas de tamanhos muito diferentes.
6. Antes de otimizar por dedução, **prove a equivalência** (draws campo a campo,
   mapa de DPI imagem por imagem) e só então meça tempo — foi assim que a
   rodada 20 mexeu no caminho `cm_idx` sem quebrar o índice.
7. Ao fundir duas fases numa passada só, pergunte **se a segunda lê algo que a
   primeira ESCREVE**: o clip reescreve o `cm` e recorta pixels, então o DPI
   efetivo tem de ser medido no estado PÓS-clip (a versão pré-clip passou 2/21
   no gate). E prove contra o caminho antigo **no arquivo final**, não só nas
   estruturas intermediárias.
8. Em A/B de tempo, **alterne qual binário roda primeiro** e desconfie de um
   resultado bonito: 4 pares davam −2,18 s; com a ordem invertida em metade dos
   pares e o código corrigido, o Δ real caiu para −0,35 s.
9. **Meça o artefato que o usuário recebe.** Quando o app é distribuído como
   `.exe`, o caminho do PyInstaller é outro: `freeze_support()` no entrypoint e
   nenhum `not getattr(sys, "frozen")` — o executável rodava em 111,8 s o que o
   CLI fazia em 62,1 s. O portátil onefile fica de fora do pool (reextrai o
   bundle a cada worker).


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

## Rodada processo.pdf (34 MB, 376 páginas, TJSP/SAJ)

Corpus de estresse fora do gate. `processo.pdf` (34.070.740 B) →
**12.244.996 B (−64,0%)** contra **12.227.010 B** do iLovePDF (recommended);
extreme 9.311.583 B (−72,2%) contra 9.275.878 B (+0,38%); low 15.738.078 B (−53,4%) contra 16.565.289 B (**−4,99%**); recommended 12.103.750 B (−1,01%). Texto extraido: recommended e low 0/376, extreme 3/376 (acento/espaco). Tempo 148–156 s → **128,9 s** após paralelizar encoders e lotear o subset de fontes (ver §5 do METODO).

- **Texto extraído idêntico ao original nas 376 páginas** (era 7 páginas com
  divergência: `/ToUnicode` fora da identidade da fonte e fontes apagadas por
  página com imagem inline).
- **Render contra a saída do iLovePDF**: 0,000% na maioria das páginas; ≤0,11%
  nas páginas com máscara 1-bit (única diferença estrutural que sobra lá).
- O gate do corpus continua **0/21** e o total do corpus caiu para
  **3.998.962 B** contra 4.203.565 B do iLovePDF (**−4,87%**).
- Detalhe técnico de cada achado: `docs/METODO.md` §5.

## Placar final (21 pares = 7 PDFs × 3 níveis)

| eixo | nosso | iLovePDF |
|---|---|---|
| tamanho total | **3.998.962 B** | 4.203.565 B (**−4,87%**) |
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
10. **`keys()` num array devolve `[]` (pikepdf 10.18)** — nunca inferir
    dicionário por `keys()`: use `obj._type_name`. Era a causa de metade das
    imagens/formas duplicadas que sobravam.
11. **Recursar em objeto indireto no remapeamento** estoura a pilha: o grafo tem
    ciclo em `/Parent`. Só descer em container direto.
12. **`Object.write(zlib_data)` sem `filter=`** comprime de novo (dupla
    compressão) — passar `filter=Name("/FlateDecode"), type_check=False`.
13. **Imagem inline (`BI…ID…EI`) não mascarada** fazia o tokenizador parar e as
    fontes da página serem apagadas como "sem uso" (render 3,9–8,7% errado).
14. **Fundir fontes com `/ToUnicode` diferente** mantém o render e quebra a
    extração de texto ("Laudo" → "/audo").

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

---

## Caso `REA-lab\x` — por que o iLovePDF parecia "muito superior"

`x.pdf` tem 711.716 B e **91% do peso em 6 programas de fonte** (Calibri 198 KB,
Calibri-Bold 197 KB, Calibri-Italic 102 KB, ArialMT 102 KB, Arial-Black 31 KB,
Wingdings 15 KB); as imagens somam só 5,7 KB. O gargalo era fonte, não imagem.

| nível | nós (antes) | nós (agora) | iLovePDF |
|---|---|---|---|
| recommended | 238.175 | **95.472** (−6,2%) | 101.754 |
| low | 238.507 | **97.941** (−3,8%) | 101.760 |
| extreme | 220.237 | **75.854** (−3,6%) | 78.689 |

Duas causas, ambas corrigidas:

1. **`/CIDToGIDMap /Identity` era pulado** em `_subset_fontes_cid`
   (`if c2g is None or isinstance(c2g, Name): continue`): ArialMT e Wingdings
   (Type0/CIDFontType2) ficavam com o programa inteiro. Agora o mapa é
   reconstruído como stream (CID → novo GID); texto continua idêntico.
2. **Política de subset agora é a do motor** (`COMPRESSPDF_SUBSET=motor`, o
   padrão): `retain_gids` + hinting + sem GPOS/GSUB/GDEF. Os subsets deles têm
   exatamente as contagens por GID 218/178/857/896/856/30 e só as tabelas
   `glyf/fpgm/prep/cvt/hmtx/loca/name` — com essa política batemos glifo por
   glifo e o tamanho encosta no deles.

Também refinei o corte de imagem: desenho com lado menor < 60 pt só é
preservado quando o dpi é < 150 (o x.pdf tem 48x45 pt a 199 dpi e é reduzido,
como eles fazem).

Corpus: total **−3,9%** (4.040.405 B), nenhum arquivo maior, paridade
estrutural 0/21, PSNR 33,22 vs 30,79 dB, render 0,058% vs 0,135%.

Neste arquivo as decisões de imagem agora também batem: a imagem 134x125 é
reduzida para 48x45 no extreme e para 101x94 no recommended, como eles fazem.
