# METODO — como o iLovePDF comprime (engenharia reversa)

Alvo: `C:\Program Files\WindowsApps\ILOVEPDFS.L.iLovePDF-PDFReaderandEditor_2.3.4.0_x64__0q01bhdkqq106\iLovePDF\`
Ferramenta: REA MCP (`mcp__rea__*`) + análise local (capstone/pefile/ctypes).

## 1. Arquitetura

| Achado | Evidência |
|---|---|
| Engine = **3-Heights PDF Optimizer** (PDF Tools AG), `PdfOptimizeAPI.dll` 8 MB, 60 exports C (`PdfOptimizeCreateObject/OpenW/Set*/SaveAsW`) | `pefile` exports; `Java_com_pdftools_pola_PdfOptimize_*` (238 JNI) |
| Fachada = `iLovePdfTools.dll` 5,4 MB, 923 exports, classe `PdfCompressTask` | `pefile` exports |
| UI = Qt6/QML (`CompressTool.qml`, `CompressModel.qml`, `compressLevel`) | strings UTF-16 de `iLovePDF.exe` |
| Nativo, sem .NET | `inspect_managed_artifact` → `not-managed` (REA ev.) |
| Sessão REA `open_binary` → exe sha256 `9d7f773a…`, x86_64 | REA ev. (sessão fechada com `close_binary`) |

## 2. Os 3 presets (disassembly, `capstone`, RVAs do `iLovePdfTools.dll`)

`CompressPdf @0x35080` lê `level = [rdi+0x50]` (`SetCompressLevel` valida `<=2`,
`SetDefaults` define `1`):
`0 → LowCompressSettings @0x35E90`, `1 → RecommendedCompressSettings @0x35F30`,
`2 → ExtremeCompressSettings @0x35990`. Enum: **0=Low, 1=Recommended (default), 2=Extreme**.
Cada função = sequência de `call [rip+IAT]` → `PdfOptimizeAPI.DLL!PdfOptimizeSet*`
(resolvido via tabela de imports; imediatos `edx`/`xmm1` extraídos).

**Extreme (2)** — `Profile(2) ColorConversion(1) BitonalCompressions(128)`
`ContinuousCompressions(2) ImageQuality(60) ResolutionDPI(72.0) ThresholdDPI(110.0)`
`ClipImages(1) OptimizeResources(1) RemoveRedundantObjects(1) RemoveStandardFonts(1)`
`SubsetFonts(1) Strip(127) ReduceColorComplexity(1)`

**Low (0)** — `ColorConversion(0) BitonalCompressions(128) ContinuousCompressions(2)`
`ImageQuality(75) ResolutionDPI(200.0) ThresholdDPI(400.0)`
`OptimizeResources(1) RemoveRedundantObjects(1) RemoveStandardFonts(1) SubsetFonts(1)`

**Recommended (1)** — `Profile(2) ResolutionDPI(150.0) ThresholdDPI(150.0)`
`ImageQuality(60) ColorConversion(0) Strip(1143)`

## 3. Semântica (manual oficial `PdfOptimizeAPI 6.27` + perfis)

- `Profile`: 0=Default 1=Web **2=Print** 3=Archive 4=Max 5=MRC (ordem da tabela).
  Print = base do Extreme/Recommended.
- `ColorConversion`: 0=None 1=RGB(eConvRGB) 2=CMYK 3=Gray.
- Máscaras (bitmask, potências de 2 na ordem da tabela):
  `None=0 Raw=1 JPEG=2 Flate=4 LZW=8 Group3=16 Group3_2D=32 Group4=64
  JBIG2=128 JPEG2000=256 MRC=512 Source=1024`.
  Logo: `Bitonal=128` (JBIG2), `Continuous=2` (JPEG). **Só tenta os tipos da
  máscara e fica com o menor** (`ForceRecompression=False`).
- `ResolutionDPI/ThresholdDPI` valem p/ os 3 tipos (bitonal/mono/cor);
  indexadas **nunca** sofrem downsampling (só recompressão).
- `ImageQuality` 0–100 = Q JPEG IJG direto (**provado**: tabelas de quantização
  do JPEG do original são idênticas às do Pillow q60, 4:2:0).
- `Strip(127=0x7F)` = Threads|Metadata|PieceInfo|StructTree|Thumb|Spider|Alternates
  (combinação canônica do próprio manual antigo).
- `Strip(1143=0x477)`: bits {0,1,2,4,5,6,10}. **Comportamento observado em 8
  saídas reais não bate com "Metadata+StructTree+FormsAnnots"** (docinfo, XMP,
  StructTree e links visíveis são mantidos). A réplica implementa o
  **comportamento observado**: remove threads/pieceinfo/thumbs/spider/
  alternates/invisíveis; mantém o resto (docinfo com datas+Producer atualizados,
  XMP re-carimbado). Ver §5.

## 4. Descobertas em 21 saídas reais do iLovePDF (REA-lab, 7 docs × 3 níveis)

1. **JPEG embrulhado**: `Filter=[/FlateDecode /DCTDecode]`,
   `DecodeParms=[None {Quality: Q}]` — camada Flate externa sobre o JPEG
   (confirmado via `zlib.decompress` → `FFD8`). Réplica idêntica. As tabelas de
   quantização são as do IJG para o `Quality` dado (Pillow q60 = idênticas).
2. **Downsample exato**: `novos_px = tamanho_pt/72 × ResolutionDPI`, aplicado
   quando `DPI_efetivo > ThresholdDPI`. DPI efetivo vem da CTM do `Do`
   (inclusive dentro de Form XObjects).
3. **ReduceColorComplexity**: imagem RGB sem saturação vira `/DeviceGray`.
4. **RemoveStandardFonts (Low e Extreme)**: a fonte embutida equivalente a uma
   padrão‑14 é **substituída** pelo dicionário mínimo
   `{Type, Subtype=/Type1, Encoding, BaseFont=/Times-Roman}` — sem `/Widths`,
   sem `/FontDescriptor`. Métricas da padrão‑14 são idênticas
   (TimesNewRoman↔Times, Arial↔Helvetica), então o layout não muda.
   ⚠️ O qpdf **grava objetos inalcançáveis**, então os programas de fonte
   desanexados precisam ser zerados explicitamente.
5. **Fontes Type0/CID**: não são trocadas por padrão‑14; são **re‑subsetadas**
   mantendo a numeração de CID (só o `/CIDToGIDMap` é reconstruído).
6. **Fontes compartilhadas**: um mesmo `/FontFile2` pode ser usado por uma
   fonte simples e por um Type0 — é obrigatório **clonar o stream** antes de
   subsetar, senão uma corrompe a outra.
7. **Strings que começam com `/`**: o texto pode conter `"/Dúvidas"`; um
   tokenizador que descarta operandos "que começam com `/`" perde caracteres.
   Sempre distinguir por **tipo de token**, nunca pelo conteúdo.
8. **ClipImages**: imagens parcialmente fora da área de clip são recortadas
   (ex.: 620×1386 → 600×496). O clip precisa ser rastreado já em espaço de
   página (CTM aplicada no momento de cada ponto do path) e o clip em espaço
   unitário (posterior ao `cm`) deve ser removido depois do recorte.
9. **Marcadores de conteúdo**: com `/StructTreeRoot` removido, os
   `BDC/BMC/EMC` sem `/OC` são inúteis e custam ~12% do content stream.
10. **Metadados**: docinfo mantido (Producer e datas atualizados); XMP
    substituído por carimbo mínimo.
11. **Fontes re‑subsetadas por nível** (amostra): Times 4731 → 216 glifos
    (deles) vs 219 (nosso).

### Resultado do A/B (21 combinações, `REA-lab`)

| métrica | nosso | iLovePDF |
|---|---|---|
| tamanho total | **4.091.105 B** | 4.203.565 B (**−2,7%**) |
| menor em | **21 / 21** casos | 0 |
| diferença média de render | **0,081%** | 0,155% |
| casos com qualidade pior | **0** | — |

Texto extraído e hyperlinks: **idênticos ao original em todos os 21 casos**.

### Ajustes finais de fidelidade (2ª rodada)

12. **Compactação de content stream**: `1 0 0 1 tx ty Tm` → `tx ty Td`
    quando a matriz de linha é identidade; separadores mínimos; `\n`.
    Aplicado **só quando o stream fica menor** (em alguns PDFs a formatação
    original do Word comprime melhor) — medido: 6.356 → 6.159 B.
13. **Transparência preservada**: `/SMask` é **reamostrada junto** com a imagem
    (BOX, não LANCZOS) em vez de achatada no branco. O motor original mantém a
    máscara (127×167 com SMask em ambas as saídas). Achatá-la mudava a
    aparência de logos com fundo transparente.
14. **Encoding por stream**: máscaras e imagens pequenas usam o menor entre
    Flate+predictor 12 e zlib cru (predictor inflava a máscara: 2.088 → 725 B,
    contra 819 B do original).
15. **Flate como resgate sem perda**: quando nenhum candidato com perda bate o
    original, reencoda em Flate **sem reamostrar** (pixels idênticos). Trocar
    resolução por bytes é proibido: o resgate só vale quando `not reamostrada`.
16. **Subset de CFF/CIDFontType0C**: implementado e **reprovado** duas vezes —
    o subsetter do fontTools renumera os glifos e o charset CID deixa de casar
    com o `/W` e os códigos do conteúdo (8,5%–9,4% de divergência de render),
    mesmo com `retain_gids=True` e `notdef_outline=True`. Fica desligado
    (`_TENTA_CFF = False`); gap residual ≈ 2% nos streams de fonte.
17. **Regra de reamostragem validada empiricamente**: a regra simples
    `DPI_efetivo > limiar` explica **239 de 243** desenhos de imagem nas 21
    saídas. As 4 exceções são todas imagens cujo resultado reamostrado **não
    ficou menor** que o original — o motor mantém bytes *e dimensões*
    originais. Nossa implementação faz o mesmo.
18. **Garantia "nunca maior"**: se a saída não ficar menor (caso real: PDF de
    2.637 B com formulário, onde XMP+docinfo custam mais que o ganho), o
    original é copiado byte a byte e a razão reportada é 0%.
19. **Corpus de estresse** (8 PDFs sintéticos × 3 níveis): página rotacionada,
    imagem indexada (`/P`), transparência RGBA, formulário + link, 25 páginas,
    imagem 2600×3400, caso misto. Resultado: **24/24 sem falha**, nunca maior,
    render ≤ 1,13% (extreme; remedido depois da rodada de paridade).
20. **Filtro de reamostragem identificado: triangular (BILINEAR).** Nos 3 casos
    em que o iLovePDF grava a imagem reduzida **sem perda** (Flate), os pixels
    são exatos e permitem identificar o filtro. Testando os 6 filtros do Pillow
    (com desfoque e tolerância de meio pixel, porque as imagens são quase
    binárias):

    | imagem | BILINEAR | BICUBIC | LANCZOS | BOX | NEAREST |
    |---|---|---|---|---|---|
    | 221×222 → 211×212 | **7,43** | 7,92 | 8,07 | 12,54 | 13,07 |
    | 222×223 → 175×176 | **5,30** | 5,78 | 5,94 | 9,47 | 9,00 |
    | 222×223 → 207×208 | **7,21** | 8,10 | 8,25 | 14,54 | 14,54 |

    Bilinear vence nos três. Efeito medido ao trocar o kernel das fotos:
    arquivos **0,2%–5,6% menores** (ex.: DL7107 rec 109.638 → 103.501),
    com perda leve de nitidez. Como a régua do usuário é "qualidade parecida,
    tamanho nunca maior", o padrão segue **LANCZOS** (mais nítido e já menor que
    o original) e a paridade exata fica disponível em
    `COMPRESSPDF_KERNEL=bilinear`.
21. **Fontes CFF já vêm subsetadas pelo produtor.** Investigando a fundo por que
    elas eram 2% maiores que as deles: a fonte `/Calibri` tem 45 glifos e o
    conteúdo usa 44 CIDs — **todos** com correspondência 1:1 no charset
    (`cid00003`, `cid00018`, …). Não há glifo sobrando para remover; os 2% são
    apenas diferença de compressão do stream CFF. Tentativas de subset com
    fontTools (inclusive `retain_gids`) e de esvaziar charstrings não usados
    foram descartadas: a primeira quebra o charset CID (−8,5% de render) e a
    segunda não tem o que ganhar. `_TENTA_CFF` fica `False`.
22. **Bug de uso de fonte corrigido**: `_usos_por_fonte` descartava as
    ocorrências seguintes de uma mesma fonte (ficava só com os códigos da
    primeira página), o que podia apagar glifos usados em outras páginas. Agora
    os conjuntos de códigos são **somados** por fonte.
23. **Escolha dupla de kernel por imagem.** Como o motor usa filtro triangular
    (bilinear) e nós usávamos Lanczos, passamos a gerar **as duas versões** e
    ficar com a que produz o menor JPEG. Efeito medido:

    | métrica | antes (só Lanczos) | depois (mín. dos dois) |
    |---|---|---|
    | total das 21 saídas | 4.091.002 B | **4.038.609 B** |
    | vs iLovePDF | −2,7% | **−3,9%** |
    | maior ganho | — | NS8002/extreme −5,4%, DO3877/rec −7,5% |

    Em `recommended` o bilinear costuma vencer **e** fidelizar mais (diff cai de
    0,071% para 0,003% em AP5439); em `extreme` o Lanczos às vezes comprime
    melhor porque preserva bordas. Nunca aumenta o arquivo: se nenhum dos dois
    bater o original, a imagem original é mantida.
24. **Rede de segurança recalibrada (2ª vez)**: limites 2% (rec/low) e 4%
    (extreme) a 110 dpi. Os defeitos reais que ela precisa pegar produzem
    8–9% de divergência; limites muito apertados revertiam o `ClipImages` por
    diferença legítima de kernel e **aumentavam** o arquivo.
25. **Re-análise na versão 2.3.6** (a instalada hoje):

    | arquivo | SHA-256 | conclusão |
    |---|---|---|
    | `PdfOptimizeAPI.dll` | `d74e91de…3a83` | **idêntico** à 2.3.4 — motor não mudou |
    | `iLovePdfTools.dll` | `802937db…a4e2` | mudou, mas os 3 presets são **iguais** |

    Re-disassembly dos presets: todos os 14/6/10 parâmetros batem. E
    `PdfOptimizeSetImageStratConserv` / `SetForceRecompression` **não são
    sequer importados** pelo wrapper — o motor roda com os defaults (elimina a
    hipótese de "estratégia conservadora" para os arredondamentos de 1 px).
26. **JBIG2: o motor codifica, nós não (ainda).** `PdfOptimizeAPI.dll` contém
    `CJBIG2EncodeFilter` + `CJBIG2Globals` (além do decoder), ou seja
    `BitonalCompressions(128)` = JBIG2 é usado **na codificação** quando vence.
    Nós usamos CCITT Group 4 (sem perda) porque não há encoder JBIG2
    open-source na máquina: sem `jbig2enc`, sem Ghostscript; o ImageMagick só
    decodifica. Impacto: **zero nos 7 PDFs de teste** (nenhum tem imagem
    bitonal), mas em documentos com muitos scans P&B o iLovePDF tende a ficar
    30–40% menor nessas imagens. Medida de referência: scan 1073×1518 em G4 =
    **1.643 B**.
    **Gancho implementado**: `_jbig2_bytes()` detecta o binário `jbig2`
    (`jbig2enc`) no PATH, gera símbolos + página e monta `/JBIG2Decode` com
    `/JBIG2Globals`; o candidato entra na disputa e só vence se for **menor**
    que o G4. Sem o binário, o comportamento é idêntico ao anterior.
27. **PDF-sonda** (`REA-lab/_sonda/sonda.pdf`) construído para exercitar as
    regras deduzidas: texto tagueado + formulário + anotação + link, scan P&B
    A4, escada de DPI (200/267/317/417) e imagem com alfa. As predições da
    regra de reamostragem bateram **100%** na execução (ex.: 1250×900 @463 dpi
    → 405×292 no recommended, 194×140 no extreme).
28. **PSNR por imagem revelou 2 bugs reais.** Comparando as 158 imagens dos 21
    pares (nosso × deles, ambos contra o original):

    - **Flate com preditor**: o candidato Flate usava sempre PNG+predictor 12;
      em imagens pequenas o zlib cru é menor. Medido em 713×128: JPEG+Flate
      5.944 B (com perda) contra **Flate puro 5.794 B** do motor — éramos
      maiores **e** com perda. Agora `tenta_flate()` usa `_flate_menor()`
      (menor entre preditor e zlib cru) e a imagem passou a sair lossless.
    - **Perda de cor**: `_e_cinza()` amostrava um downsample BICUBIC 32×32; a
      média escondia cor. Imagens com listras coloridas finas (saturação real
      184) eram classificadas como cinza e viravam `/DeviceGray` — **PSNR
      20,9 dB** contra o original, enquanto o motor as mantém em RGB.
      Agora usa amostragem NEAREST (até 256×256) e limite estrito (≤ 8 de
      diferença entre canais). As 4 imagens afetadas passaram a **PSNR 99 dB**
      (idênticas ao original), custando +1,3 KB.

    Resultado medido (remedido na rodada de paridade, 158 imagens): PSNR médio
    **33,22 dB** contra 30,79 dB do iLovePDF e **zero** casos >0,5 dB pior
    (antes eram 6).
29. **Tamanho por imagem: nenhuma ineficiência.** Comparando o tamanho de cada
    imagem em que as dimensões coincidem (nosso × deles, 21 pares × 2 níveis):
    **zero imagens** em que somos mais de 8% maiores. O delta fica entre −7% e
    +8%, com a maioria abaixo de zero. Fecha a hipótese de diferença de encoder
    (chroma subsampling, preditor, otimização de Huffman) — não há o que
    corrigir nesse eixo.
30. **XMP: o motor sempre REGENERA, não preserva.** Os 6 documentos policiais
    têm XMP de 1.343 bytes assinado pela `3-Heights XMP Library` **já no
    arquivo original** — ou seja, passaram por iLovePDF antes. Isso dava a
    impressão de "preservação com datas atualizadas". O `teste.pdf`, cujo XMP
    é do Word (3.145 bytes), sai do motor com **1.414 bytes** (stamp novo).
    Conclusão: o motor descarta o XMP alheio e escreve o dele. Nosso carimbo
    mínimo (857 B) cumpre o mesmo papel e é menor. Tentativa de preservar o XMP
    original deixava o `teste/extreme` **0,7% maior** que o deles, então foi
    revertida — a regra "nunca maior" vem antes da arqueologia de metadados.
31. **Layout de texto: deslocamento zero (ou idêntico ao do motor).** Comparei
    a bounding box de **cada palavra** (cerca de 9.000 palavras por nível) entre
    original, nossa saída e a deles:

    | documento | deslocamento máx. nosso | deles |
    |---|---|---|
    | 5 documentos com fonte própria | **0,00 pt** | 0,00 pt |
    | `teste.pdf` (fonte substituída) | **2,43 pt em 422/426 palavras** | **2,43 pt em 422/426** |

    Nos documentos com fonte embutida o layout é **bit-exato**. No `teste.pdf`,
    onde os 3 níveis trocam a fonte pela padrão‑14, o deslocamento é de 2,43 pt
    — e é **exatamente o mesmo número, na mesma quantidade de palavras**, que o
    iLovePDF produz. Prova de que a substituição TimesNewRoman→Times‑Roman
    replica as métricas do motor. Zero casos onde deslocamos mais que eles.

## 4b. Limitações honestas da réplica

- **JBIG2** (encode) sem codificador open-source → fallback **Group4**
  (sem perda; arquivo um pouco maior nesse caso). Censo do corpus (7 PDFs,
  9,05 MB): **0% de imagens bitonais** — 84,8% dos bytes de imagem são scan
  RGB 8-bit em Flate e 14,7% JPEG. JBIG2 não renderia byte nenhum nestes
  documentos; o gap fica aberto só para PDFs genuinamente bitonais.
- **Bit 10 do `Strip(1143)` — RESOLVIDO por REA/Ghidra 12.1.4** (não é strip
  de conteúdo). Evidência: `PdfOptimizeSetStrip` (`0x180027d20`) grava a
  máscara em `handle+0x1440`; a **única** leitura da máscara no binário é
  `FUN_1800b00e0` (pré-save), instrução `0x1800b01ae` →
  `test dword ptr [doc+0xBE8], 0x400` (bit 10) e `& 8` (bit 3), alimentando
  diagnóstico (códigos `0x1401`, `0x1702`, `0x1712`) — não há laço de remoção
  ligado a esses bits. O corpus **não tem nenhuma anotação invisível** (todas
  são `/Link`, nenhuma com `/F` bit 1), logo a implementação anterior
  ("remove anotação invisível") era fidelidade inventada e foi removida.
- **Docinfo é preservado nos 3 níveis** (21 saídas reais: `Author`, `Creator`,
  `Title` continuam; só datas e `Producer` mudam). O `Metadata` do `Strip`
  remove o XMP do catálogo, que é **re-carimbado** com um fluxo próprio — o
  iLovePDF extreme também deixa `/Metadata` (XMP da 3-Heights, 1.414 B).
- **`/MarkInfo` sai junto com o `StructTree`** no extreme: nenhuma saída de
  referência tem a chave (antes ficava `Marked=false` e divergia nas 7
  combinações).
- **Reamostragem**: o motor usa filtro triangular. Fotos agora reamostram
  com BILINEAR (a variante NEAREST/BOX só vence se o stream final — JPEG
  **ou** Flate — ficar menor). LANCZOS era escolha nossa: o ringing encarecia
  o caminho sem perda (AP5439 pg1: 2.574 B contra 775 B do iLovePDF).
- **Redução de cor vale sempre que a imagem é re-codificada** (não só quando
  reamostrada): o motor converte as 456x260/461x292/474x270 do DO3877, que não
  são reamostradas, e só não converte a `/Im150` porque nela o JPEG não ficou
  menor e ele manteve o original.
- **Não existe "Flate de resgate"**: o motor respeita o perfil. Em extreme e
  low o contínuo é só JPEG; oferecer Flate nesses níveis produzia um
  `DeviceGray`/Flate onde ele devolve o original.
- **Corte de 1 polegada (≈60 pt) no lado menor desenhado**: imagem desenhada
  menor que isso não é reamostrada (NS8002 pg6: 150x55 e 152x21 intactas; a
  menor reduzida do corpus tem 61 pt).
- **Alvo em float32**: o motor guarda o dpi efetivo em `float` e calcula
  `px*res/dpi`; reproduzir o float32 acerta os ±1 px (GM9477 pg1 → 241x160).
- **ClipImages arredonda para cima**: ao recortar a imagem (620x1386 →
  620x787 no NS8002), o alvo cai em 314,14 e o `round` normal daria 314; o
  motor não perde a última linha e usa `ceil` em imagem recortada → 315.
  Era o último pixel que faltava (extreme `248x315`, recommended
  `516x655`/`600x496`).
- **Subset com `/CIDToGIDMap /Identity` (corrigido em 12/11)**: o código pulava
  esse caso (`if c2g is None or isinstance(c2g, Name): continue`), então
  Type0/CIDFontType2 com mapa Identity mantinha o programa inteiro. Caso real
  (`REA-lab\x\x.pdf`): ArialMT 101.823 → 7.126 B e Wingdings 15.192 → 4.954 B;
  o arquivo caiu de 238.175 → 132.590 B no recommended (iLovePDF: 101.754).
  O mapa é reconstruído como stream depois do subset.
- **Política de subset = a do motor (novo padrão)**: `retain_gids=True`
  (GIDs originais), `hinting=True` (fpgm/prep/cvt) e `drop_tables=[GPOS,GSUB,
  GDEF]` com `layout_features=[]`. Evidência no `x.pdf`: os subsets do iLovePDF
  têm exatamente as contagens por GID 218/178/857/896/856/30 e só as tabelas
  `glyf/fpgm/prep/cvt/hmtx/loca/name`. Resultado: 95.472 B (recommended),
  97.941 (low) e 75.854 (extreme) contra 101.754/101.760/78.689 deles —
  −6,2%, −3,8% e −3,6%. `COMPRESSPDF_SUBSET=compacto` volta à política
  agressiva (sem hinting, mantém GPOS/GSUB): menor arquivo, mesma renderização
  medida, mas sem o hinting do motor.
- **Corte de imagem só vale para dpi moderado**: desenho com lado menor < 60 pt
  não é reamostrado quando o dpi efetivo é < 150 (NS8002: 150x55 a 116 dpi e
  152x21 a 123 dpi ficaram intactas); acima disso o motor reduz mesmo pequeno
  (x.pdf: 48x45 pt a 199 dpi → 48x45, igual ao deles).
- **Imagem degenerada (< 1 pt desenhado)**: nos perfis de limiar ≤ 150 o motor
  grava `1x1` sem filtro (x.pdf: `1x656` desenhada em 0,12×276,6 pt); no low
  (limiar 400) mantém o original. Replicado — nosso `1x1` ainda sai com
  `FlateDecode` (9 B) por causa do `compress_streams` do pikepdf, contra 1 B
  cru do motor.
- **Tag de subset nas Type0**: `_subset_fontes_cid` agora renomeia para
  `ABCDEF+Nome` (antes ficava sem tag) e, com `retain_gids`, mantém
  `/CIDToGIDMap /Identity` em vez de criar um stream — 1 objeto a menos por
  fonte, como o motor faz.
- **Limitações que restam** (medidas): **21/21 combinações estruturalmente
  idênticas** às do iLovePDF e **nenhum arquivo maior** (total −3,9%).
- Sem `MergeEmbeddedFonts`/`ConvertToCFF`, sem MRC, sem `ClipImages` de paths
  curvos (só retangulares — os demais são ignorados por segurança).
- Rede de segurança: após comprimir, o render é comparado com o original; se
  divergir acima do limite, refaz sem `ClipImages`.
- Execução do `PdfOptimizeAPI.dll` via `ctypes` bloqueada por licença
  (`OpenW` → `0x8A120002`); validação foi por A/B externo.
- DLL copiada p/ `%TEMP%` só p/ análise local (não redistribuída); chave de
  licença do iLovePDF **nunca extraída nem usada**.

---

## 5. Rodada `processo.pdf` — 34 MB, 376 páginas (TJSP/SAJ)

Documento real fora do corpus do gate, usado como caso de estresse.
Alvo: `lab/processo-compressed.pdf` (saída *recommended* do iLovePDF,
12.227.010 B) a partir de `lab/processo.pdf` (34.070.740 B, 376 páginas,
676 imagens, 1.219 fontes, 214 assinaturas digitais).

| etapa | nosso | iLovePDF |
|---|---|---|
| antes desta rodada | 15.451.230 B | 12.227.010 B |
| depois | **12.244.996 B (−64,0%)** | 12.227.010 B |
| extreme | 9.441.093 B (−72,3%) | — |
| low | 18.107.616 B (−46,9%) | — |

Texto extraído: **idêntico ao original nas 376 páginas**. Render contra a saída
do iLovePDF: 0,000% na maioria; ≤0,11% nas páginas com máscara 1-bit (o motor
reduz a máscara à metade, nós mantemos a resolução — 378 KB a mais de máscara
do lado dele, compensados por 411 KB a menos em imagens).

### Causas-raiz (todas medidas, cada uma virou código + teste)

1. **`keys()` num array não levanta em pikepdf 10.18** — devolve `[]`. Todo laço
   "tenta `keys()`, cai para iteração" tratava `/Kids`, `/Annots` e `/ProcSet`
   como dicionário vazio e **parava a varredura ali**. Fix: `_tipo_obj()` lê
   `obj._type_name` ('dictionary'/'stream'/'array').
2. **Assinaturas digitais**: o iLovePDF remove os 214 widgets `/FT /Sig` (com o
   carimbo `/AP` visível) e os 214 dicionários `/Type /Sig` (1,08 MB de
   `/Contents`). `_remove_assinaturas()` replica em recommended/extreme; low não
   tem `Strip` e mantém. Efeito visível: o selo "ASSINATURA DIGITAL" sai da
   página, exatamente como na saída de referência.
3. **Charprocs Type3**: o mesmo glifo aparecia **16×** (uma cópia da fonte por
   página). Dedupe por conteúdo → 967 glifos distintos, o número exato do
   iLovePDF (`_consolida_charprocs`).
4. **Programas de fonte**: dedupe por conteúdo (`_consolida_programas_fonte`) e
   subset das fontes que vivem **só** no `/Resources` de um Form XObject — o
   laço olhava apenas `page.Resources` e deixava uma Calibri de 79 KB inteira.
5. **Referências fora de `/Resources`**: imagem/fonte também aparecem em
   `/SMask`, `/Alternates`, `/CharProcs`, `/AP`. `_reaponta_tudo()` varre
   `pdf.objects` inteiro, descendo **só em containers diretos** (o grafo tem
   ciclos em `/Parent`; recursar em indireto estoura a pilha).
6. **Flate nível 9**: o qpdf grava em nível 6. Recompressão própria +
   `save(..., recompress_flate=False)` = 75.442 B em `processo.pdf`.
   ⚠️ `Object.write(zlib_data)` **sem** `filter=` faz o pikepdf comprimir de
   novo (dupla compressão, content stream ilegível); o correto é
   `write(zlib_data, filter=Name("/FlateDecode"), type_check=False)`.
7. **Tabelas da fonte**: o motor descarta `hdmx/VDMX/gasp/kern/LTSH/PCLT/DSIG`
   e deixa a tabela `name` com **7 registros** (IDs 0–6, Windows, idioma 0x409).
   Nosso subset mantinha todas as línguas: 11.906 B contra 378 B numa ArialMT
   de 52 glifos. Só isso valeu 111 KB.
8. **Imagem inline `BI … ID <binário> EI`**: o tokenizador não a conhecia, o
   binário virava "tokens" e **o resto da página deixava de ser lido**; as
   fontes da página eram consideradas sem uso e **apagadas** (pg337/338/363:
   render 3,9–8,7% diferente, texto extraído virando lixo). Fix:
   `_mascara_imagens_inline()` (mesmo comprimento, offsets preservados) + regra
   "nunca esvaziar um `/Font`" como rede de segurança.
9. **`/ToUnicode` faz parte da identidade da fonte**: duas cópias do MESMO
   programa com CMap diferente desenham igual mas **extraem texto diferente**
   ("Laudo" saía "/audo"). `_assinatura_fonte()` passou a incluir o CMap.
10. **Prefixo de subset determinístico**: `_tag_subset()` deriva as 6 letras do
    `/ID` do trailer. Antes o prefixo era sorteado e o mesmo input produzia
    arquivos com 10–30 KB de diferença (impossível comparar rodadas).
11. **`extreme` falhava** em páginas com imagem inline
    (`don't know how to encode value <PdfInlineImage>`): `_remove_marcadores_mc`
    agora pula essas páginas em vez de reescrever o stream.

