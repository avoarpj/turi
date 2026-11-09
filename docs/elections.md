# Eleições no Rostra

Estado em 2026-10-28: `/eleicoes` é a entrada da navbar para força dos partidos
e guinada de votos. Substitui os dois links independentes no menu. As rotas
anteriores continuam disponíveis para compatibilidade; os componentes também
conservam sua apresentação independente.

## Contexto principal

O topo seleciona uma eleição por `pleito_id` e, separadamente, `numero_turno`.
A eleição padrão é a mais recente do catálogo; o turno padrão é o primeiro
disponível. O catálogo de bases fornece os turnos efetivamente disponíveis,
inclusive quando cada turno tem um `eleicao_id` diferente. Aplicar o formulário
troca o contexto e limpa a comparação específica anterior.

O loader universal carrega somente `/opendata/pleito` e
`/opendata/vote_shift/elections`. Não inicia agregações no SSR/preload. Reutiliza
votos nacionais válidos já presentes no cache local do recorte exato.

## Visualizações

A aba **Força dos partidos** consulta os endpoints existentes com o pleito e o
turno principais, sem repetir os filtros dentro do mapa. Preserva os controles
de partido, zoom, limite de UFs e legenda.

A aba **Guinada de votos** usa a eleição principal como referência. O usuário
seleciona cargo/circunscrição e a eleição e turno comparados. Por padrão, oferece
uma eleição anterior do mesmo cargo, circunscrição e número de turno. A opção
“Usar outra eleição como base” libera referência e turno independentes somente
para essa visualização, sem alterar o contexto principal ou a força partidária.

Somente a primeira aba visitada é montada na abertura. A outra inicia sua
consulta na primeira visita. Depois, ambas conservam dados e instâncias dos
mapas ao alternar; a ativação redimensiona o mapa sem reenviar os votos. O
carregador municipal da força partidária pausa novos jobs enquanto a aba está
oculta. Cancelar HTTP continua sem garantir cancelamento da consulta no Fons.

## URL e contratos

Parâmetros: `pleito_id`, `numero_turno` e `view=forca|guinada`. Uma comparação
aplicada acrescenta `office`, `locality`, `round_id` e `reference_round_id`.
`custom_reference=1` indica a referência independente. A URL preserva o contexto
principal ao aplicar uma comparação; recarregá-la restaura a mesma seleção.
IDs uint64 continuam strings.

Os endpoints não mudaram nesta integração. Contratos dos mapas em
[party_strength_map.md](party_strength_map.md) e [vote_shift_map.md](vote_shift_map.md).

## Verificação

Testes do loader verificam ausência de agregações SSR, contexto principal,
referência padrão, validação de URL e referência opcional. Svelte check sem
erros/avisos, suíte do Rostra e build passaram.

Chromium com servidores temporários, catálogos reais e respostas de teste
confirmou link ativo “Eleições” na navbar, contexto compartilhado, consulta sob
demanda, alternância sem repetir consultas, referência opcional, restauração da
URL e troca do contexto principal. Sem erros JS ou overflow em 1440/390/320 px.
O Rostra local retornou HTML 200 em 0,47 s, com navbar e seleção principal, sem
agregação no SSR. Não foram executadas agregações reais apenas para validar a UI.
