# Produto de dados e contratos do Fons

Estado em 2026-11-07: a separação entre core, DTOs e consultas da API está
implementada. Catálogo por dataset, releases imutáveis e publicação BigQuery
continuam como evolução futura. Os dumps locais não foram regenerados.

## Direção do produto

O Avoar caminha para um produto de dados, com dumps oficiais para download e
acesso cloud comercial pelo BigQuery. Fons e Rostra são consumidores e
showcases. O contrato dos datasets pode evoluir independentemente das respostas
específicas da API e da experiência do portal.

## Organização implementada

| Responsabilidade | Local |
|---|---|
| Modelos básicos, enumerações e identidade canônica dos registros | `avoar/core/opendata` |
| DTOs de respostas e parâmetros de consulta do Fons | `apps/fons/dto` |
| Casos de uso, interfaces de consulta e cursores | `apps/fons/application` |
| SQL e montagem de respostas, mapas, pesquisas e rankings | `apps/fons/infra/opendata` |
| Sessão DataFusion e aquecimento da API | `apps/fons/infra/datafusion` |
| Cache de respostas HTTP | `apps/fons/infra/cache` |
| Tipagem dos serviços e composição | `apps/fons/application/services.py`, `apps/fons/bootstrap.py` |
| Configurações específicas de Redis do Fons | `apps/fons/config.py` |
| Engine, schemas e geração/consulta de índices Venato | `avoar/infra/venato` |
| Parsing de limites de recursos compartilhado com o Turi | `avoar/common/resources.py` |
| Downloads, adaptadores de fontes e ETL | `apps/turi` |
| Portal consumidor da API | `apps/rostra` |

O core e o Turi não importam Fons, Litestar ou Redis. A sessão DataFusion do
Fons não é dependência dos runtimes de ordenação/deduplicação do Turi. O
Venato permanece compartilhado porque o Turi gera índices e o Fons os consulta.
Seu produtor de texto de endereços passou a ler o diretório compartilhado de
municípios, sem importar settings do Turi ou fixar o nome do arquivo de um script.

A montagem chama-se `build_services`, retorna `FonsServices` e é injetada nos
controllers como `fons_services`. O lifespan mantém sessão e serviços por
processo e libera a sessão no shutdown/falha, como antes. Os imports dos módulos
movidos e seus consumidores internos foram atualizados; não há aliases no core
importando classes do aplicativo.

A distribuição Python inclui `apps.fons*`. A compilação da wheel verifica que
os módulos novos são empacotados e os antigos módulos movidos não permanecem
na distribuição. A localização dos dados continua sendo a configuração atual;
não foi introduzida materialização nem servidor de banco.

Após alterar os pacotes incluídos no `pyproject.toml`, reconstruir também a
instalação editável da `.venv`. A declaração no arquivo e uma wheel correta
não atualizam o finder de uma instalação anterior. Imports/testes pela raiz
ou com `PYTHONPATH=.` podem mascarar esse problema. O teste de arquitetura
agora carrega o Fons pelo loader Granian em processo `python -I`, a partir de
um diretório temporário, por caminho de arquivo e por módulo qualificado.

O reparo local foi a reinstalação somente do projeto, preservando dependências:

```bash
uv pip install --python .venv/bin/python --no-deps --no-build-isolation --reinstall --editable .
```

Em um ambiente sincronizável, `uv sync --locked --reinstall-package avoarpj`
também reconstrói o registro. No ambiente examinado, o dry-run do sync indicou
recriação da `.venv` devido à diferença de patch do Python; a reinstalação
direcionada evitou substituir o ambiente completo. Reiniciar o processo
Granian após atualizar a instalação, para recarregar o finder.

## Modelos básicos e DTOs

No core permanecem fatos como `PessoaPublica`, `Mandato`, `ExercicioMandato`,
`Empresa`, `Estabelecimento`, `Socio`, `SociedadeParticipacao`, `Recurso`,
`Candidatura`, `Eleicao`, `Pleito`, `BoletimUrna` e `LocalVotacao`, além das
enumerações públicas. Os dicionários de códigos específicos de diretórios
partidários do TSE estão no adaptador `scripts/bricks/tse_party_directory.py`.