### O que ainda difere (honesto)

- **Fontes**: 191 programas (1,77 MB) contra 111 (0,94 MB). O motor funde
  (`MergeEmbeddedFonts`) todos os subsets da mesma fonte-fonte num programa só;
  nós subsetamos por dicionário. Fechar exige subset por união de glifos.
- **Conteúdo**: 21,0 MB descomprimidos contra 16,6 MB do motor — ele reescreve
  o stream inteiro com um serializador mais econômico.
- **Máscaras 1-bit**: o motor as reamostra junto com a imagem; nós mantemos.
  Isso nos deixa *maiores* aí, e as imagens *menores* no total (−411 KB).
- Sem `ConvertToCFF` e sem MRC (fora de escopo, como já documentado em 4b).

### Os tres niveis contra as tres referencias (14/11)

| nivel | nosso | iLovePDF | Δ |
|---|---|---|---|
| recommended | 12.244.996 B | 12.227.010 B | +17.986 (+0,15%) |
| extreme | 9.450.995 B | 9.275.878 B | +175.117 (+1,89%) |
| low | **15.910.221 B** | 16.565.289 B | **−655.068 (−3,95%)** |

Render vs a referencia de cada nivel: pior caso 0,114% (pg338, mascar 1-bit).
Texto: recommended 0/376; low 4/376 e extreme 7/376 (pg 148-151, 179, 209, 221)
— **bug conhecido**: nessas paginas um Type3 aparece no `rawdict` do MuPDF com
nome de fonte VAZIO e os codigos saem como ` ...` ("fls. 1" vira lixo).
O dicionario do Type3 (Encoding/Differences/CharProcs) e' identico ao original
e a' referencia; falta achar quem deixa a fonte irresolvivel no content stream.
Nao afeta render (0,114% igual aos outros niveis).

