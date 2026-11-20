# PDFagent 1.3.6

Menu de contexto novo: **um item só**, que abre uma tela de escolha. E o
instalador deixou de perguntar.

## O que mudou

- **Menu de contexto em item único.** Antes era um submenu (Comprimir / Dividir);
  agora clicar em **PDFagent** no botão direito abre uma **tela única** com dois
  cartões grandes — **Comprimir** (setas convergindo) e **Dividir** (tesoura na
  linha de corte). Cada um leva à sua própria tela:
  - **Comprimir** → `low` / `recommended` / `extreme` → **[Voltar] [Comprimir]**;
  - **Dividir** → tamanho máximo da parte (já em **1,6 MB**) + caixa
    **“Comprimir antes de dividir”** (desmarcada; marcada, mostra o nível) →
    **[Voltar] [Dividir]**.
  Sem textos sobrando; o progresso aparece na mesma janela (fase, barra,
  cronômetro congelado e resultado). Os motores são os mesmos:
  `compress._in_place` e `commands.split.dividir`.
- **O app conserta o menu sozinho depois de um update por diff.** O updater troca
  apenas arquivos; o registro (HKCU) é escrito pelo instalador. Agora, no boot
  do app **instalado**, `app.migra_menu_contexto()` converte o formato antigo no
  item único — sem UAC, só quando encontra o formato antigo conhecido e sem criar
  nada se o menu nunca foi habilitado.
- **Instalador não pergunta mais nada**: PATH e menu de contexto são sempre
  aplicados (a página de tarefas saiu do assistente).
- **Ícone próprio do updater**: anel de atualização + seta de download, mesma
  família visual do app (squircle, degradê índigo→ciano).
- **Robustez**: `PDFagent.exe menu "%1"` também migra o registro quando chamado;
  argumento inválido no `.exe --windowed` não estoura mais `NoneType.write`
  (saída vai para `%TEMP%\pdfagent_saida.log`).

## Desempenho medido (documento de estresse, 376 páginas, 34,1 MB)

| nível | PDFagent | iLovePDF (referência) | razão | texto ≠ original | render (pior página) |
|---|---|---|---|---|---|
| recommended | **11.382.226 B** | 12.227.010 B | **93,09%** | 0/3 | 8,67% |
| extreme | **8.646.927 B** | 9.275.878 B | **93,22%** | 3/3¹ | 16,35% |
| low | **14.884.110 B** | 16.565.289 B | **89,85%** | 0/3 | 1,74% |

¹ bug conhecido do extrator (GID 304 do Calibri e NBSP) — ver `docs/METODO.md` §5.

Saída do gate (`py -3.11 scripts/verificar.py`):

```
[OK] testes de nivel (3 niveis)
[OK] CLI falha com exit code != 0               rc=1
[OK] CLI: subcomandos + retrocompatibilidade
[OK] launcher .bat (sintaxe e caminho)
[OK] consolidacao de objetos (ToUnicode)
[OK] coleta de fontes (pool x serial)
[OK] DPI efetivo (pacote x serial)
[OK] executavel (freeze_support / onefile)
[OK] progresso (janela única / console oculta)
[OK] menu de contexto (atalho -> motor split)
[OK] menu (migração x instalador / PATH)
[OK] updater (rótulo do check)
[OK] paridade no documento de estresse          0/3 combinacoes com problema
[OK] paridade estrutural vs iLovePDF            0/21 com diferenca
PASS — tudo dentro do esperado
```

## Instalação

1. `PDFagent-Setup-1.3.6.exe` — instala em `C:\Program Files\PDFagent` (UAC uma
   vez; a pasta fica gravável para o atualizador aplicar diffs sem novo UAC).
   **PATH e menu de contexto entram sem perguntar.**
2. Portátil: `PDFagent.exe` (GUI sem argumentos, CLI com argumentos).
3. Quem já tem instalado: o botão verde baixa só o diff; ao reabrir, o app
   **migra o menu antigo** para o item único automaticamente.

## SHA-256

Ver `SHA256SUMS-1.3.6.txt` no anexo da release.

## Limitações conhecidas

Ver `docs/METODO.md` §4b. Resumo: JBIG2 (sem codificador open-source no
projeto), subsetter CFF próprio e `ClipImages` de paths curvos.
