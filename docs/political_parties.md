# Cadastro de partidos e filiações

O mapa interativo do Rostra está em `/partidos`, com filtro de pleitos e detalhe
municipal progressivo. Contrato da tela e limites de carregamento em
[party_strength_map.md](party_strength_map.md).

Estado em 2026-10-15: `opendata_political_party` é gerado pelo Turi a partir dos
diretórios partidários do TSE. Cada registro tem `sigla`, `nome` e `notas`.
A carga local tem 39 registros, incluindo partidos históricos. Não é um cadastro
completo de todas as siglas de filiações existentes; não inferir situação atual
nem substituir um partido histórico pelo sucessor. As notas da fonte são
preservadas no contrato `PartidoPolitico`.

## Endpoint

`GET /opendata/political_party/` retorna uma lista de objetos `PartidoPolitico`.
Usa paginação keyset: `limit` de 1 a 1000 (padrão 1000), `order=asc|desc`
(padrão `asc`), `pull_by=sigla` e `pull_after` opcional, exclusivo. O cursor
é a sigla do último item recebido; não há OFFSET. Resultado vazio é `[]`.

```text
/opendata/political_party/?limit=10&order=asc&pull_by=sigla
/opendata/political_party/?limit=10&order=asc&pull_by=sigla&pull_after=NOVO
```

O domínio declara `sigla` como único campo ordenável. O caso de uso valida os
parâmetros, o query service DataFusion consulta o Parquet diretamente e o core
registra `political_party`. A rota retorna JSON já serializado por `msgspec`.
`JSON_STRING` e `DICT` não instanciam modelos Pydantic; `MODEL_PARSED` valida
`PartidoPolitico`. Siglas de cursor e limite são parâmetros da consulta.

Não é necessário regenerar dados. Reinicie Fons para registrar o controller
novo; não há alterações de schema do Parquet.

## Força dos partidos no mapa (2026-10-22)

- `GET /opendata/political_party/strength`: totais por UF e partido.
- `GET /opendata/political_party/strength/{uf}`: mesmos totais por município
  físico dos boletins da UF informada. Aceita sigla em caixa baixa.

Ambas aceitam `pleito_id` opcional e repetível. Os IDs são os uint64 de
`opendata_pleito`, e a seleção usa `opendata_election.pleito_id`. Sem filtro,
consideram todos os pleitos disponíveis. IDs repetidos não multiplicam votos;
IDs válidos sem registros não acrescentam dados. ID negativo, acima de uint64,
texto inválido e UF desconhecida retornam HTTP 400.

Desde 2026-10-28, ambas aceitam também `numero_turno=1|2`, opcional. Quando
omitido, preserva a soma de todos os turnos. O número aplica-se a cada pleito
selecionado; combinações sem esse turno retornam `[]`. Valores fora de 1/2 ou
não inteiros retornam 400. As rotas e os campos da resposta foram preservados.

```text
/opendata/political_party/strength?pleito_id=9447349894321270069
/opendata/political_party/strength/SP?pleito_id=2637794076754536956&pleito_id=9447349894321270069
/opendata/political_party/strength?pleito_id=9447349894321270069&numero_turno=2
```

Por decisão do usuário, os totais somam **todos os cargos** dos pleitos
selecionados e respeitam o filtro opcional de turno. Sem ele, somam todos os
turnos. Incluem votos nominais (tipo 1) e de legenda (tipo 2); excluem
brancos, nulos e anulados. São votos por disputa, não eleitores únicos: uma pessoa
pode contribuir em vários cargos e turnos.

A resposta é uma lista sem paginação, própria para preencher a camada inteira.
Cada linha contém `uf`, `sigla_partido`, `votos_nominais`, `votos_legenda` e
`total_votos`. No detalhe estadual, acrescenta `codigo_ibge`, string de sete
dígitos, para associar a feição de `assets/brazilgeo/states/<UF>.geojson`.
UF corresponde a `Feature.id` da camada nacional. Ordenação: UF, município no
detalhe, total decrescente e sigla como desempate.

```json
[
  {
    "uf": "SP",
    "codigo_ibge": "3550308",
    "sigla_partido": "PT",
    "votos_nominais": 90,
    "votos_legenda": 5,
    "total_votos": 95
  }
]
```