Achados desta rodada (14/11):

- **Assinaturas saem nos TRES niveis** (medido: 0 `/Type /Sig` e 0 widget
  `/FT /Sig` tambem no low). Antes o low mantinha 214 widgets + 214 /Sig e
  ficava 1,59 MB maior; agora fica 655 KB menor.
- **Fonte padrao sem `/Encoding`**: `_substitui_fontes_padrao` forcava
  `/WinAnsiEncoding`; no ZapfDingbats (encoding embutida) isso trocava o glifo
  e a extracao ("G" -> "l"). Agora, sem `/Encoding`, a chave e' omitida.

### Rodada 3 (14/11, noite) — comparacao com extreme/low reais do iLovePDF

| nivel | nosso | iLovePDF | Δ |
|---|---|---|---|
| recommended | 12.251.998 B | 12.227.010 B | +24.988 (+0,20%) |
| extreme | 9.465.733 B | 9.275.878 B | +189.855 (+2,05%) |
| low | **15.924.556 B** | 16.565.289 B | **−640.733 (−3,87%)** |

Texto extraido vs original: recommended **0/376**, low **0/376**, extreme 3/376
(pg 179/209/221, so acento e espaco de fim de linha: "Oficio" -> "Oİcio").
Render vs a referencia de cada nivel: 0,114% no pior caso (pg338, mascara 1-bit).

