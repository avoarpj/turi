# Medição de memória dos produtores

As medições completas abaixo precedem a substituição do índice de arquivos do
`diskful_unique` por [ordenação externa em blocos](turi_diskful_unique.md).
O novo backend foi validado com fixtures; seus benchmarks têm relatório separado.

`scripts/maintenance/profile_scripts.py` executa cada `process_data` em um
processo novo, sequencialmente, com os brutos locais e os dumps publicados como
dependências. A ferramenta ignora lifetimes, redireciona as constantes de saída
do módulo para uma pasta de diagnóstico e não atualiza checkpoints, Avro,
Bloom filters ou Venato. Nas fotos de candidaturas, o cálculo de chaves, a
seleção e a descoberta de arquivos são executados, com movimentos de arquivos
simulados para um destino isolado; fontes e assets publicados são preservados.

```bash
UV_CACHE_DIR=/tmp/turi-uv-cache uv run --locked --offline python \
  apps/turi/src/scripts/maintenance/profile_scripts.py \
  --directory downloads/temp/memory-profile-local
```

IDs posicionais restringem a seleção, sem executar pré-requisitos. Sem IDs, a
ferramenta percorre o catálogo em ordem de dependências, mas cada produtor lê
as dependências já publicadas. Uma execução interrompida pode ser retomada com
o mesmo diretório: os IDs presentes no relatório são preservados. Use outro
diretório para medir novamente esses IDs.

O monitor Linux lê RSS, pico RSS do kernel, swap do processo e memória disponível
com intervalo alvo de 100 ms; os timestamps efetivos ficam no CSV. Também conserva
`ru_maxrss` quando o worker termina.
Na rodada `disk-final`, soma RSS e swap dos descendentes vivos, incluindo o
processo de ordenação. A soma de RSS pode contar páginas compartilhadas duas
vezes; o HWM do kernel é do worker principal, sem somar picos de etapas distintas.
A rodada `address-final` também registra PSS e LazyFree via `smaps_rollup`.
PSS distribui proporcionalmente as páginas compartilhadas e permite distinguir
o transiente de fork da criação de memória física adicional. PSS inclui páginas
recuperáveis e não é uma medida exata da memória ativa. Não subtrair os picos
separados de PSS e LazyFree, pois podem ocorrer em instantes diferentes.
Os picos incluem imports e buffers nativos; o tempo `process_seconds` começa
depois dos imports, enquanto `wall_seconds` inclui a inicialização do worker.
Swap é amostrada: seu pico pode ocorrer entre amostras. Os picos separados de
RSS e swap não precisam ocorrer no mesmo instante; há uma métrica adicional da
maior soma amostrada. O monitor não acrescenta um teto ao pipeline nem altera
o número de threads.

As coletas mais recentes incluem RSS anônimo e de arquivos. RSS anônimo pode
conter páginas `LazyFree`, já liberadas pelo alocador e recuperáveis pelo kernel;
não é uma medida exata do conjunto de trabalho ativo. Em uma amostra da ordenação
de estabelecimentos, 4,85 GiB de RSS incluíam 3,85 GiB de LazyFree e cerca de
0,92 GiB de páginas privadas sujas. Essa amostra não é um pico de memória ativa.

RSS não inclui todo o cache de arquivos ou de metadados do filesystem. A memória
disponível é uma observação do sistema inteiro, sujeita aos outros aplicativos
abertos; não atribuir sua variação integralmente ao produtor medido.

Cada produtor tem `process.log`, `memory.csv` e `result.json`. O `report.json`
consolida status, tempos, picos, schemas e contagens das saídas temporárias.
Falhas não impedem medir os próximos produtores. Ao terminar cada operação,
as saídas e os intermediários exclusivos dessa execução são removidos.
O monitor compara tamanho e mtime dos dumps e checkpoints originais; isso
não constitui uma comparação byte a byte. As conexões de rede Python são
proibidas no worker por um audit hook.

Para interromper somente o produtor atual, crie `stop-current` no diretório da
medição. O resultado é uma medição interrompida, e os picos registrados são
limites inferiores, não o pico de uma execução completa.

`--input-root DIRETORIO` permite usar uma árvore auxiliar de downloads locais.
As substituições são registradas por worker. Na investigação de 2026-11-12,
os Parquets SDS ausentes foram preparados em uma árvore de diagnóstico a partir
dos JSONs existentes em `downloads/sds_cache/public/datasets`, com
`pl.read_json(...).write_parquet(..., compression="snappy")`, a mesma conversão
do Downloader. Não foram executados callbacks de atualização nem downloads.
Neste workspace, a árvore auxiliar usada foi
`--input-root downloads/temp/memory-profile-inputs`.