As famílias de detalhes, totais, rankings, pesquisas e mapas pertencem ao Fons:
`MandatoDetalhado`, `InformacoesCompletasPessoaPublica`, `EmpresaDetalhada`,
`BusinessReceipts`, `InsightsCeap`, `InsightsEmendasMandato`, projeções de
votos/candidaturas, exploração municipal, força partidária, insights gerais e
guinada. Seus filtros, paginação e cursores também pertencem ao aplicativo.

Mesmo respostas básicas usadas pelo Fons possuem DTOs com campos explícitos,
sem herdar os modelos canônicos. Isso permite acrescentar uma coluna ao produto
de dados sem acrescentar automaticamente um campo HTTP. A duplicação desses
campos representa dois contratos independentes; as enumerações continuam
compartilhadas. Os nomes Python dos modelos públicos foram preservados para
manter os nomes dos componentes OpenAPI.

`id_avoar` do core valida o domínio de inteiros unsigned de 64 bits e mantém a
representação inteira. O alias do Fons em `dto/common.py` preserva a
serialização JSON em string. Valores financeiros continuam usando precisão
decimal; políticas de datas, nulos e paginação foram preservadas. A identidade
empresarial calculada com Polars fica em
`apps/fons/infra/opendata/business/identity.py`, preservando o input textual de
oito dígitos, a seed e o hash do produtor. O core mantém apenas a seed
compartilhada em `core/opendata/common/identity.py`, sem importar Polars.
O resolvedor do Fons cuida da entrada formatada e da representação HTTP.

## Consultas e serialização

As consultas do Fons produzem diretamente o formato de seus DTOs. As interfaces
em `apps/fons/application` podem referenciá-los sem acoplar o core ao aplicativo.
A política `QueryServiceReturnTypes` está em `apps/fons/application/return_types.py`:

- `MODEL_PARSED` constrói/valida os DTOs Pydantic;
- `JSON_STRING` e `DICT` preservam o caminho rápido com msgspec, sem reconstruir
  entidades ou validar modelos antes da serialização.

A anotação de retorno do controller não filtra JSON já serializado. As leituras
que devolviam colunas brutas diretamente passaram a ter projeções explícitas:
pessoas, mandatos, gabinetes, eventos, exercícios, filiações, candidaturas,
legislaturas, municípios, órgãos e recursos das emendas.

`apps/fons/infra/opendata/projection.py::sql_columns` obtém colunas de DTOs
planos do próprio Fons, sem construir/validar modelos. Coleções aninhadas
continuam montadas em consultas menores e por página/lote. A estrutura dos
joins, regras de agregação e ordenação foi mantida. `SELECT *` pode continuar
em CTEs internos com saídas delimitadas, sem expor colunas novas ao HTTP.

Os testes adicionam colunas extras aos datasets e verificam que detalhes,
coleções de pesquisa e recursos financeiros continuam com o mesmo JSON,
inclusive com construção/validação/dump Pydantic bloqueados no caminho rápido.
Nos dez datasets locais inspecionados, as novas projeções correspondem às
colunas existentes, sem campos ausentes nem extras.

## Correção de empresa_id

O uso de `business_id` no modelo de estabelecimento era uma tradução incompleta.
O nome correto agora é `empresa_id` no core, DTOs, resposta de estabelecimento,
estabelecimentos embutidos na empresa e navegação/tipagem do Rostra. A consulta
usa diretamente a coluna já existente no dump; não precisa regenerar dados.

Os parâmetros das rotas empresariais no OpenAPI também se chamam `empresa_id`.
As URLs concretas continuam `/opendata/business/<id>` e
`/opendata/business/<id>/receipts`. Consumidores do antigo campo JSON devem ser
atualizados; não foi adicionado alias HTTP para perpetuar o erro.

A comparação com o OpenAPI anterior preserva os demais schemas, nomes de
componentes e endpoints, considerando a mudança autorizada de campo/parâmetro,
seus operationIds derivados e a ordem irrelevante dos campos `required`.
Respostas antigas em Redis ou cache do navegador podem sobreviver pelo TTL;
para uma troca imediata, alterar `REDIS_CACHE_NAMESPACE` de forma coordenada
nos servidores Fons/Rostra e renovar o cache local do cliente.

