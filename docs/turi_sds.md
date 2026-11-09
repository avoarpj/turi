# SDS incorporado ao Turi

O SDS não é mais um serviço HTTP externo. Seus geradores, modelos de entrada,
controle de idade dos arquivos e BulkDownloader foram incorporados em
`apps/turi/src/downloaders/_sds/`. Os metadados de datasets originais permanecem
junto deles para definir entradas e saídas. Não foram incorporados o servidor
web, o scheduler e os comandos independentes do SDS.

`downloaders/sds.py` mantém os três objetos existentes. Cada um configura
`Downloader(download_callback=...)`. O callback recebe `(downloader, source,
target)` e deve escrever o arquivo de entrada solicitado em `target`; substitui
a transferência HTTP normal, mantendo a conversão Parquet e os metadados do Turi.
Callbacks são síncronos, executados nas threads do downloader; o adaptador SDS
aguarda seus geradores assíncronos dentro da thread com `asyncio.run`.

| Downloader | Gerador local | Cache de saída |
| --- | --- | --- |
| `sds_municipalities_centroid` | Centroide da malha IBGE 2024 | `public/datasets/centroides-municipios-brasileiros/` |
| `sds_federal_deputies_history` | Histórico JSON Câmara | `public/datasets/historico_deputados_federais/` |
| `sds_federal_deputies_detailed` | Detalhes XML legados Câmara | `public/datasets/camaradosdeputados_deputados_federais/` |

Todos os caminhos da última coluna ficam sob `downloads/sds_cache/` na raiz do
Turi. O adaptador resolve entradas e saídas absolutas antes da execução, sem
alterar o cwd. O retorno dos downloaders permanece em `downloads/sds/*`, com os
mesmos schemas esperados pelos produtores. A malha dos centroides permanece em
2024, como no SDS; BrazilGEO continua usando 2025. Não uniformizar as fontes sem
validar essa alteração de dados.

Ausência de saída consolidada seleciona o bootstrap completo da Câmara;
execuções posteriores selecionam os módulos incrementais. Permanecem o limite
de 256 atualizações e os intervalos/jitter dos módulos incrementais. Isso não
significa atualizar todo o histórico em cada execução. O cache original pode ser
copiado de `temp-downloads/` e `public/` do SDS para as pastas homônimas dentro de
`downloads/sds_cache/`, sem apagar o original. Não foi feita requisição às fontes
oficiais durante a migração.

Falhas dos callbacks preservam os Parquets anteriormente publicados, registram
metadados de falha e permitem nova tentativa. A tentativa seguinte executa o
conjunto completo de callbacks: um resultado consolidado novo substitui o antigo,
sem concatená-los. Arquivos ausentes, JSON inválido ou resultado vazio são erros.
Downloads do cache usam arquivo `.part` antes da substituição. Exceções fatais
do BulkDownloader e XML inválido impedem publicar uma consolidação nova.

As validações herdadas do SDS e os testes de callbacks cobrem cache, retry,
seleção bootstrap/incremental e a geometria dos centroides com fixtures. Essa
cobertura não comprova disponibilidade atual de todos os endpoints nem conclui
uma atualização integral dos dados públicos.