As medições reais diagnosticam o consumo das entradas disponíveis. Para validar
mudanças de código, use fixtures sem rede que preservem schemas, IDs,
multiplicidades e valores, sem executar o ETL completo ou regenerar assets.

`--unique-root DIRETORIO` desloca os temporários da deduplicação e da ordenação
para outro disco, inclusive o spill de itens de boletins. Cada produtor recebe
uma subpasta exclusiva removida depois da medição. Em 2026-11-12, a primeira
tentativa de urnas foi interrompida por
espera prolongada de I/O no HDD, com RAM estável e swap zero. Urnas e boletins
foram selecionados para medição com esse scratch no SSD; os brutos e destinos
temporários finais continuam no HDD. Os tempos dessas execuções não são uma
comparação de desempenho entre discos ou entre versões do código. O diretório
escolhido e as interrupções ficam registrados no relatório.

Os diretórios `downloads/temp/memory-profile-*` também são excluídos do watcher
do VS Code, para evitar monitorar os milhares de arquivos transitórios do índice.

Endereços, estabelecimentos, sócios e vínculos transformam um arquivo por vez
antes da ordenação externa; o produtor de empresas mantém o scan streaming do
glob em uma parte intermediária. O sort usa pool de 256 MiB e lotes de 1.024
linhas, com 64G de quota de temporários. O tamanho do pool não limita o RSS inteiro do
processo. `TURI_SORT_MEMORY_LIMIT` e `TURI_SORT_MAX_TEMP_DIRECTORY_SIZE` continuam
com precedência. O helper anterior de itens mantém seus padrões de lote e quota.
O sort dos complementos usa 512 MiB e reserva um quarto do pool para iniciar o
merge; o pool anterior de 256 MiB falhou nessa etapa. Uma configuração explícita
de `TURI_SORT_MEMORY_LIMIT` continua tendo precedência nesse produtor.
Para sócios, a unicidade por ID é global; para vínculos, empresa/sócio é único
dentro de cada fonte. Os 16 grupos de hash limitam as tabelas de unicidade sem eliminar
duplicatas entre arquivos que o produtor original preservava.

