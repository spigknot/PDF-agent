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
Texto: recommended 0/376, low 0/376 e extreme 3/376 (pgs **180, 210 e 222**) —
bug conhecido e **nao regressivo**: medido em 22/11 rodando o extreme com a
fusao de fontes desligada (`COMPRESSPDF_MERGE=0`), as MESMAS 3 paginas divergem
do mesmo jeito. Causa: o MuPDF nao resolve o glifo do "i" acentuado do Calibri
(GID 304) — **o proprio original extrai U+FFFD ali** — e o NBSP (`\xa0`) sai como
espaco. Nao afeta render (0,114% igual aos outros niveis).
Vacina: `tests/test_paridade_lab.py` tem a lista explicita das paginas aceitas
(`TEXTO_CONHECIDO`); qualquer pagina NOVA divergindo reprova, mesmo dentro do
teto de 3.

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

### Rodada 21 — o executável rodava tudo em série (111,8 → 65,4 s)

As rodadas 16-20 otimizaram o **CLI**. No `.exe` que o usuário recebe, nada
disso acontecia: `multiprocessing.freeze_support()` nunca era chamado e **todos**
os pools tinham `not getattr(sys, "frozen", False)` — sete pontos. Medido no
onedir da própria árvore:

| fase | .exe (antes) | CLI |
|---|---|---|
| clip (coleta) | 15,9 s | 5,4 s |
| imagens `[3]` | 47,0 s | 30,5 s |
| normalização | 40,3 s | 14,4 s |
| coleta de fontes | 8,3 s | 2,5 s |
| **total** | **111,8 s** | **62,1 s** |

**Correção:** `multiprocessing.freeze_support()` no `__main__` do `app.py` (o
entrypoint do PyInstaller — sem isso o filho reabriria a GUI em vez de rodar a
tarefa) e a decisão virou `_pode_processo()`, que respeita `PDFAGENT_PROC_OFF=1`
e o PORTÁTIL.

**O onefile fica de fora de propósito:** nele o PyInstaller extrai o bundle para
um `_MEIxxxx` a cada processo, então um pool de 24 reextrairia o bundle 24× (o
start do portátil já é ~2,6 s). `_portatil_onefile()` detecta pelo basename do
`sys._MEIPASS` (`_MEI...`); o onedir usa `_internal` e roda com processos.

| | antes | depois |
|---|---|---|
| onedir (instalador) | 111,8 s | **65,4 s** |
| CLI | 62,1 s | 61,5 s (inalterado) |

O `.exe` fica ~4 s acima do CLI porque cada worker reimporta o bundle
(tkinter + pikepdf). Saída do executável: 11.382.226 B, **0 diferenças
estruturais**. Vacina: `tests/test_executavel.py` (freeze_support no entrypoint,
knob e o não-portátil).

**Lição:** otimize o caminho que o usuário roda, não o que o desenvolvedor roda.
Vinte rodadas de ganho (146 → 62 s no CLI) não chegavam ao usuário final, que
recebia 111,8 s.

### Rodada 20 — DPI dentro da passada do clip (e o bug que o gate pegou)

As rodadas 18-19 deixaram duas passadas de pool que liam as MESMAS 376 páginas:
o clip (`_coleta_draws`, parse sem filtro porque `_aplica_clip_imagens` edita
`instrucoes[cm_idx]`) e o DPI (`_tamanhos_na_pagina`, parse com filtro
`"q Q cm Do"`). Cada uma pagava o próprio spawn de 24 processos.

Agora `_draws_pagina` devolve `(draws, dpi)` e `_coleta_draws` devolve
`(draws, dpi_paginas, pacotes)`; `_aplica_clip_imagens` repassa e `comprimir` faz
`usos = _tamanhos_na_pagina(pdf, _dpi_paginas)`. **Dois parses por página, de
propósito**: o do clip continua sem filtro (índice!) e o do DPI continua com o
filtro; o que se economiza é o spawn do segundo pool e uma rodada de pickle.
O pacote de `/Resources` da rodada 19 virou o único empacotamento: a entrada de
imagem agora é `(objgen, w, h)` — `objgen` para o DPI, `w`/`h` para o recorte.

#### O bug: DPI antes do clip é o estado ERRADO (2/21 no gate)

A primeira versão devolvia o mapa agregado, coletado **antes** de o clip rodar.
O gate acusou 2/21 (NS8002 em extreme/recommended, imagens 787×655 e 512×496 px)
— o mesmo padrão da rodada 16, o que fez olhar para o clip na hora.