Causas-raiz desta rodada:

- **Assinaturas digitais saem nos TRES niveis** (as 3 saidas de referencia tem
  0 `/Type /Sig` e 0 widget `/FT /Sig`). Antes o low mantinha 214+214 (~1,4 MB):
  o nivel passou de +1,59 MB para −640 KB.
- **Assinatura de fonte truncada**: `str()` de um `/Encoding` com 257
  `/Differences` corta a saida, e 3 Type3 DIFERENTES colidiam na mesma
  assinatura (extracao virava ` ...`). Agora `/Encoding`, `/Widths` e
  `/CharProcs` entram por impressao digital sem truncamento.
- **Fonte selecionada por `Tf` conta como usada**, mesmo sem glifo lido: sem
  isso `/R72` era apagado do `/Resources` da pg148 e a pagina ficava sem fonte.
- **Remocao de fonte usava o objgen CANONICO** (pos-consolidacao); se a copia
  canonica nao aparecesse em `usados`, todas as fontes fundidas nela eram
  apagadas. Agora decide pelo objgen ORIGINAL.
- **`/ToUnicode` sobrevive a substituicao por padrao-14**: o mapeamento
  codigo->texto vivia no CMap; sem ele "fls. 1" virava `...`.
- **`MergeEmbeddedFonts` testado e rejeitado**: agrupar por BaseFont e subsetar
  pela uniao de glifos PIORA ~160 KB (medido nos 3 niveis). O motor nao faz
  uniao; cada copia mantem o seu subset. O caminho fica atras de
  `COMPRESSPDF_MERGE` e so funde programas byte a byte identicos.