O exemplo ilustra o formato; não representa contagem eleitoral real.
Localidades/partidos sem registros não são preenchidos com zero. Resultado
vazio é `[]`. Geografia vem de `BoletimUrna.codigo_municipio_ibge`, validada
contra o cadastro municipal; `codigo_local` eleitoral pode ser UF/BR e não
define o lugar físico do voto. Boletins sem geografia resolvida não entram nas
camadas; o total representa a cobertura disponível dos dumps.

A associação partidária usa a candidatura da eleição, cargo TSE e número
votável, preservando siglas históricas e sem exigir mandato ou cadastro em
`public_people`. Para legenda, usa eleição, cargo e número do partido das
candidaturas. Candidaturas com a mesma chave e sigla são uma associação única;
siglas conflitantes ou associação ausente produzem `sigla_partido: null`. Esse
grupo conserva os votos sem atribuí-los arbitrariamente a um partido.

### Memória e verificação

As dimensões de pleitos/municípios e a resolução dos partidos são consultas
separadas. A consulta grande cruza somente os boletins físicos com os itens,
filtra IDs diretamente no scan e agrega antes da conversão em lotes para Python.
Quando há `numero_turno`, resolve os IDs em `opendata_election_round`, reduz as
eleições às que possuem esse turno e filtra `i.turno_eleicao_id` no scan por IN
escalar. Não acrescenta join de turnos aos fatos. Sem filtro, esse passo não roda.
O mapa de partidos usa igualdade entre MIN/MAX para reconhecer uma única sigla;
`COUNT(DISTINCT sigla)` por centenas de milhares de números votáveis provocou
consumo excessivo nesta sessão. A consulta original com múltiplos joins também
escolhia fatos grandes como entrada de hash. Essas abordagens foram substituídas.

JSON/DICT continuam sem validação Pydantic; somente MODEL_PARSED usa TypeAdapter.
`tests/test_party_strength.py` cobre HTTP com app/core reais, OpenAPI, listas de
pleitos uint64, tipos de voto, todos os cargos/turnos, geografia física, partidos
históricos, chaves repetidas/ambíguas, ausência e os três formatos. Regressões de
memória usam 210 mil itens com pool de 4 MB e 50 mil números de candidatura com
pool de 32 MB.

```bash
PYTHONPATH=apps/fons:. uv run python -m unittest tests.test_party_strength tests.test_political_parties -v
```

O orçamento do pool não é um teto do RSS do processo. Durante a validação,
`DATAFUSION_MEMORY_LIMIT=12GB` e seis partições estavam configurados numa máquina
de 14 GiB; esses valores locais foram preservados. As verificações reais seguintes
usaram pool de 512 MB, duas partições, limite de espaço de endereços no subprocesso
e monitor externo de RSS. Condições e medições em
[party_strength_2026-10-22.json](audits/party_strength_2026-10-22.json).
Na mesma execução sequencial, a camada nacional de 2022 respondeu em 2,395 s,
SP detalhado em 1,623 s e o país sem filtro em 6,618 s. Pico acumulado do processo:
884,8 MiB. O total de SP coincidiu por partido entre as duas camadas. São medidas
locais sem Redis, não um teste de concorrência ou de cache frio do SO. Oito testes
da feature/catálogo passaram.
Reinicie Fons para carregar as novas rotas; não exige regenerar os Parquets atuais.

### Regressão após regenerar os boletins (2026-10-28)

A SQL não havia mudado ao incorporar 2026, mas a publicação passou pelo novo
gravador externo PyArrow. Ele registra `sorting_columns` por
`(tipo, quantidade, boletim_id)`, enquanto uma reprodução do writer Polars
anterior não declara essa ordenação no footer. A malha física também mudou:
o relatório anterior tinha 184.398.705 linhas/481 row groups/2,45 GB, e o arquivo
atual tem 254.345.786 linhas/3.882 grupos/5,74 GB. Excluindo 2026, a auditoria
bruta atual reproduz exatamente as 184.398.705 linhas anteriores. Crescimento de
volume não explica sozinho a regressão; codec/layout não foram isolados em um
benchmark de reescrita.