Causa medida: `_aplica_clip_imagens` **reescreve o `cm`** e **recorta os
pixels**. Em NS8002 o desenho da imagem (182,0) era 553,26 pt de altura e vira
314,14 pt; a (147,0) ia de 643,45 para 237,75. O DPI efetivo (px por pt) muda
junto — e o otimizador só vê o estado pós-clip. Com o mapa pré-clip,
reamostrávamos para o alvo errado (a largura batia, a altura não).

**Correção:** `_coleta_draws` devolve o DPI **por página** e `pacotes = {pi:
pacote}`; quem reescreveu a página re-rastreia o DPI dela com o conteúdo NOVO
(`_dpi_pagina((novo, pac))`) antes de devolver. Só as páginas mexidas pagam esse
custo (2 em processo.pdf, 2 em NS8002). Depois disso o mapa do clip é idêntico
ao medido do zero no pdf já clipado — em processo.pdf (469 imagens) e em NS8002
(15), e a paridade voltou a 0/21.

**Lição:** "mesma página, uma passada só" é seguro para *ler*, mas o DPI depende
de um estado que o clip ESCREVE. Ao fundir fases, perguntar sempre se a segunda
fase lê algo que a primeira altera — e provar a equivalência contra o caminho
antigo (foi o `proto20` que mostrou os draws iguais; o gate mostrou o que o
`proto20` não cobria: o efeito no ARQUIVO).

#### Números

| | antes (v19) | depois (v20) |
|---|---|---|
| `clip: coleta_draws` | 4,4-4,8 s | 5,2-5,8 s (leva o DPI junto) |
| fase de DPI isolada | 1,5-1,6 s (pacotes 0,19 + pool 1,4) | **0** (`dpi: N imagens (do clip)`) |
| run completo, **8 pares alternados** (4 com cada binário na frente) | mediana **62,6 s** (min 61,7) | mediana **62,1 s** (min 60,9) |

Δ médio **−0,35 s** (mediana −0,50; desvio 0,85; erro padrão 0,30; **6/8 pares a
favor**; t≈1,2 — não é significativo com 8 pares). Nas FASES o líquido é −0,4 s
(clip +1,15, DPI −1,55), medido com precisão de ±0,05: o ganho é pequeno e real.

**Uma medição intermediária mentiu:** os primeiros 4 pares (medidos na versão
ainda SEM o fix, e numa janela em que o v19 rodou lento) deram −2,18 s com 4/4 a
favor. Repetidos com o código corrigido e a ordem dos binários invertida em
metade dos pares, o Δ caiu para −0,35 s. **Ordem e janela importam: alterne
quem roda primeiro.**

A saída final é 11.382.226 B, 0 diferenças estruturais, texto 0/376.
O ganho não paga sozinho a complexidade (são ~70 linhas e um acoplamento novo
entre clip e DPI); o que fecha a conta é metade dos spawns de pool por
compressão, que pesa em máquina de poucos núcleos. O commit é separado — se
preferir o código mínimo, `git revert` dele devolve a rodada 19 inteira.

**Vacinas** (`tests/test_dpi_pacotes.py`, 6 testes): geometria do mapa, Form
sem/vazio `/Resources`, pool × serial, `cm_idx`/`do_idx` apontando para `cm`/`Do`
no parse sem filtro, DPI do clip == isolado, e **o caso do recorte**
(200×100 pt → 50×50 pt depois do clip, com o mapa tendo de acompanhar).

### Rodada 19 — DPI efetivo em processos (2,8 → 1,7 s) e a hipótese que caiu

`_tamanhos_na_pagina` custava 2,7 s dos 61,8, decomposto em parse 1,5 s +
rastreio 1,3 s (469 imagens mapeadas). Passou a montar pacotes picklables —
`{"i": {nome: objgen}, "f": {nome: (bytes, /Matrix, pacote do /Resources)}}` —
e a rastrear a CTM em `ProcessPoolExecutor`, com o **mesmo parser**
(`pikepdf.parse_content_stream` com o filtro `"q Q cm Do"`) e um
`pikepdf.new()` local por worker (o parser C++ não aceita bytes soltos).

| | antes | depois |
|---|---|---|
| fase de DPI (isolada, 3 medidas alternadas) | 2,83 s | **1,72 s** |
| fase de DPI no pipeline (instrumentação do próprio código) | 2,8-2,9 s (`parse 1,5 + rastreio 1,3`) | ~1,7 s |
| run completo, **7 pares alternados** v18 × v19 | mediana **63,6 s** | mediana **62,1 s** (Δ médio −1,16 s, 5/7 pares a favor) |

O piso é o spawn do pool (~0,7 s) mais o maior stream (~0,35 s); o resto é
paralelo. **Unificar com o clip** (que já parseia a mesma página) salvaria mais
~1 s, mas exigiria mexer no caminho que guarda `cm_idx`/`do_idx` — descartado
na própria rodada, mesma regra da 16.