### Rodada 4 (14/11, madrugada) — Fases 4-6 do plano

| nivel | nosso | iLovePDF | Δ | texto | render |
|---|---|---|---|---|---|
| recommended | 12.103.750 B | 12.227.010 B | −1,01% | 0/376 | 0,1134% |
| extreme | 9.311.583 B | 9.275.878 B | +0,38% | 3/376 | 0,1134% |
| low | **15.738.078 B** | 16.565.289 B | **−4,99%** | 0/376 | 0,1134% |

- **Content streams**: cortes medidos por histograma de operador. O motor tem
  `Tf` 6.451 × 14.114 nossos, `M` 35 × 3.389, `j` 1.923 × 3.978, `c`→`v`/`y`
  29.944 conversões. Implementado no `_normaliza_conteudo`: rastreio de estado
  (com pilha para `q`/`Q` e invalidação em `gs`) e conversão geométrica
  `c`→`v` (ponta inicial == ponto corrente) / `c`→`y` (dois controles iguais ao
  destino). Ganho: 152 KB descomprimidos na normalização; texto segue 0/376.
- **Política de subset**: fonte SIMPLES agora renumera os glifos (o motor tem
  Calibri com **4** glifos onde nós tínhamos 3.874); CID continua com
  `retain_gids` porque o `/CIDToGIDMap` depende disso. Efeito medido: low
  −58 KB, recommended igual, extreme +7 KB (ruído de execução).
