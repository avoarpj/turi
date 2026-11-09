# Turi

Serviço de ingestão e transformação de dados do Avoar. Gera os dumps Parquet,
assets estáticos e índices Tantivy consumidos pelos demais projetos.

A estrutura dos produtores foi preservada em `apps/turi/src`. BrazilGEO fica em
`apps/scripts/brazilgeo` e Venato em `avoar/infra/venato`, com sua implementação
original. O SDS agora roda localmente por callbacks dos downloaders, sem servidor
HTTP ou scheduler próprio.

## Ambiente

Use Python 3.14 ou superior e UV. O checkout do [Avoar Core](https://github.com/avoarpj/core)
deve estar ao lado deste repositório, em `../core`:

```bash
uv sync --locked
cp .env.example .env
```

`avoar-core` é uma dependência editável configurada em `tool.uv.sources`.
Seus módulos Protobuf são gerados durante a instalação, conforme o README do
core. Nenhum contrato antigo foi copiado para este repositório. Ao alterar os
`.proto`, execute novamente `uv sync` para reconstruir os módulos gerados.

Para outro caminho de checkout, use `uv add --editable /caminho/do/core`.
Para consumir uma revisão publicada, use `uv add 'git+https://github.com/avoarpj/core.git@REVISAO'`
e atualize o lock junto com o manifesto.

Os downloaders que usam navegador exigem uma instalação adicional:

```bash
uv run playwright install chromium
```

## Execução

Execute na raiz do repositório:

```bash
# Ajuda e seleção por IDs, incluindo pré-requisitos.
uv run turi --help
uv run turi ID_DO_SCRIPT --no-update-venato

# Todos os downloads habilitados no entrypoint atual.
uv run turi-download

# Reconstruir somente os índices, a partir dos dumps existentes.
uv run turi-index

# Scheduler dos pipelines existentes.
uv run turi-schedule

# BrazilGEO: geração completa substitui assets/brazilgeo.
uv run python -m apps.scripts.brazilgeo.generate

# Acrescentar apenas índices de navegação, sem baixar ou substituir mapas.
uv run python -m apps.scripts.brazilgeo.generate --bounds-only
```

Executar `uv run turi` sem IDs seleciona todos os produtores. Confira os
entrypoints antes de executar: existem fontes comentadas por decisão operacional.
Os comandos de download, ETL e mapas podem consumir bastante disco e rede.
A atualização do Venato continua sendo acionada pelo pipeline quando um produtor
com a tag correspondente executa; `--no-update-venato` pula essa etapa.

Os comandos antigos continuam disponíveis com `PYTHONPATH=apps/turi/src:.`.
Não existe limite global novo de RAM ou alteração automática de threads.

## Dados e caminhos

| Caminho | Conteúdo |
| --- | --- |
| `downloads/` | Fontes baixadas e metadados dos downloaders |
| `downloads/sds_cache/` | Cache persistente e saídas intermediárias do antigo SDS |
| `parquet_dumps/opendata/` | Dumps finais |
| `assets/` | Assets gerados e arquivos estáticos pertencentes ao Turi |
| `venato_data/` | Índices Tantivy gerados pelo Venato |
| `apps/turi/src/scripts/__metadata__/` | Checkpoints de execução |

A migração copia assets, dumps e o cache do SDS. Os brutos dos outros
downloaders permanecem na origem: execute `uv run turi-download` antes de
regenerar seus dumps ou copie os arquivos brutos necessários para `downloads/`.
Metadados de download com caminhos absolutos antigos devem ser recriados.
Os checkpoints de execução não foram copiados.

Os caminhos padrão partem da raiz deste repositório, identificada por
`project_root.py`. `.env.example` contém as configurações opcionais de diretórios
e dos operadores com spill. Pools DataFusion não representam um teto de RSS.
Arquivos de dados grandes, caches e checkpoints não são versionados.

O cache do SDS pode ser aproveitado colocando suas antigas pastas `temp-downloads`
e `public` dentro de `downloads/sds_cache/`. As rotinas Câmara fazem bootstrap
completo quando não há saída consolidada e depois usam atualizações incrementais,
com seus limites e intervalos originais. A primeira carga sem cache pode levar horas.
Os três downloaders preservam seus nomes e diretórios `downloads/sds/*` para não
alterar os produtores existentes. Veja [a integração do SDS](docs/turi_sds.md).

## Verificação

```bash
PYTHONPATH=apps/turi/src:. uv run python -m unittest discover -s apps/turi/tests -v
uv run python -m unittest discover -s tests -v
```

Os testes usam fixtures; não execute o ETL completo para validar uma alteração de
código. Consulte [a memória técnica](docs/development_notes.md),
[o contrato dos scripts](docs/turi_scripts.md) e
[o BrazilGEO](apps/scripts/brazilgeo/README.md).