**Cuidado com a janela da máquina:** o mesmo código mediu 61,8 s às 11h e
64-66 s às 13h (e há experimentos do usuário rodando em paralelo). Um par de
medianas de janelas diferentes chegou a sugerir ganho zero; com 7 pares
ALTERNADOS (binário antigo × novo, um após o outro) o Δ ficou claro: −1,16 s
médio, desvio 1,15, erro padrão 0,44. **Compare sempre alternando no mesmo
momento**, e confirme pela fase instrumentada, que é imune à deriva.

**A hipótese que a medição derrubou:** mandar o `mapa` de `/Resources` uma vez
por worker (`ProcessPoolExecutor(initializer=...)`) em vez de em cada tarefa. O
mapa pickla 0,58 MB, então a conta parecia óbvia — medido: **6,30 s com
initializer contra 2,38 s com o mapa por tarefa** (2,6× pior). `chunksize=4`
também piorou (4,65 s contra 2,38 s): junta duas páginas grandes na mesma
tarefa e desbalanceia. Ficou mapa por tarefa, `chunksize=1`, ordem por tamanho
decrescente. **Custo de spawn/unpickle em `ProcessPoolExecutor` não escala com
o tamanho do que se manda — medir antes de "economizar pickle".**

**Vacinas** (`tests/test_dpi_pacotes.py`): geometria exata do mapa para imagem
da página (200,100), Form sem `/Resources` (5,5), Form com `/Matrix` 2× (20,20),
`/Resources` **vazio** caindo no pai (o `or cur` do serial) e pool × serial.
`PDFAGENT_DPI_SERIAL=1` para A/B.

### Rodada 18 — a 2ª coleta de fontes: 2,4 → 0,3 s (reuso por assinatura)

A rodada 17 deixou 4,6 s em coleta, e **2,4 s eram da SEGUNDA chamada**.
`_codigos_por_fonte` é chamado de novo por `_consolida_fontes`, que precisa
saber quais fontes são realmente usadas — e roda depois do merge.

**A observação que resolveu:** a fase 3 de `_merge_subset_fontes` grava
`/FontFile2`, `/BaseFont` e `/CIDToGIDMap` **no mesmo objeto de fonte**; não
troca `/Resources` nem conteúdo. Entre as duas coletas, portanto, tudo o que o
walk lê é idêntico — só os objetos de fonte mudam por dentro.

Duas mudanças:

1. O evento do walk passou a carregar o **rótulo do `/Resources`** (caminho
   estável, `"p7/Fm1"`) e o **nome** da fonte, nunca o objgen. Quem resolve é o
   processo principal, no pacote ATUAL — a mesma lista de eventos vale para
   qualquer objeto de fonte, e um objgen trocado não deixa chave morta.
2. `_assinatura_coleta` = (id do `Pdf`, tamanho+crc32 de cada página, e por
   rótulo: nomes de fonte + nome/tamanho/crc32/rótulo-filho de cada Form). Se a
   assinatura bate, os eventos são reaproveitados.

| | antes | depois |
|---|---|---|
| coleta, 2ª chamada | 2,4 s | **0,3 s** |
| coleta, 1ª chamada | 2,2 s | 2,2 s (assinatura inclusa: ~0,1 s) |
| **total recommended** | 64,9 s (com `PDFAGENT_FONTES_CACHE=0`, mesma sessão) | **61,8 s** (mediana de 3; espalhamento 1,2 s) |

**Duas armadilhas pagas aqui:**

- A primeira assinatura usava as CHAVES do memo (objgen/`id()`).
  `pagina.Resources` devolve um wrapper novo a cada chamada, então o `id()` de
  dicionário direto muda entre duas coletas do MESMO arquivo — a assinatura
  nunca batia. O caminho (`"p7/Fm1"`) é estável; o `id()` segue servindo só para
  o dedup DENTRO de uma coleta.
- A assinatura lista NOMES de fonte e bytes, não objgens: foi o que fez a troca
  de objeto de fonte (`test_coleta_ve_troca_de_objeto_de_fonte`) ser detectada
  pelo resultado, e não silenciosamente herdada do cache.

**Vacinas** (`tests/test_coleta_fontes.py`, 7 testes): reuso quando nada muda,
invalidação por conteúdo novo, troca de objeto de fonte e mutação no lugar (a
que o merge faz). `PDFAGENT_FONTES_CACHE=0` desliga o reuso para A/B.

### Rodada 17 — coleta de fontes em processos (71,7 → 67,1 s)