- **Máscara 1-bit**: a premissa estava errada — as 58 imagens 1-bit de
  processo.pdf **não são `/SMask`**; o iLovePDF as codifica em **JBIG2**
  (31 delas, 24 KB) e nós em CCITT G4 (111 KB). `_recomprime_mascaras` foi
  implementada e testada (segue valendo para documentos com `/SMask` 1-bit),
  mas neste documento é no-op. **JBIG2 segue bloqueado**: `jbig2enc` não está
  instalado na máquina.
- **Fontes (diagnóstico)**: 48-61 tipos de letra deles contra 66 nossos; a
  diferença não é compartilhamento e sim **renumeração** (subsets menores por
  programa). Agrupar por BaseFont com união de glifos continua **rejeitado**
  (piora ~160 KB).

- **Bug de consolidacao (achado na Fase 7)**: as tres funcoes de consolidacao
  devolviam `0` quando nao havia duplicata; o chamador faz
  `mapa_dup.update(0)` -> `TypeError` silencioso (capturado pelo try), entao a
  fase inteira era PULADA. Corrigido para `{}`: −141 KB no recommended e
  −34 KB no extreme.
- **Paralelismo do subset REJEITADO**: `ProcessPool` com 164 grupos deu 151,9 s
  contra ~150 s em serie (serializar os programas para os workers come o
  ganho). O worker `_subset_programa` fica no codigo, o pool desligado.