O DataFusion reconhecia a ordenação de `tipo`, presente no GROUP BY, e escolhia
`AggregateExec ordering_mode=PartiallySorted([3])` com `RepartitionExec
preserve_order=true` tanto nos fatos quanto nos agregados. Em um experimento
controlado, os mesmos bytes e a mesma SQL levaram 23,616 s com a ordenação
inferida e 15,361 s com um provider temporário `file_sort_order=[[]]`. Esse
provider foi usado somente no diagnóstico; o registro da API não foi alterado.

A consulta agora faz duas somas filtradas, `FILTER (WHERE tipo = 1/2)`, e deixa
`tipo` fora do agrupamento. Isso elimina a preservação de ordem nessa agregação
sem alterar os dados ou ocultar seus metadados. A associação ao partido continua
separada para cada tipo: um número de candidato não determina o partido de uma
linha de legenda. SUM nulo indica tipo ausente; zero explícito permanece zero.

Comparação integral sequencial, pool 512 MB e duas partições:

| Recorte | SQL anterior | SQL corrigida | Igualdade |
|---|---:|---:|---|
| País, todos os pleitos | 27,579 s | 16,435 s | 1.247 linhas e 2.498.845.054 votos, registros idênticos |
| SP municipal, 2022 | 6,144 s | 3,299 s | 20.080 linhas e 167.769.935 votos, registros idênticos |

Sem 2026, a versão corrigida retornou 1.117 linhas/1.699.451.801 votos, exatamente
o resultado histórico de 22/10, em 12,686 s. Portanto, não foi demonstrado retorno
à latência antiga de 6,618 s. As medições não controlam o cache do SO nem isolam
todo o custo adicional do layout novo. O pico RSS acumulado foi 1.110,9 MiB.

Nove testes de força/cadastro passaram. A regressão usa Parquet real ordenado,
verifica ausência de reparticionamento ordenado, tipos simultâneos com o mesmo
número, zero explícito e ausência. Ela falha no plano da SQL anterior. Evidência:
[party_strength_regression_2026-10-28.json](audits/party_strength_regression_2026-10-28.json).
Reinicie Fons para carregar a SQL; não é necessário regenerar dados.

## Filiações no Rostra

O histórico do mandato e os períodos de exercício na busca de parlamentares
mostram logo seguido do nome completo do cadastro. O nome é associado por sigla,
ignorando caixa, espaços e acentos, sem associar siglas de partidos diferentes.
Se não houver registro, o nome estiver vazio ou a consulta estiver indisponível,
mostram a sigla original. Não há lista manual de nomes substituindo o dataset.

Os loaders SSR de mandato e busca consultam o catálogo em paralelo aos demais
metadados, com `optionalData`: falha desse catálogo não impede abrir a página.
TanStack Query recebe os dados iniciais, compartilha a chave `political-parties`
e mantém os dados frescos por cinco minutos. Há uma consulta por página para o
catálogo, não uma por filiação. Rostra continua somente lendo o Redis e usa o
proxy restrito `/api/fons/opendata/political_party/` para consultas no navegador.

`PartyLabel` aceita um `label` explícito para exibir o nome ao lado da imagem.
Nas demais aparições, preserva a apresentação somente com logo escolhida pelo
usuário; ausência/falha do SVG exibe a sigla. Os logos continuam preferindo
`_typo.svg`, com fallback ao SVG completo. As cores, os SVGs do submodule e os
períodos históricos de cada filiação não foram alterados.

## Verificação

`tests/test_political_parties.py` abre o app real com core real e Parquet de
fixture, substituindo somente a conexão e desabilitando cache externo. Cobre
listagem, notas, limites, cursores nas duas direções, cursor com aspas, resultados
vazios, OpenAPI e equivalência dos três formatos. Nos caminhos rápidos, bloqueia
a validação Pydantic para detectar regressões.

No Rostra, os testes cobrem associação de nomes, siglas históricas ausentes,
nome vazio, catálogo indisponível, carregamento SSR, permissão restrita do proxy
e HTML de logo com nome/fallback. Check sem erros/avisos, build e suíte do Rostra
passaram; a suíte API/infra passou com 55 testes. A chamada local ao app real
retornou HTTP 200 com os 39 registros, sem regenerar dados.