`_usos_e_codigos` custava 8,4 s dos 71,7 e a instrumentação dizia exatamente
onde: leitura dos 21 MB de content stream **0,17 s**, tokenização **7,66 s**
(1.169 streams únicos) e o laço do walk 0,83 s. Nove décimos do custo era
`_tokens_conteudo` na thread principal — o walk não usa
`pikepdf.parse_content_stream`, usa o tokenizador próprio.

Para levar o walk a outro processo só era preciso tornar picklable o que ele lê.
`/Resources` virou `{fontes: {nome: (chave, largura, objgen)}, xobjs: {nome:
(bytes do Form, chave do /Resources filho)}}`, montado na thread principal
(0,16 s), com memo GLOBAL por `/Resources` — o mesmo `vistos_res` do serial: um
`/Resources` compartilhado é visitado uma vez e o Form que cai no `/Resources`
do pai continua sendo pulado (é o que o walk serial faz, replicado de
propósito). O walk é o MESMO código rodando no worker; o principal só reproduz
os eventos na ordem do walk serial (`Tf` citou → entrada vazia; `Tj` achou →
bytes na ordem).

| | antes | depois |
|---|---|---|
| coleta, 1ª chamada | 8,7 s | **2,2 s** |
| coleta, 2ª chamada (pós-merge) | 0,6 s | 2,4 s |
| fase de fontes (`[4]`→`[5]`) | 31,2 s | ~27 s |
| **total recommended** | 71,7 s | **67,1 s** (mediana de 3) |

A 2ª chamada ficou mais cara: no serial ela era quase de graça porque o
`_TOKENS_CACHE` do processo principal já estava quente; no pool cada chamada
paga spawn + pickle e o cache dos workers só acerta se a tarefa cair no mesmo
processo. É por isso que o ganho total (4,6 s) é menor que o da 1ª chamada
(6,5 s).

**A armadilha que custou a rodada: não serializar o `set`.** A primeira versão
devolvia `{chave: set(codigos)}` do worker. Os conjuntos vinham iguais, a
contagem de objetos batia e ainda assim o arquivo saía **20 bytes** diferente:
`_cod2glifo` numera os glifos ITERANDO esse set, e a ordem de iteração de um
`set` de ints depende do histórico de inserção (colisão em open addressing), não
só do conteúdo — `sorted()` esconde exatamente essa diferença. Agora os bytes
viajam crus e o set é montado no processo principal, na ordem dos bytes: os dois
caminhos dão o mesmo retrato, inclusive `list(set)`. É o que
`tests/test_coleta_fontes.py` trava (pool × serial comparando conteúdo **e**
ordem, com Form de `/Resources` próprio, `Tf` sem `Tj` e Tipo0). O item entrou no
`scripts/verificar.py` como "coleta de fontes (pool x serial)".

**Duas tentativas medidas que não ficaram:**

1. **Serializar o set** (acima): 20 B de diferença no programa de uma fonte;
   `compara_saidas.py` acusava um stream trocado. Revertido.
2. **Reusar o pool de imagens para a coleta** (`_pool_proc`, devolveria o
   segundo spawn e o cache dos workers): no CLI funciona e dá 63,3 s numa
   rodada, mas dentro do pool aninhado de `tests/test_paridade_lab.py` os três
   níveis **travam com 0% de CPU** — deadlock de `ProcessPoolExecutor` dentro de
   worker de `ProcessPoolExecutor` no Windows/spawn. Revertido: o pool por
   chamada custa ~0,5 s e é seguro.

**O que sobrou:** imagens 31,3 s (piso de núcleos), `_normaliza_conteudo`
14,4 s (piso do parse+reescrita), coleta 4,6 s (duas chamadas), subset ~3 s,
save ~5 s. O próximo alvo real é a **segunda** coleta: ela existe porque o
`_codigos_por_fonte` reparseia depois que o merge trocou os objetos de fonte.

`PDFAGENT_FONTES_SERIAL=1` força o caminho serial (A/B e o teste de
equivalência).

### Rodada 16 — clip em processos (76,1 → 71,7 s)

O `_coleta_draws` era 11,2 s dos 12,8 s da etapa de clip: parse + rastreio de
CTM/clip das 376 páginas na thread principal. Virou `_rastreia_draws` (função de
módulo) + `_draws_pagina` em `ProcessPoolExecutor`.

**O parser foi mantido igual de propósito** (`pikepdf.parse_content_stream`, sem
filtro): `_aplica_clip_imagens` reparseia a página e edita
`instrucoes[cm_idx]`, então mudar o parser (ou filtrar operadores, como se
tentou antes) desalinha os índices — foi o que derrubou o gate para 2/21.