## Validação da migração

- Baseline anterior: 85 testes API/infra aprovados e OpenAPI salvo para comparação.
- Suíte API/infra: 94 testes aprovados, incluindo fronteiras, identidade,
  serialização e isolamento de colunas novas; montagem/lifespan reais preservados.
- Descoberta dos 32 scripts Turi em processo isolado sem carregar Fons, Litestar
  ou Redis, inclusive com uma configuração Redis inválida no ambiente.
- Testes do produtor Venato com municípios e endereços temporários, preservando
  ID uint64 e conteúdo do texto indexado.
- Suíte Turi: 93 testes aprovados. Os 18 arquivos de testes do Rostra, check e
  build passaram; wheel construída e inspecionada, com 88 módulos Python Fons.
- Smoke com app/lifespan e dumps locais reais, Redis desabilitado: órgãos e
  estabelecimento retornaram 200, com `empresa_id` string e vínculo empresarial
  correto. Não foi uma medição de capacidade ou uma carga cloud.

Os resultados consolidados estão em
[audits/fons_dto_migration_2026-11-07.json](audits/fons_dto_migration_2026-11-07.json).
O `svelte-check` mantém dois avisos sobre referências iniciais em
`PersonDetails.svelte`; não são erros de contrato. Dois imports com alias `$lib`
e extensão `.ts` em `Details/format.ts` foram ajustados para caminhos relativos,
permitindo executar os testes Node e o check TypeScript atuais.

## Evolução futura do produto de dados

A separação implementada não substitui um contrato tabular por dataset.
Esse contrato deve declarar ID, schema físico Arrow, semântica das colunas,
granularidade, chaves, relacionamentos, política de nulos, cobertura,
proveniência, licença e versões de schema/release. Modelos básicos podem ser
conferidos contra esse contrato sem validar cada linha do ETL em Pydantic.

Os metadados novos do Turi descrevem scripts. Um script de eleições gera
pleitos, eleições e turnos, portanto o catálogo precisa distinguir o produtor
de cada dataset. O `metadata.avro` atual oferece proveniência, mas ainda não
define o schema e a granularidade de cada saída.

Um agregado pode tornar-se um dataset oficial, como uma votação municipal,
quando tiver contrato e validação próprios. O envelope de mapa, ranking e
paginação continua pertencendo ao Fons. A escolha do canal cloud também não
exige tornar as consultas DataFusion do Fons intercambiáveis com BigQuery.

Para publicar releases, a sequência proposta é staging, ordenação/Bloom filters,
auditoria, checksums finais e publicação imutável com manifesto. Downloads,
Fons e entrada do publicador cloud devem consumir a mesma release validada.
A sessão DataFusion deve fixar a release na abertura, junto de índices Venato
compatíveis. Hoje os caminhos ainda seguem o arranjo anterior; essa publicação
coordenada não foi implementada na migração de DTOs.

Usar os dumps no showcase exercita relações; a publicação precisa também
comparar cobertura, linhas, votos e totais com o bruto por ano/tipo/localidade,
preservando nulo versus zero e os vínculos legitimamente ausentes.

## BigQuery: decisão de representação pendente

Estatísticas dos dumps locais confirmam IDs `uint64` acima de `2**63 - 1` em
empresas, estabelecimentos, mandatos e candidaturas. BigQuery usa `INT64` com
sinal e documenta erro ao carregar Parquet `UINT_64` acima desse limite.
[Documentação oficial de carga Parquet](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-parquet?hl=en).

A representação cloud precisa ser escolhida explicitamente, preservando os
valores. `NUMERIC(20, 0)` e `STRING` são alternativas a avaliar no adaptador de
publicação; a ingestão precisa receber uma representação suportada, em vez de
presumir que declarar outro tipo de destino resolve o arquivo atual.
[Tipos do BigQuery](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-types).

Esta migração preservou os hashes e os tipos físicos dos dumps. Não houve
carga BigQuery, mudança de IDs, geração de novas releases ou reindexação.