### Perfil de tempo (T7.1 do plano) — processo.pdf, recommended, 146,5 s

| bloco | tempo | % |
|---|---|---|
| `[3]` imagens (503 imagens, 383 recomprimidas) | **82,0 s** | **56%** |
| subset de fontes (164 programas) | **52,5 s** | **36%** |
| consolidações + remapeamento | 2,6 s | 1,8% |
| `[5]` save (`object_streams` + flate 9) | 8,0 s | 5,5% |
| strip/normaliza/unifica/carimbo | ~1 s | <1% |

Conclusão: o gargalo é **imagem**, não fonte (a intuição dizia o contrário). O
`ProcessPool` no subset não compensa (151,9 s x ~150 s) porque o custo é
serializar os programas. Para atacar os 82 s de imagem seria preciso
decodificar/encodar em processo separado — o `pikepdf.Object` não é picklable,
então teria de passar bytes + parâmetros e reescrever o resultado no processo
principal. Fica como próximo passo, fora deste plano.

**Variância de execução**: o mesmo código produz 12.096.302–12.103.750 B
(~7 KB) entre rodadas; o gate usa tolerância (1.000/1.015/0,990) em vez de
exigir byte exato.

### Rodada 5 — velocidade: usar os núcleos (o que o motor faz)

Evidência no binário (`PdfOptimizeAPI.dll`): importa **`libomp140.x86_64.dll`**
(`__kmpc_push_num_threads`, `omp_get_thread_num`) e usa `CreateThread` /
`_beginthreadex` — o motor roda com OpenMP nos 36 núcleos. Nós rodávamos em um.

**Perfil instrumentado** (recommended, 376 pág.):

| bloco | antes | depois |
|---|---|---|
| `[3]` imagens | 82,6 s | **70,0 s** |
| — decode (`pikepdf.PdfImage`) | 1,5 s | 1,5 s |
| — encoders (JPEG/Flate/G4) | 35,3 s | 35,6 s (agora em pool) |
| — resize/convert/análise de cor | ~45 s | ~33 s |
| subset de fontes | 52,5 s | **47,1 s** (em lotes) |
| **total** | **146,5 s** | **128,9 s (−12%)** |

O peso **não** está no decoder (1,5 s) e sim no trabalho de pixel e nos
encoders — todos PIL/numpy/zlib, que **liberam a GIL** e portanto podem ir para
threads.

O que foi feito:

- `_em_paralelo()` + pool de threads (`PDFAGENT_THREADS`, default
  `min(8, cpus)`): roda callables PUROS em paralelo. `pikepdf` continua
  exclusivamente na thread principal — o `Pdf` não é thread-safe.
- Candidatos de imagem e as duas variantes de kernel passam pelo pool.
- Subset de fontes em **lotes** (`PDFAGENT_LOTE_FONTE`, default 8): a tentativa
  anterior com 1 tarefa por grupo (164) perdia para o custo de serializar;
  agrupada, ganha 5,4 s.
- `opts`/`tt.recalcTimestamp = False`: a saída ficou **determinística** (antes o
  fontTools gravava `head.modified` = agora em 85 programas, ±1-2 B por rodada).
- `scripts/compara_saidas.py`: prova que a otimização não mudou a saída
  (0 objetos estruturais diferentes; só o XMP e o docinfo com as datas novas).

**O que falta para chegar aos ~60 s**: o ganho contido é limitado porque cada
imagem tem 1-2 candidatos. Para usar os 36 núcleos é preciso o **pipeline por
imagem**: decodificar na thread principal (1,5 s total), mandar
resize/convert/encoders para o pool em janelas e aplicar em série. Estimativa:
70 s → ~15 s, total ~75 s.

### Rodada 6 — pipeline por imagem (o que a medição mostrou)

O pipeline foi feito: `_recomprime_imagem` virou três fases —
`_prepara_job` (thread principal: early-returns, DPI, decode), `_processa_job`
(thread: resize, kernel, cor, encoders — devolve **dados + `meta`** em vez de
closures) e `_aplica_job` (thread principal: `/SMask` e candidato vencedor).
O laço de `comprimir` mantém uma janela de K imagens (`PDFAGENT_JANELA`,
default = nº de threads): prepara, submete e aplica na ordem de preparo.