| | antes | depois |
|---|---|---|
| `_coleta_draws` | 11,2 s | **4,5 s** |
| etapa de clip | 12,8 s | 6,7 s |
| fase `[3]` | 38,5 s | 31,8 s |
| **total** | 76,1 s | **71,7 s** (mediana de 3) |

**O que sobrou, com o custo de cada um:** laço de imagens 22,5 s (~500 s de CPU,
limitado por núcleos), `_normaliza_conteudo` 14,4 s (piso do parse+reescrita),
coleta de fontes 8,4 s e subset 3,5 s. A coleta **não** é paralelizável de graça:
o documento tem **1.162 Form XObjects** e o walk recursa neles — seria preciso
serializar a árvore de recursos por página.

### Rodada 15 — o kernel do bitonal: LANCZOS é mais fiel E menor

A página 218 (9,6% de render vs original) é um **scan de página inteira**
(2480×3507, 1-bit CCITT). Nós e o motor reamostramos para 1240×1754, com
`/DecodeParms` idênticos (`Columns`=largura, `K`=-1) — a diferença estava no
**kernel**: usávamos `Image.NEAREST` num downsample 2:1, que descarta 3 de cada
4 pixels.

Medido nas 376 páginas (`PDFAGENT_KERNEL_BITONAL`):

| kernel | pg218 | pg117 | pg132 | pg116 | média geral | bytes |
|---|---|---|---|---|---|---|
| `nearest` | 9,60% | 4,61% | 3,97% | 4,35% | 0,3248% | 11.386.742 |
| `box` | 10,80% | 4,87% | 4,55% | 4,72% | 0,3312% | 11.379.405 |
| **`lanczos`** | **8,67%** | **3,72%** | **3,42%** | **3,81%** | **0,3131%** | **11.382.226** |

O LANCZOS — redução em cinza (`L`) e binarização depois com limiar 128 — é
**mais fiel nas quatro páginas, melhor na média e 4,5 KB menor**, e o tempo cai
de 77,8 s para **76,1 s** (imagem menor, encode mais rápido). Virou default;
`PDFAGENT_BITONAL_LIMIAR` ajusta o limiar.

**Lição:** o comentário antigo no código dizia que LANCZOS "gera franja cinza
que vira speckle no G4 — 12x maior". Era verdade para o caminho antigo
(LANCZOS direto numa imagem já `1`); convertendo para cinza **antes** e
binarizando **depois** o resultado é menor e mais fiel. O comentário estava
certo sobre o fenômeno e errado sobre a conclusão.

### Rodada 14 — JBIG2 também no recommended (−78 KB) e o bitonal é o que sobra

Com o gate novo (376 páginas contra o original), fui atrás da página 218: é um
**scan inteiro** (2480×3507, 1-bit CCITT). Nós e o motor reamostramos igual
(1240×1754) e o nosso `/DecodeParms` é idêntico (`Columns`=largura, `K`=-1) —
mas o **nosso G4 sai 8% maior** (61.746 × 57.011 B).

Somando as 64 imagens 1-bit do arquivo: **302.685 B nossos × 221.643 do motor
(+81 KB)**. É exatamente o gap que a tabela de papéis de 14/11 apontava como
"+81.604" no recommended.

O JBIG2 estava **desligado neste nível** por uma nota conservadora no código
("o motor tem 0 stream JBIG2 no recommended"). Testado: o gate estrutural do
corpus continua **0/21** e o documento de estresse fica **0/3**.

| | tamanho | bitonal | tempo (mediana) |
|---|---|---|---|
| G4 | 11.464.919 B | 302.685 B | 77,1 s |
| **G4+JBIG2** | **11.386.742 B** | **224.913 B** | 77,8 s |

−78 KB **de graça** (o custo do jbig2enc, 64 subprocessos, ficou dentro do
ruído). `PDFAGENT_BITONAL=g4,jbig2` permite experimentar sem editar a política.

**O que ainda sobra em bitonal**: 224.913 nossos × 221.643 do motor — o gap
fechou. O próximo seria JBIG2 **simbólico** (dicionário de símbolos), medido em
442.591 B contra 426.048 do genérico no arquivo original: **perde** aqui, não
usar.

### Rodada 13 — fidelidade medida no documento inteiro (e o gate corrigido)

O gate de render comparava **10 páginas fixas contra o arquivo do motor**. Duas
descobertas ao varrer as 376 páginas contra o **original**:

1. **O gate punia a nossa fidelidade.** Em 22 páginas ficamos >0,5% longe do
   motor — e em **todas** as 22 estamos mais perto do original que ele:

   | página | nosso vs original | motor vs original |
   |---|---|---|
   | 44 | **0,05%** | 5,23% |
   | 82 | **0,48%** | 5,19% |
   | 218 | **9,60%** | 12,76% |
   | 117 | **4,61%** | 6,14% |

   Comparar com o motor media "parecido com o iLovePDF", não "fiel ao
   original". O critério agora é o original, nas **376 páginas**, com teto por
   nível (média e pior): recommended 0,37%/10,5%, extreme 0,80%/18%, low
   0,45%/2%.

