# Turi

Pipeline de ingestão e transformação de dados públicos brasileiros do
[Avoar](https://github.com/avoarpj). O Turi coleta fontes oficiais, cruza
registros e produz datasets Parquet, metadados, índices de busca e assets
estáticos para as aplicações do ecossistema.

O processamento reúne informações eleitorais, parlamentares, empresariais,
orçamentárias e geográficas. Os modelos de domínio são definidos em Protobuf
no [Avoar Core](https://github.com/avoarpj/core), que também fornece as regras
de identidade compartilhadas pelos produtores.

## Fontes de dados

| Fonte | Dados processados |
| --- | --- |
| Tribunal Superior Eleitoral | Eleições, candidaturas, partidos, diretórios, locais de votação, urnas e boletins de urna |
| Câmara dos Deputados | Deputados, legislaturas, mandatos, exercícios e despesas da cota parlamentar |
| Receita Federal | Empresas, estabelecimentos, sócios e participações societárias do CNPJ |
| Governo Federal | Emendas parlamentares, convênios e cadastros auxiliares |
| IBGE | Endereços, malhas territoriais e dados geográficos municipais |

Cada produtor declara suas entradas, saídas, dependências, origem dos dados
e frequência de atualização. A execução resolve os pré-requisitos e registra
os processamentos concluídos em checkpoints.

## Artefatos produzidos

| Artefato | Finalidade |
| --- | --- |
| Datasets Parquet | Dados estruturados para consulta e processamento analítico, com Bloom filters nas saídas do pipeline |
| Metadados Avro | Descrição das fontes, dependências e últimas execuções dos produtores |
| Índices Tantivy | Busca textual sobre os datasets, gerada pelo Venato |
| Assets estáticos | Fotos de candidaturas, mapas GeoJSON e índices de navegação geográfica |

## Instalação

O projeto requer **Python 3.14 ou superior**, **uv** e **Git**. O Core é obtido
automaticamente pelo uv; não é necessário clonar outro repositório ao lado do Turi.

Para preparar um ambiente:

```bash
git clone --recurse-submodules https://github.com/avoarpj/turi.git
cd turi

uv sync --locked
[ -e .env ] || cp .env.example .env
uv run playwright install chromium
```

O `uv sync --locked` prepara a `.venv` com as dependências fixadas no lock.
A criação do `.env` é um passo separado e preserva um arquivo já existente.

O `pyproject.toml` fixa uma revisão Git de `avoar-core`; o `uv.lock` registra a mesma
revisão. O uv obtém o código e executa o build do Core, que gera os contratos
Protobuf no ambiente Python. Não é necessário instalar `protoc` separadamente.
A primeira sincronização precisa de rede para obter código e dependências de
build. Com o cache já preparado, use `uv sync --locked --offline`.

Os submódulos incluem os assets de partidos. O Chromium é utilizado pelos
downloaders que automatizam o navegador com Playwright.

As variáveis de ambiente disponíveis estão em [`.env.example`](.env.example).
Elas configuram caminhos de dados, diretórios temporários, recursos dos
operadores e parâmetros de acesso às fontes.

## Uso

Os comandos abaixo são executados na raiz do repositório.

### Coleta

```bash
uv run turi-download
```

Executa os downloaders habilitados no
[entrypoint de coleta](apps/turi/src/scripts/entrypoints/opendata_downloads.py).
A seleção de fontes e períodos é definida nos adaptadores de download.
Arquivos em cache são reutilizados conforme a validade dos metadados e a
existência dos arquivos associados.

Os geradores SDS executam localmente por callbacks do Downloader, com cache
persistente em `downloads/sds_cache/`. A integração funciona sem um servidor
SDS separado. Detalhes em [SDS](docs/turi_sds.md) e
[downloads e cache](docs/turi_downloads.md).

### Transformação

```bash
# Catálogo completo de produtores.
uv run turi

# Produtores selecionados e seus pré-requisitos.
uv run turi elections candidatures

# Processamento sem reconstrução dos índices de busca.
uv run turi public_people --no-update-venato

# Opções da CLI.
uv run turi --help
```

O processamento utiliza os arquivos brutos preparados pelos downloaders.
A lista de downloads habilitados e a seleção de produtores são independentes;
as entradas dos produtores selecionados precisam estar disponíveis.

Cada produtor respeita sua frequência de atualização (`lifetime`) e o último
checkpoint bem-sucedido. A seleção por ID inclui seus pré-requisitos. Após o
processamento, o pipeline aplica Bloom filters aos Parquets gerados e atualiza
os índices do Venato quando um dataset indexável foi processado.

O contrato dos produtores, a descoberta automática e os metadados estão
descritos em [Scripts do Turi](docs/turi_scripts.md).

### Indexação e agendamento

```bash
# Reconstrução dos índices a partir dos dumps existentes.
uv run turi-index

# Inicialização do agendador de pipelines.
uv run turi-schedule
```

O Venato gera índices Tantivy a partir dos datasets Parquet. O agendador usa
APScheduler e os pipelines registrados em `apps/turi/src/pipelines/`.

### Mapas

O BrazilGEO gera as camadas GeoJSON do Brasil e das UFs, com geometrias
municipais e índices de limites para navegação no mapa:

```bash
uv run python -m apps.scripts.brazilgeo.generate
```

A geração completa substitui o conteúdo de `assets/brazilgeo/`. O modo
`--bounds-only` gera os índices de navegação a partir dos mapas existentes.
Consulte o [BrazilGEO](apps/scripts/brazilgeo/README.md) para opções e formatos.

## Organização do repositório

| Caminho | Responsabilidade |
| --- | --- |
| `apps/turi/src/downloaders/` | Adaptadores de coleta, callbacks e geradores SDS |
| `apps/turi/src/scripts/operations/` | Produtores dos datasets |
| `apps/turi/src/infra/` | Download, execução, metadados e operadores de processamento |
| `apps/turi/src/pipelines/` | Composição e registro dos pipelines agendados |
| `apps/scripts/brazilgeo/` | Geração dos assets geográficos |
| `avoar/infra/venato/` | Engine, schemas e produtores de texto dos índices de busca |
| `docs/` | Contratos de dados e documentação técnica |

### Diretórios de dados

Os caminhos padrão são resolvidos a partir da raiz do projeto:

| Caminho | Conteúdo |
| --- | --- |
| `downloads/` | Fontes baixadas, caches e metadados dos downloaders |
| `downloads/sds_cache/` | Cache persistente dos geradores SDS |
| `parquet_dumps/opendata/` | Datasets finais e metadados Avro |
| `assets/` | Assets estáticos e arquivos gerados |
| `venato_data/` | Índices de busca Tantivy |
| `apps/turi/src/scripts/__metadata__/` | Checkpoints dos produtores |

Os dados gerados, caches e checkpoints ficam fora do versionamento. Operações
de deduplicação e ordenação usam arquivos temporários em disco; seus caminhos
e orçamentos de buffers podem ser configurados pelo ambiente.

## Desenvolvimento

As dependências são gerenciadas com uv. Alterações no `pyproject.toml` devem
manter o `uv.lock` consistente.

No VS Code, use o Python da `.venv` do Turi. A configuração de análise acrescenta
`apps/turi/src` para resolver os imports usados pelos produtores. O pacote
`avoar` é um namespace nativo compartilhado entre este projeto e o Core instalado;
não crie um `avoar/__init__.py`, pois isso pode esconder o Core do Pylance.

Para desenvolver o Core junto com o Turi, um checkout local pode ficar em qualquer
diretório. Ative a instalação editável com seu caminho:

```bash
uv add --editable /caminho/para/core
```

Isso altera `pyproject.toml` e `uv.lock` no seu checkout. Para voltar à revisão Git
compartilhada, execute o comando abaixo com o SHA registrado no repositório e
descarte da alteração a ser publicada os caminhos particulares da sua máquina:

```bash
uv add 'avoar-core @ git+https://github.com/avoarpj/core.git' \
  --rev 56339faa0e7341f1abc927d0b330e66615edaa3c
```

```bash
PYTHONPATH=apps/turi/src:. uv run python -m unittest discover -s apps/turi/tests -v
uv run python -m unittest discover -s tests -v
```

A suíte usa fixtures locais para validar transformações, identidades, schemas,
multiplicidades e integração dos produtores. A validação de alterações de
código utiliza essas fixtures, sem exigir novas coletas ou regeneração dos
datasets completos.

## Documentação técnica

- [Produtores, dependências e metadados](docs/turi_scripts.md)
- [Downloads, cache e configuração das fontes](docs/turi_downloads.md)
- [Integração SDS](docs/turi_sds.md)
- [Deduplicação por ordenação externa](docs/turi_diskful_unique.md)
- [Ordenação dos Parquets](docs/parquet_ordering.md)
- [Bloom filters](docs/parquet_bloom_filters.md)
- [Schemas dos índices de busca](avoar/infra/venato/indexes/)
- [Assets geográficos com BrazilGEO](apps/scripts/brazilgeo/README.md)

## Licença

[MIT](LICENSE).
