# CompressPDF

Compressor de PDF com os **3 níveis do iLovePDF** — *Extreme*, *Recommended*,
*Low* — com método replicado por engenharia reversa do
`iLovePDF Desktop 2.3.4` (engine 3-Heights PDF Optimizer).
Ver [`docs/METODO.md`](docs/METODO.md) para a tabela exata de parâmetros e as
evidências.

> O SDK comercial original exige licença e não é redistribuível; este app
> replica os parâmetros com bibliotecas open-source
> ([pikepdf](https://pikepdf.readthedocs.io/) + [Pillow](https://pillow.readthedocs.io/) +
> [fontTools](https://fonttools.readthedocs.io/)).

## Desempenho medido (7 PDFs reais × 3 níveis, vs iLovePDF)

| métrica | CompressPDF | iLovePDF |
|---|---|---|
| tamanho total | **4.040.405 B** | 4.203.565 B (**−3,9%**) |
| menor em | **21 / 21** arquivos | 0 |
| diferença média de render | **0,058%** | 0,135% |
| **PSNR por imagem** (158 imgs) | **33,22 dB** | 30,79 dB |
| imagens >0,5 dB pior | **0** | — |
| **deslocamento de texto** | **0,00 pt** (idêntico ao deles) | 0,00 pt |
| casos com qualidade pior | **0** | — |

Texto extraído e **hyperlinks idênticos ao original em todos os 21 casos**.
Transparência (`/SMask`) preservada e reamostrada como no original.
**Garantia:** se o resultado não ficar menor, o original é mantido byte a byte.

## Instalar

```bash
pip install -r requirements.txt
```

## Executável (Windows)

```bash
python scripts/build_exe.py          # gera dist/PDFagent.exe (onefile)
```

`PDFagent.exe` sem argumentos abre a interface gráfica; com argumentos funciona
como linha de comando (o próprio .exe anexa o console do pai):

```bash
dist\PDFagent.exe                                  # GUI
dist\PDFagent.exe entrada.pdf -n low               # CLI
dist\PDFagent.exe pasta\ -n recommended --saida-dir out\
dist\PDFagent.exe --version
```

O `CompressPDF.bat` usa o `dist\PDFagent.exe` quando ele existe e cai para
`python app.py` quando não existe (modo desenvolvimento).

## Instalador (Windows)

```bash
"C:\Users\<voce>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" instalador\PDFagent.iss
```

Gera `dist\PDFagent-Setup-1.0.0.exe` (per-usuário, **não pede admin**). Duas
opções vêm marcadas:

- **Adicionar ao PATH do usuário** → `PDFagent` fica chamável no terminal;
- **Adicionar "PDFagent > Comprimir" ao menu de contexto de PDFs**.

A ação do menu executa `PDFagent.exe --in-place --avisar "%1"`:

1. comprime com o perfil **recommended**;
2. renomeia o original para `<nome>_old.pdf` (usa `_old_2`, `_old_3`… se já existir);
3. deixa a saída com o **nome original**;
4. mostra o resultado numa caixa de diálogo.

Se o arquivo não puder ficar menor, nada é alterado (o original permanece).
Desinstalar: Configurações → Apps → PDFagent — remove arquivos, a entrada do
PATH e as chaves do menu de contexto.

## Interface gráfica

**Duplo clique em `CompressPDF.bat`** (instala as dependências sozinho na
primeira vez). Ou pelo terminal:

```bash
pip install -r requirements.txt
python app.py
```

Arraste a lógica na mão mesmo: **Adicionar…** → escolha os PDFs →
marque o nível → **Comprimir**. A saída vai para
`<nome>-compressed.pdf` ao lado do original (ou na pasta escolhida).

## Linha de comando

```bash
python compress.py entrada.pdf -n extreme|recommended|low [-o saida.pdf]
python compress.py pasta/ -n recommended --saida-dir out/
```

Variável de ambiente opcional:

```bash
COMPRESSPDF_KERNEL=bilinear python compress.py entrada.pdf -n recommended
```

Bilinear é o filtro que o motor original usa (identificado nas saídas sem
perda) e gera arquivos 0,2–5,6% menores, com nitidez um pouco menor. O padrão
é Lanczos (mais nítido, e já menor que o original).

## Níveis

| Nível | Imagens | Qualidade JPEG | Fontes | Metadados |
|---|---|---|---|---|
| Extreme | re-amostra >110 DPI → 72, JPEG; bitonal → Group4; RGB | q60 | re-subset + desembute padrão 14 | remove (XMP re-carimbado) |
| Recommended | re-amostra >150 DPI → 150, JPEG/Flate (menor vence); bitonal → Group4 | q60 | re-subset | mantém + atualiza |
| Low | re-amostra >400 DPI → 200, JPEG; bitonal → Group4 | q75 | re-subset + desembute padrão 14 | mantém + atualiza |

Regra geral (como no original): só troca o stream se ficar menor.

## Testes

```bash
python tests/test_levels.py
```

Gera um PDF de teste, comprime nos 3 níveis e valida dimensões, filtros,
metadados e ordenação dos tamanhos.