2. **A diferença de AA contra o baseline não é da fusão de fontes.** Medido
   com `COMPRESSPDF_MERGE=0`: 0,3225% (sem) × 0,3248% (com) — 0,0023 pp. O
   resto vem do arredondamento numérico: `COMPRESSPDF_CASAS=6` dá 0,3105%
   (o baseline era 0,3082%), custando +21,6 KB. Com 4 casas: 11.464.919 B e
   0,3248%.

**Placar de fidelidade** (recommended, 376 páginas): texto **0/376**; render
média **0,3248%**, pior **9,60% (pg218)** — onde o motor está em 12,76%.

### Rodada 12 — 75,6 s: os walks repetidos e o piso da normalização

A soma das fases não fechava com o total (38 s de fase de imagem contra 22 s de
laço). O que faltava: **`_aplica_clip_imagens` (12,8 s)** e, dentro dele,
`_coleta_draws` (11,2 s) fazendo um parse **sem filtro de operadores** — o
quarto walk completo do documento (normaliza, DPI, fontes e clip parseiam tudo
separadamente).

| mudança | efeito |
|---|---|
| ~~`_coleta_draws` com filtro de operadores~~ | **revertido**: 11,2 → 9,0 s, mas quebrou o gate (2/21) |
| `_tamanhos_na_pagina` instrumentado (parse 1,4 s + rastreio 1,2 s) | não era gargalo |
| pool de processo derivado de RAM (`_workers_processo`) | segurança em máquina pequena |
| `PDFAGENT_PROC_NORM=0` para comparar | serial 37,9 s × pool 14,9 s |

**Por que o filtro foi revertido**: `_coleta_draws` guarda `cm_idx`, a POSIÇÃO
da instrução `cm` no stream, e `_aplica_clip_imagens` reparseia a página **sem**
filtro para editar exatamente aquela posição. Com o parser filtrado os índices
desalinham, o clip edita a instrução errada e a paridade estrutural do corpus
cai para 2/21 — com 0/3 no documento grande, ou seja, o gate pequeno é que
pegou. Economizar 2,2 s não paga esse risco.

**A normalização tem piso de ~14 s** e não escala de 12 para 24 workers: o
custo está na serialização dos content streams (20 MB descomprimidos) e no
próprio `pikepdf.ContentStreamInstruction`, não em CPU. Para descer disso seria
preciso um parser próprio bytes→bytes — anotado como próximo passo, não feito.

**Render**: a divergência de 0,114% está espalhada em 1.411 pixels por 10 faixas
da página 339 (0,04–0,26% em cada). É antialiasing de glifo, **não** máscara
1-bit como se supunha — não há o que "replicar" do motor ali.

### Rodada 11 — 76,6 s: o gargalo escondido era a normalização de conteúdo

Instrumentando as fases (`PDFAGENT_DEBUG_TEMPO=1`) apareceu o que o perfil
anterior escondia: **`_normaliza_conteudo` custava 42,6 s** dos 111,5 s — o
maior bloco depois das imagens — enquanto o subset de fontes, que eu tratava
como gargalo, custava 3,5 s. E a coleta (`_codigos_por_fonte` +
`_usos_por_fonte`) custava 11,6 s por fazer **dois walks completos** do conteúdo.

| bloco | antes | depois | como |
|---|---|---|---|
| `[3]` imagens | 42,2 s | **38,3 s** | `ProcessPoolExecutor` (24) + janela 24 |
| `_normaliza_conteudo` | 42,6 s | **15,0 s** | reescrita por página em processos |
| coleta | 11,6 s | **8,4 s** | um walk só (`_usos_e_codigos`) |
| subset de fontes | 3,5 s | 3,5 s | — |
| **total** | **111,5 s** | **76,6 s** (‑31%) | |

Três detalhes que custaram:

- a reescrita da normalização virou `_normaliza_instrucoes` (função de módulo) e
  o worker `_normaliza_stream` cria um `pikepdf.new()` local só para o parser
  (que é C++ e não aceita bytes soltos) e devolve **bytes comprimidos**;
- `_processa_job` nunca tocou em `pikepdf`, então bastou `_job_leve` (sem
  `obj`/`m_obj`) para mandar o job a processo. Mas **a janela do pipeline
  continuava 8** (valor das threads): com 24 processos e janela 8 o pool ficava
  ocioso e a fase não melhorava nada — corrigir a janela foi o que destravou;