O DataFusion 55.0 reconstrói o gerenciador de disco ao aplicar `SET` da quota e
perde a configuração anterior do diretório. A análise do
[setter SQL](https://raw.githubusercontent.com/apache/datafusion/55.0.0/datafusion/core/src/execution/context/mod.rs)
e do [RuntimeEnvBuilder](https://raw.githubusercontent.com/apache/datafusion/55.0.0/datafusion/execution/src/runtime_env.rs)
confirmou a causa das falhas anteriores: spill retornando ao temporário do SO,
que nesta máquina está no tmpfs `/tmp`. Aumentar a quota nominal não resolvia.
O helper executa o sort em um subprocesso com `TMPDIR` exclusivo apontando para
o disco escolhido; o ambiente do chamador é preservado. Aplica somente a quota,
sem um segundo `SET` que descartaria o primeiro. Um teste força spill e observa
os arquivos sob o diretório solicitado. As medições anteriores incluem o RSS,
mas não toda a memória do tmpfs; as novas medições usam temporários em disco.

## Resultados de 2026-11-12

Concluídos: 32/32. As métricas completas, schemas, contagens e tentativas estão no [relatório JSON](audits/turi_memory_profile_2026-11-12.json).

Picos de RSS nas principais intervenções:

| Produtor | Antes (GiB) | Depois (GiB) | Swap depois (MiB) |
| --- | ---: | ---: | ---: |
| `elections` | ≥ 8.657 | 1.655 | 0.0 |
| `public_people` | 3.685 | 1.651 | 0.0 |
| `camaradosdeputados_ceaps` | 7.422 | 3.534 | 0.0 |
| `camaradosdeputados_services_supplier` | 7.025 | 0.645 | 0.0 |
| `ibge_addresses` | ≥ 10.427 | 5.642 | 0.0 |
| `receitafederal_business` | ≥ 10.249 | 2.708 | 0.0 |
| `receitafederal_business_establishments` | ≥ 10.741 | 7.298 | 348.0 |
| `receitafederal_partners` | 6.837 | 4.038 | 0.0 |
| `receitafederal_partnership` | ≥ 8.423 | 2.611 | 0.0 |

O símbolo ≥ marca uma execução original interrompida. Não comparar esse valor como se fosse o pico completo. RSS e swap são picos separados. As execuções completas comparáveis preservaram as contagens e os schemas; a igualdade de valores, IDs e multiplicidades das transformações foi validada com fixtures sem rede.

Catálogo completo; tempos incluem a inicialização do processo e não são um benchmark controlado de desempenho:

| Produtor | RSS (GiB) | PSS (GiB) | Swap (MiB) | Tempo (s) |
| --- | ---: | ---: | ---: | ---: |
| `camaradosdeputados_legislatures` | 0.324 | — | 0.0 | 2.3 |
| `elections` | 1.655 | — | 0.0 | 111.4 |
| `candidatures` | 2.066 | — | 0.0 | 31.9 |
| `public_people` | 1.651 | — | 0.0 | 11.3 |
| `camaradosdeputados_mandate` | 0.448 | — | 0.0 | 7.9 |
| `camaradosdeputados_ceaps` | 3.534 | — | 0.0 | 45.3 |
| `camaradosdeputados_mandate_events` | 0.385 | — | 0.0 | 6.4 |
| `camaradosdeputados_mandate_exercises` | 0.352 | — | 0.0 | 1.8 |
| `camaradosdeputados_mandate_exercises_political_party` | 0.358 | — | 0.0 | 1.2 |
| `camaradosdeputados_mandate_office` | 0.477 | — | 0.0 | 3.1 |
| `camaradosdeputados_services_supplier` | 0.645 | — | 0.0 | 13.5 |
| `evm` | 1.297 | — | 0.0 | 169.1 |
| `evm_bulletin` | 5.307 | — | 0.0 | 530.7 |
| `evm_bulletin_items` | 6.329 | 6.259 | 541.0 | 452.7 |
| `gov_amendments` | 0.346 | — | 0.0 | 46.8 |
| `gov_amendments_agreements` | 0.441 | — | 0.0 | 1.3 |
| `gov_amendments_authorship` | 0.445 | — | 0.0 | 1.2 |
| `gov_amendments_items` | 0.346 | — | 0.0 | 0.6 |
| `gov_amendments_resource` | 0.405 | — | 0.0 | 0.8 |
| `gov_amendments_services_supplier` | 0.493 | — | 0.0 | 1.5 |
| `gov_amendments_to_agreements` | 0.336 | — | 0.0 | 0.7 |
| `gov_amendments_to_services_supplier` | 0.559 | — | 0.0 | 1.3 |
| `sds_municipalities` | 0.319 | — | 0.0 | 0.7 |
| `ibge_addresses` | 5.642 | 5.545 | 0.0 | 565.8 |
| `organs` | 0.308 | — | 0.0 | 47.1 |
| `policial_parties` | 1.019 | — | 0.0 | 4.8 |
| `political_parties_directories` | 0.958 | — | 0.0 | 10.1 |
| `receitafederal_business` | 2.708 | — | 0.0 | 138.2 |
| `receitafederal_business_establishments` | 7.298 | — | 348.0 | 549.7 |
| `receitafederal_partners` | 4.038 | — | 0.0 | 50.2 |
| `receitafederal_partnership` | 2.611 | — | 0.0 | 52.5 |
| `tse_voting_locations` | 2.631 | — | 0.0 | 144.5 |

RSS é a soma bruta dos processos vivos e pode duplicar páginas no fork. PSS divide páginas compartilhadas; foi acrescentado na última rodada dos endereços e itens. Ambas as métricas incluem páginas recuperáveis do alocador. Os picos das colunas não precisam ser simultâneos.


O produtor de itens de boletins conferiu 254.345.786 linhas e 2.841.719.245 votos. Seu algoritmo de transformação foi preservado; a medição final usa o novo helper de ordenação com temporários em disco. O produtor de boletins completos produziu 1.860.036 linhas, com redução local de repetições antes do índice em disco; não há baseline completo anterior dessa execução para afirmar uma redução de pico RSS.

Validação: 118 testes Turi com fixtures locais passaram; os sete testes de ordenação também passaram após o último ajuste dos lotes e do merge. Os tamanhos e mtimes dos dumps e checkpoints originais foram preservados. Nenhum asset foi regenerado ou publicado. Os footers das saídas temporárias também foram comparados com os dumps publicados como referência; o JSON registra o resultado por produtor.