| bloco | antes | agora |
|---|---|---|
| `[3]` imagens (fase inteira) | 82,0 s | **40,1–40,7 s** |
| — `_tamanhos_na_pagina` (mapa de DPI, fixo) | 16,0 s | 16,0 s |
| — trabalho de imagem de verdade | **59 s** | **24 s** |
| subset de fontes | 52,5 s | 47,1 s |
| **total** | **136,2 s** | **102,4 s** (100,9–102,4 em 3 rodadas) |

**O teto é a GIL, não o número de threads.** Com `PDFAGENT_THREADS=8` o pool
fica ocupado 23,8–24,1 s para 63 s de trabalho serial (2,6x); com 16 threads a
fase faz 42,3 s (pior). Ocupação média de só 1,6 job simultâneo, apesar
de 8 workers e pico de 8 concorrentes. Micro-banco com a mesma imagem em 32
jobs escala 8,7x em 8 threads; no corpus real, o job mediano é 0,03 s (glue de
Python domina) e os grandes são poucos. Conclusão: mais threads não resolve;
o próximo salto exige **processos** (passar bytes+parâmetros, não `pikepdf`).

Duas correções de fidelidade/velocidade que saíram junto:

- **Memo por job**: `_custo_variante` já codifica a variante vencedora para
  comparar, e `tenta_jpeg`/`tenta_flate` recodificavam o MESMO objeto (3 JPEG +
  3 zlib por imagem reamostrada). O cache é (tag, `id`), guardando a imagem
  junto — o `id` não recicla dentro do job. Mesma saída, −6,8 s na fase.
- **Objeto repetido** (32 dos 503 no corpus): a janela é esvaziada antes de
  re-preparar um `objgen` já em voo, para a 2ª ocorrência decodificar o estado
  já aplicado — a semântica da versão em série, mesmo que uma etapa futura
  deixe de ser idempotente.
- `scripts/compara_saidas.py` passou a classificar `/Type /XRef` como metadado:
  o stream de cross-reference carrega `/Info` (datas) e `/ID`, então varia 1-2 B
  por execução e o gate acusava "diferença estrutural" onde só havia timestamp.
- `tests/test_pipeline_imagens.py`: janela=4 tem de produzir os mesmos bytes que
  janela=1, e a `/SMask` tem de ter o tamanho da mãe depois do pipeline (a
  escrita da máscara é a única parte móvel de thread — provado que o teste
  falha se ela for desligada).

### Rodada 7 — JBIG2, e o bug de render que ele desenterrou

**JBIG2 (encoder de terceiro)**: `tenta_jbig2` existia desde sempre e nunca
rodava (`shutil.which("jbig2")` vazio). Compilado do fonte
(`agl/jbig2enc`) com MSYS2 **portátil** em `%LOCALAPPDATA%\msys2_jb` (não há
compilador na máquina; `C:\msys64` é do usuário e não foi mexido no final) e
empacotado com as 19 DLLs em `%LOCALAPPDATA%\PDFagent\tools\` — `_acha_jbig2()`
procura em `PDFAGENT_JBIG2`, no PATH e em `tools/`.

Dois modos medidos nas 65 imagens 1-bit de `processo.pdf`:

| modo | total | observação |
|---|---|---|
| CCITT G4 (antes) | 692.670 B | — |
| JBIG2 simbólico (`-s -p`) | 442.591 B | 370 KB só de globais (1 dicionário por imagem) |
| **JBIG2 genérico (`-p`)** | **426.048 B** | sem globais, **sem perda** — escolhido |

O genérico escreve em **stdout** (o `-b` só vale no simbólico) e o custo das
globais passou a contar na escolha do candidato (senão o simbólico ganhava em
imagem pequena e o arquivo crescia: 8×6 px, G4 11 B × JBIG2 70+39 B).

**O bug que apareceu no meio**: ao ligar JBIG2, 6 páginas passaram a renderizar
certo — e as mesmas 6 estavam **77% pretas** antes (`processo.pdf` pg116, 117,
135, 179, 218 e mais uma; original 4,1%, motor 5,2%). Causa: `_g4_bytes` gravava
o TIFF do Pillow em **várias strips** (~8 KB cada) e concatenava os bytes. Cada
strip do T6 é autocontido; o leitor de PDF decodifica o stream como fluxo único
→ topo invertido e corpo em branco. Medido a 150 dpi na imagem de referência:
multi-strip 22,9%, uma strip **4,12%** (igual ao original).

- Correção na raiz: `_tiff_g4()` grava o TIFF com `tiffinfo={278: altura}`
  (uma strip). Vale também para as `/SMask` 1-bit de `_recomprime_mascaras`.
- Tabela de polaridade medida (imagem 1240×1754, 1 strip): `BlackIs1=True` sem
  `/Decode` = 4,12% (certo); com `/Decode [1 0]` = 95,89%; `BlackIs1=False` =
  95,89%. O `tenta_g4` estava correto e continua sem `/Decode` — a tentação de
  "consertar" com `/Decode [1 0]` **piora**.
- Vacina: `tests/test_g4_strip.py` (uma strip só + ida-e-volta exata).

**Efeito no tamanho** (`processo.pdf`):

| nível | antes | agora | motor | Δ |
|---|---|---|---|---|
| recommended | 12.096.326 | **12.095.782** | 12.227.010 | −131.228 (−1,07%) |
| extreme | 9.307.797 | **9.277.527** | 9.275.878 | **+1.649 (+0,018%)** |
| low | 15.738.087 | **15.510.050** | 16.565.289 | −1.055.239 (−6,37%) |

**Política por nível (é o que o motor faz, medido nas referências):** o JBIG2
entra em `low` e `extreme` (`"bitonal": ["g4", "jbig2"]`, o menor vence) e fica
**fora do recommended**, onde a referência do motor tem 0 stream JBIG2 e 221 KB
de G4 — tentar JBIG2 ali trocava o filtro e o gate acusava diferença
estrutural. No recommended o ganho veio só da correção das strips.

**Lição de método**: o placar de render anterior ("0,114% de pior caso") não
cobria estas páginas — comparação estrutural e tamanho não pegam polaridade.
Toda mudança em imagem 1-bit agora precisa de render por página.