- o pickle dos jobs é 0,2–0,4 s, ou seja **não** era a serialização que segurava
  (medido, não suposto).

**Piso do que sobrou**: a fase de imagem é ~500 s de trabalho de CPU (16/24/32
workers variam 1–2 s) e a normalização tem 15 s de parse+reescrita. Chegar aos
60 s exigiria reescrever o content stream sem `pikpdf.ContentStreamInstruction`
— próximo desenho, não ajuste.

### Rodada 10 — fechamento do plano de velocidade (101 s; a GIL é o teto)

Perfil final do `recommended` em `processo.pdf` (36 CPUs, `PDFAGENT_THREADS=8`):

| bloco | baseline | agora |
|---|---|---|
| `[3]` imagens (fase inteira) | 82,0 s | **40,4 s** |
| subset de fontes | 52,5 s | **50,2 s** |
| `[5]` save | 8,0 s | **3,7 s** |
| **total** | **146,5 s** | **101,1 s** (‑31%) |

O ganho desta rodada veio de **parar de calcular o que não muda a decisão**: a
assinatura do desenho de um glifo (`_assinatura`, que expande contornos) era
calculada para TODO código de TODA cópia ao fundir fontes — 240 fontes ×
dezenas de glifos. Agora ela só roda quando os programas **não** são
byte-idênticos e o mesmo código aparece nos dois lados: fontes 56,1 → 50,2 s e
o total 109,6 → 101,1 s. A saída varia ±286 B (0,0025%, dentro da tolerância do
plano; render 0,114% e texto 0/376 iguais).

**Fase 5 do plano (Pillow SIMD): nada a fazer.** `Pillow 12.1.1` já vem com
`libjpeg-turbo` (`features.check("libjpeg_turbo") == True`) e `zlib-ng`; o
`pillow-simd` está arquivado e não tem wheel para cp311.

**Meta de 70-80 s não atingida — e o motivo está medido**: com 8 threads o pool
fica ocupado só 24,3 s para 66,9 s de trabalho serial (2,7x) e o job mediano é
0,03 s (glue de Python domina); com 16 threads a fase piora (42,3 s). O teto é
a **GIL**, não o número de núcleos: o próximo salto exige processo de verdade
(passar bytes + parâmetros ao worker, sem `pikepdf`), o que é redesenho — não
ajuste. Registrado como próximo passo, fora deste plano.

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

---

### Rodada 8 — fusão de fontes (Fase B): a regra do motor, extraída do binário

O gap era só de fonte: 3.893.562 B em streams de programa contra 2.240.376 B do
motor. Três rodadas de engenharia reversa em `PdfOptimizeAPI.dll`
(`FUN_18008dec0` = `0x1800907c8`, o `Merge fonts "%S" (obj. %d) e "%S"...`)
mostraram que a fusão **não** é por bytes nem por `BaseFont`:

1. duas cópias são fundíveis quando, **por código**, caem no mesmo caractere
   (mesmo `/Encoding`, mesmo ToUnicode) com a mesma largura — é o que as
   mensagens de aborto verificam (`difference in Encoding`, `width collision`,
   `ToUnicode collision`, `CIDToGIDMap collision`, `difference in CIDFont` =
   `/Subtype` + `/CIDSystemInfo`);
2. o programa compartilhado é a **união de glifos**: o programa final de
   `Spranq eco sans` no arquivo do motor tem 292 glifos e o maior programa do
   arquivo original tem 272 — ele copia glifos de um programa para o outro;
3. fonte simples **renumera** (motor: 4 glifos onde guardávamos 3.874); CID
   mantém os GIDs e o `/CIDToGIDMap`;
4. o programa final mantém o **cmap (3,0) formato 4 com `0xF000+código`** e
   **não** ganha `/Encoding` novo.

**Cinco bugs reais que apareceram no caminho** (cada um com medição):

- `hmtx` inconsistente: 11 dos 12 programas de Calibri eram recusados pelo
  fontTools (`too much`/`not enough 'hmtx' table data`) e ficavam **sem subset
  nenhum**. `_abre_tt()` reajusta `numberOfHMetrics` e reconstrói a tabela
  truncada — Calibri caiu de 43.640 B/3.874 glifos para **13.692 B/2 glifos**.
- `TTFont.getBestCmap()` devolve vazio quando o programa só tem as tabelas
  Symbol (1,0)/(3,0): 68 fontes do Word ficavam sem mapeamento. `_cmap_fonte()`
  usa a união de todas as tabelas.
- `legacy_cmap` desligado apagava a cmap e o dígito "3" **sumia do texto em 9
  páginas**. Ligado em `_politica_subset` (vale para todos os níveis).
