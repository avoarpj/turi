# Scripts do Turi

## Execução

Na raiz do repositório:

```bash
# Todos os scripts descobertos
PYTHONPATH=apps/turi/src:. uv run python apps/turi/src/run_all_scripts.py

# Apenas os IDs escolhidos e seus pré-requisitos
PYTHONPATH=apps/turi/src:. uv run python apps/turi/src/run_all_scripts.py elections candidatures

# Mesma execução, sem atualizar índices do Venato
PYTHONPATH=apps/turi/src:. uv run python apps/turi/src/run_all_scripts.py public_people --no-update-venato
```

Dentro de `apps/turi`, também pode usar `uv run python src/run_all_scripts.py`.
A seleção é uma lista de argumentos posicionais; sem IDs, executa todos.
IDs e crons anteriores foram preservados, inclusive o ID histórico
`policial_parties`. Não é necessário comentar chamadas no entrypoint.

`OpendataDumpsEntrypoint.run(script_ids=None, no_update_venato=False)` continua
sendo a entrada do scheduler. A execução permanece direta e sequencial, sem
supervisor ou limite global de memória acrescentado por essa reforma.

## Declaração de uma operação

Uma operação estende `DataScript`, implementa apenas `process_data(logger)` e
exporta `script_instance`. `persist_data` e `ExecutionMode` foram removidos.
O próprio processamento escreve os Parquets; consumidores consultam os dumps.
O Turi não exige mais `AVOAR_POSTGRES_URL` para iniciar.

```python
from logging import Logger

from config.projectsettings.settings import DUMPS_OUTPUT_DIR
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript


OUTPUT = DUMPS_OUTPUT_DIR / "opendata" / "example" / "data.parquet"


class ExampleDataScript(DataScript):
    script_id = "example"
    lifetime = "0 6 * * *"

    source = "Nome da fonte"
    source_url = "https://example.org/dados"
    description = "Descrição do conteúdo produzido."

    input_paths = []
    output_paths = [OUTPUT]

    dependencies = ["organs"]
    tags = [VENATO_INCLUDED]

    def process_data(self, logger: Logger):
        # Preparar os dados e escrever OUTPUT.
        ...


script_instance = ExampleDataScript()
```

Só adicione `VENATO_INCLUDED` se o script produz ou altera uma entrada da
indexação; a tag não cria um schema no Venato. Metadados e caminhos próprios
ficam no módulo da operação. `config/projectsettings/scripts.py` contém apenas
caminhos usados por múltiplos produtores. Valores comuns a todo o serviço
continuam em `settings.py`.

Os valores são acessíveis por import, por exemplo
`script_instance.script_id`, `.lifetime`, `.source`, `.source_url`, `.description`,
`.input_paths`, `.output_paths`, `.dependencies`, `.tags` e
`.last_successful_execution`. `output_paths` lista arquivos Parquet, não diretórios.
O runner prepara seus diretórios antes do processamento.

## Descoberta e dependências

`infra/datascript/discovery.py` procura módulos Python sob `scripts/operations`,
inclusive subdiretórios sem `__init__.py`, e registra seus `script_instance`.
Módulos sem instância são helpers; nomes iniciados por `_` são ignorados.
Imports devem ser livres de processamento e downloads. A preparação do NLTK
de pessoas públicas passou a ocorrer somente quando o processamento a utiliza.

`dependencies` contém os `script_id` dos **pré-requisitos**, que rodam antes do
script consumidor. O plano inteiro da seleção é resolvido antes de processar:
IDs inexistentes, dependências ausentes e ciclos interrompem a execução. IDs
duplicados no catálogo também são erro. Cada script aparece uma única vez,
mesmo compartilhado entre várias dependências ou repetido na seleção. A ordem
das dependências declaradas é respeitada; a seleção de todos parte dos IDs
ordenados para produzir um plano determinístico.

Cada pré-requisito consulta seu próprio lifetime e pode ser pulado. Isso não
pula o consumidor: ele também consulta seu lifetime. Selecionar um script não
força sua regeneração nem executa automaticamente os consumidores posteriores.
Uma falha interrompe os próximos scripts e o pós-processamento.

O cron mantém o timezone padrão do APScheduler, como antes. Datas de execução
continuam em UTC. O histórico JSON em `scripts/__metadata__/<script_id>.json`
continua sendo lido, preservando lifetimes de dados existentes. A atualização
desse checkpoint ocorre depois do processamento e da escrita do Avro.

Os vínculos atuais seguem as leituras de dumps de cada produtor. Endereços
declaram municípios como pré-requisito porque o produtor de texto do índice de
endereços usa esse catálogo. Municípios também recebem `VENATO_INCLUDED`, pois
uma alteração de nomes/UF afeta esse índice. O cadastro IBGE continua opcional
para locais de votação: sua ausência preserva o fallback TSE e não obriga uma
carga de endereços quando apenas `tse_voting_locations` é selecionado.

## Metadados dos dumps

`infra/datascript/metadata.py::write_metadata(script, executed_at)` usa Polars
para escrever `metadata.avro` em cada diretório de `output_paths` após o
processamento bem-sucedido. O arquivo contém:

- `script_id`, `lifetime`, `source`, `source_url` e `description` como strings;
- `input_paths`, `output_paths`, `dependencies` e `tags` como listas de strings;
- `last_successful_execution` como string ISO 8601 com timezone UTC.

Se vários produtores compartilham um diretório, o Avro mantém uma linha por
`script_id`. Reexecutar um deles substitui apenas sua linha. Escritas Avro e JSON
usam temporários no mesmo diretório e substituição atômica de cada arquivo;
isso não representa uma transação entre todos os Parquets, Avros e checkpoints.
As execuções devem continuar sem concorrência sobre as mesmas saídas.

Scripts pulados pelo lifetime não reescrevem os metadados. Dumps existentes
recebem o Avro na próxima execução efetiva do respectivo produtor. Esta reforma
não regenera os dados locais automaticamente.

## Pós-processamento

O entrypoint aplica os Bloom filters somente aos Parquets dos scripts que
efetivamente executaram, antes da indexação. O modo isolado de
`bloom_final_parquets` continua descobrindo todos os arquivos por padrão; seu
argumento Python opcional `paths` permite restringir a manutenção.

Se pelo menos um script executado tem `VENATO_INCLUDED`, o entrypoint reconstrói
os índices com `prune_all()` e `ingest_all()`, preservando a estratégia anterior.
`no_update_venato=True` ou `--no-update-venato` impede essa etapa. Uma tag apenas
em um script pulado pelo lifetime não dispara indexação. Sem scripts executados,
também não há manutenção de Bloom filters.

## Validação da reforma (2026-11-07)

A suíte Turi passou com 93 testes, incluindo 13 novos para essa reforma. Cobre
descoberta real dos produtores, diretórios namespace, ciclos,
IDs desconhecidos/duplicados, ordenação, deduplicação de dependências, histórico
anterior, skip por lifetime, seleção CLI, condições do Venato, round-trip Avro,
preservação de produtores em diretórios compartilhados e falhas sem atualizar o
checkpoint. O teste do entrypoint usa Parquets e Bloom filters reais temporários
e confere que um dump não selecionado permanece intacto.

Um smoke da CLI executou o produtor real `organs` em diretório temporário:
três órgãos, Avro, checkpoint e Bloom filters; a segunda chamada pulou pelo
lifetime. Os dumps e índices de produção não foram regenerados nessa validação.