- `retain_gids=True` vazava do modo "motor" para fontes simples no caminho
  antigo: elas mantinham 3.874 slots. Fonte simples renumera sempre.
- `OS/2.recalcUnicodeRanges` estoura `KeyError: 'cmap'` em programas sem cmap
  (Verdana, LiberationSerif): `_garante_cmap()` cria a tabela vazia.

**A parte difícil foi a união.** Os subsets do Word usam `post` 3.0, onde o
nome do glifo é **posicional** (`glyph00042`): o mesmo nome em duas cópias
aponta para desenhos diferentes. Fundir por nome embaralhava o texto (página
338 ilegível); fundir por caractere colidia entre cópias com/sem ToUnicode. A
solução: chave = **código**, glifo copiado recebe nome único (`c%04X`),
conflito detectado por **assinatura do desenho** (contornos + coordenadas) e o
cmap reconstruído por código (`0xF000+código`) **depois** do subset. Para CID a
fusão exige que todo CID do membro já exista no canônico **com o mesmo desenho**
— assim o GID não muda e o `/Identity` continua válido (era o que trocava a
página 210: 194 CIDs sem glifo no mapa reescrito).

**Resultado medido** (`processo.pdf`, streams de programa distintos):

| | antes | agora | motor | Δ vs motor |
|---|---|---|---|---|
| FontFile2+3 distintos | 3.893.562 B / 186 | **2.364.626 B / 138** | 2.240.376 B / 135 | +124.250 (+5,5%) |
| total recommended | 12.095.782 | **11.654.076** | 12.227.010 | −572.934 (−4,7%) |
| texto | 0/376 | **0/376** | 0/376 | — |
| render vs motor (10 pág.) | 0,11% | **0,11%** | — | — |

Gate dos 3 níveis: recommended **95,31%** da referência, extreme **95,31%**, low
**90,99%**; 0/3 combinações com problema, 0/21 diferenças estruturais, os 3
níveis com texto dentro do teto.

**Lição de método**: o nome do glifo não é identidade — em `post` 3.0 ele é
só a posição na tabela. Qualquer fusão de programa de fonte tem de comparar o
**desenho** (ou o caractere), nunca o nome, e reconstruir o cmap por código.

---

### Rodada 9 — content stream (Fase C): não era estrutura, era decimal

O diagnóstico do plano dizia "+127 KB de content stream" e listava `cm` +5.600,
`Tm` +1.960, `Tf` +146. O histograma por operador (`scripts/diag_conteudo.py`)
confirmou as contagens — mas a **contagem de `cm` era praticamente a mesma**
(31.646 nossos × 31.329 do motor) enquanto os *operandos* somavam **542 KB a
mais**. Ou seja: o motor não remove operador, ele **encurta o número**.

Medido: 38.961 números com **6 casas** em `cm` contra 50 do motor, que usa 1–2
casas (76.399 com 1 casa, 12.077 com 2). A causa no código era explícita: o
parser devolve `decimal.Decimal` e `_serializa_obj` **preservava a grafia
original** com um `if tipo == "Decimal": return s`.

**Mudanças:**

- `_serializa_obj` passa a normalizar todo número por `_fmt_num` (o caso especial
  `Decimal` saiu);
- `_fmt_num` usa `_CASAS` (topo do módulo). Com **3** casas o ganho é maior
  (‑203 KB) mas o render vai a **0,56%** e estoura o teto de 0,5%; com **4**
  casas o render volta ao piso histórico (**0,11%**) e o ganho é ‑185 KB;
- `_normaliza_conteudo` ganhou no rastreio de estado `cm`, `Tm`, `cs`, `sc`,
  `scn`, `SC`, `SCN` (mesma lógica de `Tf`: corta quando repete o valor vigente,
  respeitando `q`/`Q`/`gs`). Esse corte, sozinho, valia só ~4 KB — o ganho
  estava mesmo na formatação.

`Tm` é invalidado por `BT`, `Td`, `TD`, `T*`, `'` e `"` para o corte não usar
matriz de texto velha.

**Resultado** (`processo.pdf`):

| | antes | agora | motor |
|---|---|---|---|
| content stream comprimido | 3.538.796 | **3.353.615** | 3.414.674 |
| total recommended | 11.654.076 | **11.465.205** | 12.227.010 |
| render | 0,11% | **0,11%** | — |

Gate dos 3 níveis: recommended **93,77%** da referência, extreme **93,27%**, low
**89,85%**; 0/3 combinações com problema.

**Lição de método**: antes de reescrever operadores, comparar **bytes de
operandos**, não contagem de operadores. Um `cm` idêntico em número pode custar
20 bytes a mais e responder por 100+ KB de diferença.



