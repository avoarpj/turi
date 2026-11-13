# Memória técnica do Turi independente

## Instalação diretamente com uv sync (2026-11-13)

Removido `scripts/setup.sh`: o Core já é uma dependência Git fixada, cujo build
gera os contratos durante o `uv sync`. O wrapper acrescentava apenas a cópia
condicional do `.env`. O README agora usa `uv sync --locked`, seguido da criação
separada do `.env` quando não existe e da instalação opcional do Chromium para
os downloaders. Não há necessidade de um script de bootstrap do Core no Turi.
As notas anteriores sobre o setup Bash descrevem a alternativa substituída.

Validação: `uv sync --locked --offline --check` não propôs alterações;
`git diff --check` passou. Nenhuma dependência, lock, `.env`, produtor, dado ou
asset foi alterado por essa simplificação; não foi executado ETL.

## Namespace avoar compatível com Pylance (2026-11-13)

O Core estava corretamente instalado na `.venv` e o log do Pylance apontava para
esse Python. A diferença era o `avoar/__init__.py` local: usava
`pkgutil.extend_path` para juntar em runtime o código do Turi e o Core em
site-packages. A análise estática parava no pacote local regular e não encontrava
`avoar.core`. A [documentação do Pylance](https://github.com/microsoft/pylance-release/blob/main/docs/howto/unresolved-imports.md#works-at-runtime-but-pylance-shows-errors)
descreve essa diferença entre runtime e resolução estática.

Removido somente esse `__init__.py` de três linhas. `avoar` agora é namespace
nativo PEP 420, como no pacote Core. Setuptools declara `namespaces = true`
explicitamente; a alteração do pyproject também invalida o build editável antigo
no sync. Core continua externo, sem cópia de contratos ou alterações no Venato.
O README registra que o arquivo de raiz não deve ser recriado.

VS Code aponta para `${workspaceFolder}/.venv/bin/python` neste workspace Linux e
adiciona `${workspaceFolder}/apps/turi/src` aos extraPaths, refletindo os caminhos
que os entrypoints já preparam. As exclusões de dados, caches e `.venv` foram
preservadas; não foram silenciados diagnósticos. O experimento com
defaultInterpreterPath apontando somente à pasta `.venv` fez a versão instalada
tratar o diretório como executável e perder a indexação de bibliotecas; por isso
o caminho final usa o executável. O log posterior confirmou esse Python e a
indexação de 700 arquivos de biblioteca.

Validação estática com Pyright 1.1.414 em ambiente temporário: fixture reproduziu
três `reportMissingImports` com o namespace legado, usando a mesma `.venv`; a
versão nativa resolveu os imports. Um probe gerado por AST reuniu 19 declarações
de import, cobrindo 12 módulos Core e módulos locais de recursos/Venato, sem
diagnósticos. Não foi coletada a lista de diagnósticos da interface do VS Code.

Passaram 123 testes Turi e seis da raiz. O novo teste importa Core e Venato em
subprocesso fora do checkout e sem PYTHONPATH, conferindo que o Core não veio de
uma cópia em `avoar/`. O teste de limpeza após falha de auditoria do sort passou
a isolar `TURI_UNIQUE_TEMP_DIRECTORY`, pois o `.env` local redirecionava o scratch
e invalidava a suposição do teste; o operador não foi alterado.
`uv sync --locked --offline` refez o pacote Turi, sem mudar dependências ou lock;
`git diff --check` passou. Nenhum ETL ou asset foi regenerado.

## Comando de setup padronizado pelo uv (2026-11-13)

O comando de instalação documentado passou a ser
`uv run --no-project bash scripts/setup.sh`. O uv executa Bash disponível no
sistema; `--no-project` deixa o sync exclusivamente a cargo do script e permite
o bootstrap antes da instalação do Turi. Não foi criado um alias de shell em
`[project.scripts]`, que exige entrypoints Python, nem um wrapper Python apenas
para chamar o Bash. Referência: [execução de comandos no uv](https://docs.astral.sh/uv/concepts/projects/run/).

Smoke real offline com `uv run --no-project bash scripts/setup.sh --offline`
passou. Pyproject/lock mantiveram os hashes; `.env` foi criado a partir do exemplo
e removido ao final para restaurar sua ausência anterior. Nenhuma dependência,
ETL, dado ou asset foi alterado. `git diff --check` passou.

## Setup portátil do Core via Git (2026-11-13)

O caminho editável `../core` era uma conveniência da extração do monorepositório
e exigia checkouts irmãos. `uv add` substituiu essa origem por
`https://github.com/avoarpj/core.git`, fixada no commit
`56339faa0e7341f1abc927d0b330e66615edaa3c`, a mesma revisão do checkout local
limpo e de `origin/main` no início desta alteração. `uv.lock` foi atualizado pelo
uv; as versões das demais dependências foram mantidas. O Core continua externo:
seu build gera os contratos Protobuf no ambiente, sem copiar contratos para o
Turi ou exigir um `protoc` instalado separadamente.

`scripts/setup.sh` resolve a raiz pelo próprio caminho, executa
`uv sync --locked` e cria `.env` somente quando não existe. Argumentos adicionais
são repassados ao sync, inclusive `--offline`. Uma falha no sync interrompe o
script antes da criação do `.env`. Git, uv e acesso à rede no primeiro setup
continuam necessários; submódulos de assets e Chromium seguem as instruções
separadas do README. O Core não exige um script gerador próprio no consumidor:
o backend de build do pacote já realiza a geração.

O README removeu a exigência de diretórios irmãos e documenta setup e uso
opcional de `uv add --editable /qualquer/caminho/core` para desenvolvimento,
incluindo o retorno à origem Git fixada. Esse override altera pyproject/lock
localmente; caminhos particulares não devem ser publicados como padrão.

Validação: `uv sync --locked` instalou efetivamente o Core da origem Git.
`direct_url.json` confirmou o commit e a instalação não editável; o check offline
de sync não propôs alterações. O setup real foi executado de `/tmp`, preservando
pyproject/lock. Fixtures cobriram caminho com espaços, repasse de argumentos,
criação/preservação do `.env` e propagação de erro do sync. O `.env` de exemplo
criado pelo smoke real foi removido após comparação exata, restaurando a ausência
anterior desse arquivo. Nenhum `.env` preexistente foi removido ou sobrescrito.

Uma cópia temporária de pyproject/lock em diretório sem irmão `core` resolveu
com `uv sync --locked --offline --dry-run --no-install-project`. Esse dry-run
valida resolução portátil com cache aquecido, não uma instalação completa a frio.
Passaram offline 123 testes Turi e cinco da raiz, incluindo Core Protobuf real,
Venato e BrazilGEO com fixtures. `bash -n scripts/setup.sh` e `git diff --check`
passaram. Nenhum ETL, download de dados públicos, asset ou produtor foi executado
fora dos testes com fixtures; o checkout externo do Core foi apenas lido.

## Ordenação dos estabelecimentos por faixas UInt64 (2026-11-13)

`infra/parquet_sort.py` ganhou staging particionado opcional por intervalos
disjuntos da primeira chave `UInt64`. Estabelecimentos ativa 64 faixas de
`empresa_id` e batches de 8.192 linhas. A chamada local tinha `batch_size=256000`,
mas o helper ainda não aceitava esse argumento; agora o aceita e o repassa ao
worker. Não aumentar simplesmente o batch: no ensaio isolado de um milhão de
linhas, 256 mil linhas por batch foi mais lento que 1.024.

Cada fonte é transformada uma vez e gravada diretamente nas faixas; a divisão
inteira preserva os limites de UInt64, inclusive 2^64-1. Nulos entram na faixa
zero. O worker ordena cada faixa por `(empresa_id, id)` e grava as faixas em ordem,
sem um merge global. A coluna auxiliar não é publicada. Mantidos schemas,
identidades, duplicidades, join municipal m:m, Snappy final, metadados de sort,
row groups finais de 65.536 linhas, auditoria e troca atômica. O buffer final
atravessa faixas; staging Zstd usa row groups de 16.384 para reduzir os buffers
dos writers das partições. Faixas desbalanceadas continuam podendo usar spill.

O pool padrão de 256 MiB e as variáveis de memória, scratch e quota continuam.
O pool não limita RSS nem buffers Polars/Arrow. Não foi aplicado um segundo SET
de runtime DataFusion, que perderia a quota no 55.0 instalado. As faixas exigem
potência de dois entre 2 e 256 e chave principal UInt64; combinação com unique
é recusada antes da escrita. Outros produtores e manutenção mantêm o sort global.

Validação: 123 testes Turi offline passaram, incluindo cinco casos novos de
limites, nulos, ordem secundária, faixas esparsas, entrada vazia, schemas ricos,
duplicidades, fronteiras de row groups, faixa concentrada com pool pequeno,
recusa de parâmetros e falha de auditoria sem substituir o publicado.
`git diff --check` passou. Nenhuma dependência ou lock foi alterado.

Benchmark sintético no HDD, com oito milhões de linhas largas, pool de 256 MiB
e oito fontes: helper antigo 112,50 s; faixas 77,43 s (-31,2%). A etapa do worker
caiu de 63,19 para 8,90 s; redistribuição/staging e demais custos aumentaram de
49,31 para 68,53 s. Pico RSS agregado amostrado caiu de 3.389 para 2.872 GiB;
páginas compartilhadas podem ser contadas duas vezes. Com um milhão de linhas,
o padrão de 256 MiB regrediu de 8,74 para 11,59 s, enquanto o pool de 64 MiB
caiu de 18,19 para 13,23 s. Faixas têm custo de arquivos e redistribuição.

São observações únicas, com cache do SO e writeback, sem drop de caches ou fsync;
não extrapolar para a base real. Um milhão de linhas teve todas as colunas
comparadas exatamente entre saídas; oito milhões teve todos os pares de chaves
comparados, inclusive multiplicidade oito, além de schema, contagem e ordenação
física global. Payloads da fixture maior não foram integralmente comparados.
Método, versões, tempos e limites no
[relatório](audits/parquet_sort_ranges_2026-11-13.json); contrato em
[parquet_ordering.md](parquet_ordering.md).

Do dump publicado de estabelecimentos foi lido somente o footer (72.605.022
linhas). Nenhum ETL completo, asset, download ou dump real foi executado ou
regenerado. As fixtures e temporários exclusivos do benchmark foram removidos.
Processos já iniciados precisam ser reiniciados para carregar o helper novo;
nenhum processo ou checkpoint do usuário foi interrompido/removido.

## Exclusões do Pylance para dados e temporários (2026-11-13)

`.vscode/settings.json` tinha somente `assets/localidades` em
`python.analysis.exclude`. A lista agora cobre `assets`, `downloads`,
`parquet_dumps`, `venato_data`, metadados de execução `__metadata__`, scratch
de deduplicação/ordenação/DataFusion, caches, ambiente virtual e artefatos de
build/instalação. Código em `apps`, `avoar` e testes continua no escopo.
Não foram desativados indexação, diagnósticos ou resolução de imports.

Watchers e buscas também excluem as árvores de dados e temporários. Mantidos
`files.exclude`, `explorer.excludeGitIgnore: false` e a regra preexistente de
watcher para `downloads/temp/memory-profile-*`; as pastas continuam visíveis.
A [documentação do Pylance](https://github.com/microsoft/pylance-release/blob/main/docs/settings/python_analysis_exclude.md)
explica que exclusões limitam descoberta; arquivos abertos ou importados ainda
podem ser analisados. A extensão instalada é 2026.4.1.

Validação offline com `uv run --no-sync --offline`: JSON sem chaves duplicadas,
tipo da configuração conferido no manifesto da extensão, 16 caminhos
representativos cobertos por análise/watchers/busca e todos os 160 arquivos
Python de código/testes encontrados fora das exclusões. `git diff --check`
passou. Não foi medido o tempo de inicialização nem reproduzido o travamento
do `turi run`; reiniciar o language server no editor para observar o efeito.
Nenhum ETL, coleta, asset, dependência ou lock foi alterado por esta mudança.

## README como apresentação do projeto (2026-11-12)

O README da raiz foi reescrito para leitores do repositório: escopo do Turi,
fontes oficiais, artefatos produzidos, instalação, coleta, processamento,
indexação, agendamento, mapas, estrutura, desenvolvimento e licença MIT.
Foram retiradas as notas de migração e referências à instalação específica;
o histórico permanece na documentação técnica. O setup descreve a dependência
editável do Core em `../core` e o submódulo dos assets de partidos.

Validação estática: 15 links locais existentes, seis blocos shell aceitos por
`bash -n`, quatro entrypoints conferidos no pyproject e IDs dos exemplos
confirmados via AST dos produtores. Nenhum exemplo foi executado, nem foram
iniciados downloads, ETL ou geração de assets. Alterações somente documentais.

## Deduplicação sequencial para HDD (2026-11-12)

`infra/diskful_unique.py` passou do índice SHA-256 com marcador/arquivo por
chave para ordenação externa de chaves canônicas e posições. O índice anterior
fazia consultas aleatórias, criava dois arquivos por chave e tornava execução e
limpeza muito lentas no HDD. A assinatura pública e os produtores foram mantidos.

Cada batch Arrow gera um bloco ordenado com chave exata, primeira/última posição
e contagem. Merges de até 32 leitores coalescem as chaves. As posições escolhidas
são ordenadas em blocos, e uma leitura sequencial recupera as linhas originais.
Mantidos any=first, first, last, none, ordem, schemas, IDs, nan/zero assinado e
precisão temporal, inclusive tipos aninhados. Não há dependência nova, banco,
DISTINCT global ou coleção de todas as chaves em RAM. A contagem da seleção é
auditada antes de devolver o LazyFrame. Sessões, retenção e limpeza continuam.

`TURI_UNIQUE_MEMORY_LIMIT`/`memory_limit` agora orçam os buffers de I/O do merge,
não um pool DataFusion; o helper lê via PyArrow. No padrão, até 32 leitores e
um writer têm buffers de até 1 MiB cada. O orçamento não limita RSS, alocações
anteriores, largura de um batch, listas de runs ou metadados Parquet.

Validação: 118 testes Turi, incluindo 15 do helper/produtores; múltiplos passes
forçados, escolhas de representantes, fronteiras ambíguas, todos os keeps,
uint64, ns, categorias, listas, nulos, erros e limpeza. Benchmark offline no HDD:
1 milhão de linhas/100 mil chaves em 1,647 s, pico RSS até saída 286,5 MiB
(347,2 MiB com auditoria). Referência DataFusion independente conferida com
EXCEPT ALL bidirecional. Fixture comparável de 10 mil linhas/5 mil chaves:
índice antigo 10 mil arquivos de chave/0,157 s; novo um bloco de chaves/0,055 s.
Fixtures pequenas cabem no cache do SO; não extrapolar esses tempos para o ETL.
Relatório em `docs/audits/diskful_unique_external_2026-11-12.json`; contrato e
algoritmo em `docs/turi_diskful_unique.md`. Nenhum ETL completo ou asset foi gerado.

O processo já iniciado conserva o módulo antigo: precisa ser reiniciado para
carregar a mudança, recomeçando o produtor em andamento. Checkpoints concluídos
não foram apagados. Nenhum índice ou processo ativo do usuário foi interrompido
ou removido; os benchmarks usaram diretórios próprios e descartaram suas fixtures.
As medições completas dos 32 produtores abaixo precedem esta substituição.

## Reaproveitamento dos caches SDS de deputados (2026-11-12)

Por pedido do usuário, os Parquets antigos de detalhados e histórico foram
copiados para `downloads/sds/federal_deputies_detailed/restored-20261027.parquet`
e `downloads/sds/federal_deputies_history/restored-20261027.parquet`. São as
conversões usadas na medição anterior, provenientes dos JSONs locais de 27/10
em `downloads/sds_cache/public/datasets`; os JSONs e caches por deputado foram
preservados. A cópia foi conferida por SHA-256.

Os dois metadados Downloader foram marcados como bem-sucedidos, sem fontes
pendentes, com caminhos absolutos existentes e `downloaded_at` de
2026-11-12 14:41:29 (hora local). Os lifetimes continuam em 28 dias para
detalhados e 3 dias para histórico; a data dos dados antigos não foi alterada.
Auditoria e cópia do metadado anterior do histórico em
`downloads/temp/sds-cache-restore-20261112T144129/`.

Validação sem rede: `get_meta_files_or_download` retornou os arquivos dos dois
caches com zero erros, com `download_from_sources` bloqueado por mock. Nenhum
callback SDS, servidor, coleta, ETL ou regeneração de assets foi executado.
Não houve alteração do código ou dos lifetimes para essa restauração.

## Perfil de memória por produtor (2026-11-12)

Por pedido explícito do usuário, os 32 produtores concluíram individualmente
com entradas reais locais, processos novos e saídas isoladas. Não foi executado
o runner completo para validar código, nem foram regenerados assets. Método e
comparativo em [turi_memory_profiling.md](turi_memory_profiling.md); histórico,
schemas, contagens e métricas no [JSON de auditoria](audits/turi_memory_profile_2026-11-12.json).

Picos RSS observados: eleições ≥8.657 → 1.655 GiB; pessoas públicas
3.685 → 1.651 GiB; CEAP 7.422 → 3.534 GiB;
fornecedores CEAP 7.025 → 0.645 GiB; endereços
≥10.427 → 5.642 GiB; empresas ≥10.249 → 2.708 GiB;
estabelecimentos ≥10.741 → 7.298 GiB; sócios
6.837 → 4.038 GiB; vínculos ≥8.423 → 2.611 GiB.
O símbolo ≥ identifica uma tentativa original interrompida, não seu pico completo.
Picos separados de RSS, PSS e swap não necessariamente coincidem. RSS agregado
pode duplicar páginas compartilhadas. Os tempos não são benchmarks controlados.

Itens de BU conferiu 254.345.786 linhas e 2.841.719.245 votos; seu algoritmo de
transformação foi preservado. Pico PSS final: 6.259 GiB;
RSS bruto agregado: 6.329 GiB. O fork pode duplicar
temporariamente o RSS sem criar o mesmo volume de páginas físicas novas.
PSS distribui páginas compartilhadas, mas inclui páginas recuperáveis e não
mede só memória ativa. Não subtrair picos independentes de PSS e LazyFree.

O profiler registra RSS, VmHWM, swap e memória disponível, com intervalo alvo de
100 ms e timestamps efetivos no CSV, além de ru_maxrss, schemas e linhas. As
rodadas finais incluem descendentes vivos; a última também registra PSS e
LazyFree via smaps_rollup. Não foi acrescentado teto global nem alterado
POLARS_MAX_THREADS. Cada process_data lê dependências já publicadas, ignora
lifetimes e preserva checkpoints, Avro, Bloom filters e Venato.

Causa confirmada no plano físico do Polars 1.38: cs.string().replace([""], None)
produzia in-memory-map, materializando colunas mesmo em streaming. O helper
scripts/bricks/nullish.py usa condição elementwise, com igualdade de valores,
schema, ordem e hashes completos nas fixtures. Aplicado a endereços, empresas
e estabelecimentos.

Eleições reduz oito colunas por arquivo antes dos joins. Urnas reduz números
de série por arquivo, alinhando o schema global antes do unique, inclusive
tipos misturados, zeros à esquerda e zero assinado. Boletins reduz linhas
iguais mantendo a primeira ocorrência e sua ordem. A deduplicação global
existente continua; infra/diskful_unique.py não foi alterado.

CEAP expande um download aninhado por vez, mantendo schema e ordem de campos
dos hashes de despesas e comprovantes. Fornecedores projeta somente as folhas
Parquet de documento/nome no PyArrow. Pessoas públicas projeta os campos usados
antes da coleta que antes retinha o bruto inteiro.

sink_sorted_parquet_parts transforma fontes separadamente, alinha tipos como o
concat anterior e ordena via DataFusion com Arrow, restauração do schema,
contagem de linhas e substituição atômica. Preserva compressão, IDs e
multiplicidades. A unicidade opcional em 16 grupos suporta somente keep="any":
sócios usa id global; vínculos usa empresa/sócio por fonte, mantendo repetições
entre arquivos. Não aplicar a escolhas first/last dependentes de ordenação.

DataFusion 55.0 recria o gerenciador de disco ao aplicar SET de quota/fan-in,
perdendo o diretório anterior; um segundo SET também descarta o primeiro. O
spill retornava ao /tmp em RAM. As notas anteriores de spill fora do tmpfs
descreviam a intenção da configuração e devem ser lidas com esta correção.
O helper agora usa subprocesso com TMPDIR exclusivo no scratch, sem mudar o
ambiente do chamador. Aplica somente a quota; não foi adicionada dependência.
Um teste força spill e observa os arquivos no destino escolhido.

Os cadastros usam lotes de 1.024 linhas, pool de 256 MiB e quota de 64G. O merge
de complementos precisou de pool de 512 MiB com um quarto reservado para merge;
TURI_SORT_MEMORY_LIMIT explícito continua com precedência. Itens mantém seus
padrões de lote/quota de 16.384/24G. O pool não é um teto do RSS. A leitura usa
schema_force_view_types=false. O comando maintenance/sort_final_parquets.py
reutiliza o helper, mantendo partições, row groups e auditoria antes da troca.

Houve ensaios com scratch em HDD e SSD. A rodada corrigida de estabelecimentos
no HDD foi interrompida por I/O; os seis produtores que usam a ordenação externa
concluíram com scratch no SSD. Brutos e destinos isolados ficaram no HDD. Os
logs das tentativas e as CSVs foram preservados; os temporários exclusivos
dos ensaios foram removidos depois das medições.

Os JSONs SDS existentes foram convertidos pela mesma leitura Polars do
Downloader para uma árvore de diagnóstico, sem servidor, rede ou callbacks de
atualização. As substituições são registradas. Fotos são selecionadas com
movimentos simulados, preservando fontes e assets. O Parquet CEAP vazio foi
ignorado como antes; não foi removido nem baixado novamente.

Validação: 118 testes Turi com fixtures sem rede passaram, incluindo hashes,
schemas, multiplicidades, joins municipais m:m, complementos repetidos, uint64,
decimais, listas, tipos históricos e limpeza. Todos os 32 produtores mantiveram
contagens e schemas dos dumps publicados como referência. Tamanho/mtime dos
dumps e checkpoints originais foram preservados; isso não é um hash byte a byte.
A alteração preexistente do usuário em DataScript.py foi mantida. Core,
Venato, lock e assets não foram modificados.

## Assets locais e exclusões do VS Code (2026-11-09)

`/assets/brazilgeo/` e `/assets/candidatures/` são ignorados pelo Git. Os 55
arquivos gerados do BrazilGEO foram retirados somente do índice com
`git rm --cached`; os 601,36 MiB continuam no disco. O gerador e sua documentação
em `apps/scripts/brazilgeo` permanecem versionados.

`.vscode/settings.json` exclui as duas pastas das buscas e do monitoramento de
arquivos. `files.exclude` explicitamente falso para essas pastas e
`explorer.excludeGitIgnore: false` mantêm ambas visíveis no explorador.
As exclusões do editor não removem arquivos já presentes no histórico do Git.

Por autorização do usuário, a limpeza do histórico da `main` remove somente
`assets/brazilgeo/` do commit de importação, preservando sua autoria, datas,
mensagem e demais arquivos. O histórico anterior foi copiado para o repositório
bare irmão `../turi-before-brazilgeo-2026-11-09-153fce8.git`, fora do workspace.
A publicação usa `--force-with-lease` com o hash remoto anterior explícito.

Validação sem rede: JSON válido, regras de `git check-ignore --no-index`
incluindo subpastas e caminhos de controle, nenhum asset BrazilGEO no índice e
comparação dos metadados dos 55 arquivos locais. O diff do commit reescrito
contém somente as 55 remoções; o commit seguinte altera apenas ignore,
configuração do editor e esta memória. Nenhum ETL ou gerador foi executado.

## Cookie CKAN do TSE configurável (2026-11-08)

O downloader TSE lê `TSE_CKAN_COOKIE` do ambiente após carregar as configurações
que leem o `.env`. O conteúdo completo do header é opcional: ausente, vazio ou
apenas espaços omite `Cookie` da configuração inicial da sessão. O valor fixo
foi removido, sem fallback. A configuração ocorre no import; reinicie o processo
para reler o ambiente. Exemplo vazio em `.env.example`; contrato em
[turi_downloads.md](turi_downloads.md).

## Extração do monorepositório (2026-11-08)

Estado atual: produtores em `apps/turi/src`, BrazilGEO em `apps/scripts/brazilgeo`,
assets e dumps na raiz. Venato foi copiado sem alterações de implementação ou
YAMLs para `avoar/infra/venato`; sua atualização continua ligada ao pipeline.
Core é a dependência UV editável `../core`, que gera os contratos Protobuf ao
instalar. Não existe cópia local dos contratos antigos. Seus enums públicos
mantêm a interface consumida pelos produtores. Testes que usavam `model_validate`
foram adaptados à construção e validação explícita do Protobuf.

Os entrypoints instalados `turi`, `turi-download` e `turi-schedule` preparam o
caminho de imports existente, evitando reescrever todos os produtores. A raiz
única tem `project_root.py`; o marcador aninhado antigo do Turi não foi copiado.
Checkpoints de execução não foram migrados, portanto não presumir que uma
execução será pulada apenas porque existem dumps copiados.

SDS incorporado em `downloaders/_sds`, acionado pelos callbacks locais em
`downloaders/sds_callbacks.py`. Não precisa de `localhost:8000`. Os produtores
preservam nomes/diretórios e referências históricas à origem SDS. Detalhes,
bootstrap, cache e limites em [turi_sds.md](turi_sds.md). O código e os dados de
origem foram copiados, nunca movidos ou removidos.

Validação da extração: 104 testes Turi/SDS, 3 BrazilGEO e 2 de montagem real
core/Venato passaram. O smoke Tantivy fez ingestão e busca com uint64 acima de
INT64 em diretório temporário. Os 54 arquivos de scripts, os 2 do BrazilGEO e os
9 do Venato foram comparados byte a byte com a origem, sem diferenças; checkpoints
não entram nessa comparação. `uv sync --locked` e a ajuda dos quatro comandos
instalados passaram. Dados foram copiados, sem executar ETL ou reconstruir índices.
O relatório de inventário fica em `docs/audits/turi_migration_2026-11-08.json`.

A descoberta de pacotes setuptools exclui explicitamente assets, dumps, downloads,
índices e testes: sem isso o setup percorria centenas de milhares de fotos.
Tantivy foi fixado em 0.26.0, como no lock da origem, para preservar o formato
dos índices consumidos pelos outros serviços. Também foram preservadas as versões
anteriores de curl-cffi, msgspec, Playwright e adbc-driver-manager. Os 109 testes
foram repetidos com essas versões e passaram.

O cache original do SDS (`temp-downloads` e `public`) é aproveitado dentro de
`downloads/sds_cache`; isso evita começar novamente pelo bootstrap completo.

A seção abaixo é memória histórica do monorepositório Avoar. Caminhos Fons/Rostra,
procedimentos de API e propostas antigas podem pertencer a outros repositórios;
confira o código atual antes de aplicar. Medições históricas não são medições
novas deste checkout.

---

# Memória técnica e fluxo de desenvolvimento

Atualizada em 2026-11-07, a partir das sessões de implementação de eleições,
candidaturas, mandatos, API e análise de concorrência do Venato.
Este documento é uma memória consultável, não uma
promessa de que os dados locais ou o ambiente permaneceram iguais. Confira o código,
os schemas e a configuração atuais antes de executar procedimentos.

## Resolução de identidade empresarial fora do core (2026-11-07)

`empresa_id_from_base_cnpj` foi movida de `avoar/core/opendata/business/identity.py`
para `apps/fons/infra/opendata/business/identity.py`: o cálculo usa Polars e é
consumido apenas pelo resolvedor de CNPJ do Fons. Imports da aplicação e dos
testes foram atualizados, sem alias no core. A seed continua compartilhada em
`avoar/core/opendata/common/identity.py`. Validação, entrada textual e hash foram
preservados; não é necessário regenerar dumps ou índices. O teste de arquitetura
também impede imports de Polars no core.

Validação: 14 testes de arquitetura Fons e detalhes empresariais passaram,
incluindo inicialização instalada via Granian, comparação com o hash do produtor
e resolução HTTP de CNPJ. `git diff --check` passou.

## Registros CEAP no Rostra (2026-11-07)

A lista usa `ExpenseRecord.svelte`, com categoria/subcategoria em destaque,
fornecedor e CNPJ/CPF formatado, descrição, emissão e os três valores
(documento, glosa e líquido). Comprovantes mantêm expansão nativa e URLs
HTTP/HTTPS; o nome do fornecedor CNPJ abre o modal do estabelecimento.
Usa tokens visuais dos detalhes e layout adaptado a telas pequenas, preservando
SSR, contrato da API, cache e paginação. Subcategorias desconhecidas preservam
seu código; zero não gera uma classificação adicional.

Validação: 19 arquivos de testes Rostra, check sem erros (dois avisos existentes
em PersonDetails) e build. Smoke Chromium do componente renderizado com fixtures
em 1137 e 390 px confirmou ausência de overflow horizontal e expansão por teclado.
Esse smoke isolado não verifica a integração do modal ou a paginação com API real.
Veja [ceap.md](ceap.md) e [rostra_details.md](rostra_details.md).

## Como iniciar e implementar uma feature

1. Leia `git status --short` e as instruções locais. O workspace costuma conter
   alterações em andamento do usuário; não restaurar arquivos ou limpar mudanças alheias.
2. Leia os modelos básicos em `avoar/core/opendata/<dominio>`, os DTOs em
   `apps/fons/dto/<dominio>.py` e a rota mais parecida.
   Confira também o produtor em `apps/turi/src/scripts/operations` se a feature
   depende de um campo novo ou de um relacionamento entre datasets.
3. Implemente o caminho completo no Fons: contrato do query service, implementação
   DataFusion, caso de uso, tipagem/montagem dos serviços e registro do controller. Reutilize a
   montagem dos detalhes quando a mesma entidade aparecer em mais de uma resposta.
4. Preserve os formatos de retorno e a semântica de ausência. Teste com fixtures
   pequenas que exponham os riscos da mudança; depois consulte amostras reais,
   preferencialmente com conexão somente leitura.
5. Se a mudança afeta IDs ou ETL, regenere os dependentes e audite cobertura e
   integridade antes de publicar. Uma alteração de API isolada não exige regeneração.
6. Relate o que foi validado, as limitações e se é necessário reiniciar conexões.
   Atualize esta memória quando surgir uma decisão reutilizável.

## Mapa do projeto

| Área | Local e função |
|---|---|
| Modelos básicos dos dados | `avoar/core/opendata/<dominio>/` |
| DTOs e parâmetros da API | `apps/fons/dto/<dominio>.py` |
| Interfaces e cursores da API | `apps/fons/application/opendata/<dominio>/` |
| Casos de uso | `apps/fons/application/opendata/<dominio>/usecase.py` |
| Tipagem dos serviços Fons | `apps/fons/application/services.py` |
| Montagem das dependências | `apps/fons/bootstrap.py` |
| Consultas DataFusion | `apps/fons/infra/opendata/<dominio>/` |
| Controllers Fons | `apps/fons/controllers/opendata/` |
| Registro de rotas e logging | `apps/fons/main.py` |
| Operações Turi | `apps/turi/src/scripts/operations/` |
| Expressões compartilhadas | `apps/turi/src/scripts/bricks/` |
| Execução e seleção das operações | `apps/turi/src/scripts/entrypoints/opendata_dumps.py` |
| Descoberta e dependências Turi | `apps/turi/src/infra/datascript/discovery.py` |
| Metadados e caminhos Turi | Cada produtor; `config/projectsettings/scripts.py` só para caminhos compartilhados |
| Caminho dos dumps | `avoar/projectsettings/globals.py` |
| Sessão DataFusion da API | `apps/fons/infra/datafusion/client.py` |
| Busca textual/schema | `avoar/infra/venato/core.py`, `avoar/infra/venato/indexes/*.yaml` |

## Produto de dados e DTOs do Fons: implementado (2026-11-07)

Direção definida pelo usuário: Avoar como produto de dados, com dumps oficiais
para download e acesso cloud comercial pelo BigQuery. Fons/Rostra serão
consumidores e showcases, usando os dumps oficiais em produção.

Implementada a separação descrita em
[data_product_architecture.md](data_product_architecture.md): o core contém
modelos/fatos básicos, vocabulários e identidade; DTOs, filtros, paginação,
cursores, interfaces, usecases, consultas, sessão DataFusion e cache HTTP estão
no Fons. `build_services` em `apps/fons/bootstrap.py` compõe `FonsServices` e
o lifespan injeta `fons_services`. Os caminhos antigos dos módulos movidos
foram removidos e seus consumidores internos atualizados, sem aliases no core.

Os DTOs têm campos próprios, incluindo as respostas básicas. Enumerações
continuam compartilhadas. IDs canônicos são inteiros uint64; o alias JSON em
string pertence ao Fons. A identidade empresarial compartilhada preserva o
hash e a seed. `business_id` foi corrigido para `empresa_id` no core, DTOs,
SQL, HTTP/OpenAPI e Rostra, usando a coluna que já existe nos dumps.

Preservados `JSON_STRING`/`DICT` sem construir/validar modelos; somente
`MODEL_PARSED` valida DTOs. As projeções públicas antes baseadas em `SELECT *`
agora selecionam campos explicitamente. Testes acrescentam colunas aos dumps
e verificam detalhes/coleções/recursos sem vazamento, com Pydantic bloqueado.

Venato permanece compartilhado; seu produtor de endereços não importa mais
settings do Turi. `parse_size` está em `avoar/common/resources.py`, e Redis
é configurado no Fons. Um teste em subprocesso descobre o catálogo Turi sem
carregar Fons/Litestar/Redis, mesmo com uma configuração Redis inválida.

Estatísticas dos Parquets locais confirmaram IDs uint64 acima de INT64 com
sinal em empresas, estabelecimentos, mandatos e candidaturas. A documentação
BigQuery registra falha de carga direta nesse caso. Mapeamento cloud e versão
de representação permanecem decisões pendentes; não alterar hashes/IDs nesta
refatoração. Dumps físicos atuais não foram alterados.

Contratos por dataset, publicação de releases imutáveis e integração cloud
continuam como evolução futura. Nenhum dump ou índice foi regenerado.
Reiniciar Fons/Rostra após a troca; caches antigos podem conter `business_id`
até expirar. Para troca imediata, coordenar namespace Redis e cache do cliente.

Validação e comparação OpenAPI registradas em
[audits/fons_dto_migration_2026-11-07.json](audits/fons_dto_migration_2026-11-07.json).
Passaram 94 testes API/infra, 93 Turi e os 18 arquivos de testes do Rostra,
além de check/build e wheel. O check mantém dois avisos de referências iniciais
em `PersonDetails.svelte`. Smoke real sem Redis retornou órgãos/estabelecimento
com HTTP 200 e vínculo `empresa_id` correto. Não houve carga BigQuery.

Correção posterior de inicialização: a instalação editável antiga da `.venv`
ainda registrava só `apps.turi`/`avoar`. O include `apps.fons*` no pyproject e
o build da wheel não atualizaram esse finder; executar pela raiz mascarava a
falha. Reinstalado apenas o projeto com
`uv pip install --python .venv/bin/python --no-deps --no-build-isolation --reinstall --editable .`.
O dry-run de `uv sync` pretendia recriar toda a `.venv` após atualização do
Python 3.14.7 para 3.14.9, por isso o reparo foi direcionado. Testar imports
instalados fora do checkout: o novo teste usa `python -I`, cwd temporário e o
loader Granian com alvo por arquivo e por módulo. Não corrigir isso inserindo
`sys.path` manualmente em `main.py` ou editando o finder gerado.

## Scripts Turi: descoberta, dependências e metadados (2026-11-07)

Os 32 produtores declaram ID, cron, fonte/link/descrição, entradas/saídas,
dependências por `script_id` e tags na própria classe `DataScript`. Seus valores
podem ser lidos por `script_instance`. `persist_data`/`ExecutionMode` foram
removidos; processamento continua escrevendo diretamente os Parquets. Settings
não exige mais PostgreSQL e mantém apenas configuração geral/caminhos comuns.

O entrypoint descobre instâncias em `scripts/operations`, resolve pré-requisitos
antes dos consumidores e deduplica o plano. Ciclos e IDs ausentes são erro antes
do ETL. Histórico JSON, IDs e lifetimes anteriores foram preservados. Cada script
decide seu skip; dependência pulada não pula o consumidor. Não foi acrescentado
supervisor de recursos nem paralelismo. Imports não devem iniciar downloads;
o NLTK agora é preparado sob demanda no processamento de pessoas.

`run_all_scripts.py [script_id ...] [--no-update-venato]` seleciona operações sem
editar o entrypoint. Bloom filters alcançam somente saídas efetivamente geradas.
Venato reconstrói índices apenas se algum script executado tem `VENATO_INCLUDED`
e a flag não está ativa. Municípios também têm a tag porque alimentam o texto
do índice de endereços. Não há reindexação por tags apenas em scripts pulados.

`write_metadata` publica `metadata.avro` com Polars ao lado de cada saída,
mantendo linhas de outros produtores que compartilham o diretório. Datas são
ISO UTC; listas têm schema string explícito. JSON de execução é atualizado só
depois do processamento/Avro. Substituições são atômicas por arquivo, sem
transação global. Dumps pulados recebem o Avro na próxima execução efetiva.

Contrato, comandos e limites em [turi_scripts.md](turi_scripts.md). Os 93 testes
Turi passaram, com fixtures temporárias e descoberta real dos 32 scripts; smoke da CLI gerou
três órgãos, Avro, checkpoint e Bloom filters, e a segunda chamada pulou por
lifetime. Nenhum dump ou índice de produção foi regenerado.

## Concorrência do Venato: diagnóstico, sem implementação (2026-11-07)

Venato continua embutido no Fons. `search_ids`/`search_scored_ids` coletam todos
os hits antes de filtros/paginação; `limit=20` na API não limita essa etapa.
As buscas já usam threads AnyIO, mas o limitador padrão de 650 tokens é
compartilhado com outras operações. O orçamento DataFusion não limita o RSS
do processo nem as listas/resultados do Venato. Redis não consolida misses
concorrentes; timeout do cliente não comprova cancelamento do trabalho nativo.

Diagnóstico com app/lifespan/dependências reais via ASGITransport, sem Redis,
DataFusion 512 MiB/duas partições: três rajadas de `*`, 20 pessoas por resposta,
índice local com 599.577 documentos. Mediana da busca: 682 ms isolada, 3.913 ms
com quatro e 8.675 ms com oito simultâneas. RSS máximo do processo: 564, 1.042
e 1.715 MiB. A mediana da rota de órgãos permaneceu perto de 11 ms, com pico
de 516 ms sob oito buscas e atraso máximo do loop de 494 ms. Não interpretar
essas rajadas como capacidade HTTP/produção ou memória incremental do Venato.

Um semáforo apenas no harness, admitindo uma busca por vez entre quatro
requests, melhorou a vazão e reduziu RSS. Nenhuma proteção foi incorporada
ao app. Admissão com fila limitada, processo servidor dedicado e contrato de
resultados em lotes são propostas, não estado implementado. Separar processo
isola interpretador/heap, mas não resolve sozinho CPU/disco compartilhados,
hidratação DataFusion ou transferência de todos os IDs. Preservar filtros,
completude das páginas e políticas atuais de ranking/cursores ao evoluir.

Relatório e reprodução em [venato_server.md](venato_server.md), com
[métricas e hashes das fontes](audits/venato_concurrency_2026-11-07.json).
Não foram executadas buscas empresariais completas de milhões de hits nem
um servidor separado. Comparação com isolamento ainda precisa ser medida.

Direção especificada pelo usuário para a evolução: servidor apenas de consulta
sobre diretório de índices Tantivy existentes, sem receber dados para ingestão,
com QUIC e Arrow IPC em RecordBatches. Ainda é proposta. Conexão persistente,
consulta por stream e limites de produção/fila fazem parte do desenho; streaming
de transporte não torna incremental a coleta atual de todos os hits. O schema
lógico derivado dos YAMLs deve acompanhar os índices para distinguir `u64`
armazenados como `i64`; IDs trafegam como `uint64` no Arrow. Não presumir que
Arrow IPC sobre QUIC seja interoperável com Arrow Flight/gRPC.

## Desempenho eleitoral no perfil sem mandatos (2026-10-29)

`public_people/{id}/candidatures` lista candidaturas sem depender de mandatos,
com ano, IDs exatos e turnos/datas. O catálogo não agrega votos nem altera o
caminho rápido do detalhe da pessoa. Pessoa inexistente retorna 404; catálogo
vazio retorna `[]`. No Rostra, Candidaturas é a abertura padrão somente quando
não há mandatos registrados; isso não comprova derrota eleitoral. Perfil com
mandatos mantém sua abertura e também oferece a seção de candidaturas.

`candidature/{id}/votes` preserva o resumo municipal e inclui estados e votos
sem UF/local físico por turno. `votes/locations` exige `turno_eleicao_id`, aceita
UF/município e pagina por votos decrescentes + município/zona/número ascendente,
com cursor exclusivo de quatro campos. Filtrar os fatos por candidatura exata,
eleição e turno antes do join/agregação geográfica; não resolver por nome/número.
Somar seções por chave física normalizada e resolver metadados históricos apenas
para a página, pela data e turno. Cadastro ausente/ambíguo não descarta votos ou
multiplica locais. Preservar null versus zero e votos sem geografia nos totais.

Catálogo tem seed SSR quando necessário. Rankings e locais são consultas sob
demanda, com candidato/turno/filtros/cursor em todas as chaves. Não carregar
quantitativos financeiros completos para exibir a votação. Preservado
o endpoint/mapa municipal anterior. Não exige ETL/reindexação; reiniciar Fons.

Mapa atual da candidatura: começa no Brasil, independentemente da espera pelos
votos, com um único número por UF. Os pontos de rótulo ficam no interior da maior
parte de cada UF; não usar símbolos em MultiPolygon diretamente, pois repetem
números em ilhas/partes da mesma UF. Em zoom 5,5, mostrar rótulos municipais e
detalhar UFs por viewport usando `nearbyStates`/limites da força partidária.
Padrão de duas UFs residentes, configurável de 1 a 27; uma carga geométrica por
vez, removendo/abortando estados fora do conjunto. `Maps/geometry.ts` compartilha
o timeout com a força partidária e aceita cancelamento explícito na candidatura.
Geometria municipal segue por URL ao worker; votos já estão no resumo e não
exigem novas consultas ao aproximar. Trocar turno reutiliza fontes. Não impor
maxBounds que corte o país no mobile. Destruir mapa/observer ao sair.

Ranking municipal: clicar/acionar uma linha enquadra e destaca o município no
mapa e leva foco ao canvas. `states/<UF>.bounds.json` fornece os limites exatos,
sem trazer a malha completa para a thread principal ou depender de tiles já no
viewport. A UF escolhida tem prioridade no limite de residentes; cliques antigos
não podem mover a câmera após outra seleção/retorno ao Brasil/interação manual.
Manter turno e filtros; sem UF/limites válidos, não adivinhar um destino.

`apps.scripts.brazilgeo.generate --bounds-only` cria os índices a partir dos
GeoJSONs existentes, sem limpar mapas ou baixar novamente. A geração completa
também os escreve. Execução local: 27 índices, 5.573 feições, 395.363 bytes e
SHA-256 dos 28 GeoJSONs preservado. Validação: três testes do gerador, 18 arquivos
do Rostra, check/build e Chromium (mesma UF sem novo download, outra UF, teclado,
mobile sem overflow ou erros JavaScript). Apenas assets/frontend; sem novos
Parquets ou agregações eleitorais. O comando do gerador e seu modo destrutivo
completo estão documentados em [brazilgeo/README.md](../apps/scripts/brazilgeo/README.md).
Auditoria: [candidature_municipality_jump_2026-10-29.json](audits/candidature_municipality_jump_2026-10-29.json).

Validação dessa apresentação: 18 arquivos de testes Rostra, check e build;
Chromium com BR real e municípios/votos fixture confirmou mapa antes dos votos,
detalhe por zoom, rótulos e troca de turno sem novos downloads, retorno ao Brasil
e mobile sem overflow. Os 27 pontos estaduais foram calculados sobre a malha
nacional real. Falha de geometrias mantém listas/retry. Sem API/ETL nesta etapa.
Relatório: [candidature_progressive_map_2026-10-29.json](audits/candidature_progressive_map_2026-10-29.json).

Validação: 18 testes focados API/pessoas, os 17 arquivos de testes do Rostra,
check e build passaram. Caso real sem mandato: 84 votos em 17 locais, com nomes
históricos e conservação dos totais. Pool 512 MiB/duas partições, caso de uso sem
HTTP: 0,023 s catálogo, 1,010 s resumo, 0,182 s locais. Não extrapolar a amostra
para carga nacional/concorrente. Contratos e limites em
[candidature_votes_map.md](candidature_votes_map.md).

Chromium com API fixture validou abertura sem mandato, votação nacional, três
visões geográficas, paginação/filtros, troca de candidatura/turno, zero/ausência e
catálogo vazio. Perfil com mandato não antecipou consultas do catálogo. Mobile
de 390 px sem overflow nem erros JavaScript. Relatório da amostra real e dessas
verificações em [candidature_performance_2026-10-29.json](audits/candidature_performance_2026-10-29.json).

## Inicialização dos downloads Turi (2026-10-27)

`Downloader.__init__` apenas guarda o provedor `dynamic_sources`. Resolver suas
URLs em `download_from_sources`, depois da consulta ao metadado, e antes de
remover arquivos antigos. Cache válido e retentativa com `failed_sources` não
precisam consultar catálogos remotos. A resolução bem-sucedida é reutilizada na
instância; uma exceção permite nova tentativa sem apagar os arquivos anteriores.

Antes desta correção, importar `pipelines.registry` já consultava os catálogos
TSE (BUs e fotos) e Receita, inclusive com downloads comentados no entrypoint.
O log de início só vinha depois dos imports e o CKAN passava `timeout=None` ao
cliente HTTP. Isso permitia espera silenciosa na inicialização, independentemente
da inclusão de 2026. Agora `download_all.py` configura logging e anuncia o início
antes de importar o registro; consultas CKAN usam timeouts de conexão/leitura
de 15/60 s. A resolução dinâmica também registra qual downloader está consultando.

Validação: 53 testes Turi passaram, incluindo cinco testes novos de inicialização,
cache, retentativa e preservação dos arquivos se a descoberta falhar. O import
do registro real foi validado em subprocesso com chamadas remotas proibidas.
A execução anterior tentou acessar o TSE durante esse import; a sandbox bloqueou
DNS. Não foi reproduzida a espera da sessão do usuário com rede real nem executada
uma carga de downloads. Adicionar um ano não invalida automaticamente metadados
existentes; URLs de candidatos ainda são explícitas no adaptador, sem usar o range.

### Playwright e falhas dos downloads TSE

Na investigação seguinte, `driver_mode="playwright"` e `headless=False` estavam
configurados corretamente para boletins/candidatos, mas o executável Chromium
1234 exigido pelo pacote instalado estava ausente. `uv run playwright install
chromium` instalou a revisão e o driver real abriu uma janela visível. O pacote
Python não instala o navegador automaticamente. Reinstalar a revisão exigida
após atualizar Playwright, sem fixar um executável de outra versão no código.

Falhas devolvidas pelo pool agora são registradas com a URL; o entrypoint verifica
erros de boletins/candidatos e interrompe a execução. Também há logs para cache
e início do navegador. A descoberta CKAN continua via HTTP, antes do Playwright:
`NotFound` de um ano gera aviso; outros erros e lista final vazia interrompem a
descoberta, evitando metadados de sucesso sem downloads.

Validação: 58 testes Turi passaram, incluindo erros do catálogo, falha de abertura
e interrupção do entrypoint. Um smoke com o driver real baixou dois ZIPs locais
com Chromium visível, pool e metadados temporários. Consulta real de boletins de
2022 ao CKAN retornou 112 recursos. Não foi executada uma carga completa do TSE.
Procedimento e limites em [turi_downloads.md](turi_downloads.md).

### Checksum anunciado como boletim de RR/2026

O único retry restante era o link `.zip.sha512` de RR/2º turno de 2026,
incorretamente anunciado no catálogo como CSV. A resposta era `200` e MIME ZIP,
mas o corpo era um checksum de 158 bytes. O adaptador agora normaliza esse
sufixo para o ZIP, deduplica a descoberta e corrige também URLs já persistidas
em `failed_sources`, por meio do `TSEBulletinsDownloader`. Não colocar a regra
de fonte no downloader genérico, nem descartar o recurso e perder a UF/turno.

Recuperação real pelo Playwright: ZIP de 500.520 bytes com SHA-512 conferido;
5.332 linhas/45 colunas integralmente iguais ao CSV, ano 2026, UF RR, turno 2 e
308.597 votos. Os 221 arquivos existentes foram preservados, e o metadado passou
a 222 arquivos, sucesso e nenhuma pendência. Suíte: 60 testes passaram. O retry
continua sendo uma tentativa por URL/execução. Procedimento e relatório em
[turi_downloads.md](turi_downloads.md#link-de-checksum-anunciado-como-boletim).

## Pessoas públicas e órgãos (2026-10-26)

Atualização em 2026-10-29: o cadastro agora inclui também não eleitos e eleições
suplementares, com identidade válida. As restrições de eleição ordinária e
situação diferente de não eleito ficam somente no adaptador do vínculo externo
da Câmara, preservando seus vínculos anteriores. A pesquisa pode filtrar cargo
disputado e pleito sem exigir eleição/mandato; os parágrafos seguintes registram
o estado histórico da ampliação inicial.

O produtor de pessoas públicas deixou de restringir cargos e anos aos deputados
federais/legislaturas da Câmara. Mantém os filtros anteriores de eleição ordinária
(`CD_TIPO_ELEICAO = 2`) e situação diferente de não eleito
(`CD_SIT_TOT_TURNO != 4`), além da necessidade de identidade válida. O perfil
escolhe a candidatura mais recente, com desempates explícitos. O pareamento NLP
da Câmara continua restrito às candidaturas de deputado federal, prioriza data de
nascimento coincidente e deduplica em ordem determinística. Adaptadores de
mandatos, eventos, gabinetes e CEAP filtram identificadores pela fonte da Câmara.

`opendata_organ` substitui `opendata_legislative_house`, e `orgao_id` substitui
`casa_legislativa_id` no ETL, Parquets finais, contratos, SQL, API e Rostra.
Também foram atualizados `coletado_de_orgao_id` e `orgao_nome`. O catálogo contém
`cd`, `sf` e `gov` (`Governo Federal`); rotas em `/opendata/organ` aceitam IDs de
comprimentos diferentes. O vínculo `gov` não cria mandatos presidenciais.
O contrato e a manutenção idempotente estão em
[organ/doc.md](../avoar/core/opendata/organ/doc.md).

Execução local: 10.086 → 423.593 pessoas, preservando todos os IDs anteriores;
nenhuma pessoa elegível ausente ao comparar o bruto por ano/cargo. As fontes
locais cobrem 2018, 2020 e 2022. Índice Venato reconstruído com 423.593 documentos.
Cinco Parquets migrados com comparação completa de valores/ordem/metadados e
Bloom filters. Os relatórios históricos conservam os nomes antigos.

A ordenação determinística revelou um vínculo externo errado por homônimo e
recuperou outro vínculo que a deduplicação descartava. Os dependentes foram
regenerados: 1.812 → 1.815 mandatos (IDs anteriores preservados), com correção de
uma pessoa vinculada, eventos, gabinetes, CEAP e comprovantes. Nenhum conteúdo
anterior de comprovante se perdeu; IDs de comprovantes podem mudar porque o
produtor inclui colunas de joins no hash. A autoria de emendas possui deduplicação
histórica não determinística por emenda: a publicação desta sessão preservou
todos os vínculos conhecidos e acrescentou 58 vínculos dos novos mandatos.
Essa política de preservação na regeneração não corrige o produtor de autoria.
Auditorias em `docs/audits/organ_schema_migration_2026-10-26.json` e
`docs/audits/public_people_organs_2026-10-26.json`.

Reiniciar Fons/Rostra após a migração; IndexedDB passou à versão 2. Redis pode
reter payloads anteriores até o TTL; um namespace novo deve ser compartilhado
pelos dois serviços em publicação coordenada. Não aplicar migrations SQL legadas
nem recriar materialização para esta mudança.

Validação: 36 testes Turi, 70 testes API/infra, 15 arquivos de teste do Rostra,
check sem diagnósticos e build concluído. A suíte API usou o heartbeat de
`asyncio` descrito nesta memória, aplicado pelo runner temporário, porque um
teste de votação sem esse workaround bloqueou no ambiente local. Smoke com
app/core reais e dumps atuais retornou 200 para catálogo, `gov`, legislaturas
vazias de `gov`, pessoa presidencial, mandato corrigido e busca Venato.

## Página Eleições no Rostra (2026-10-28)

`/eleicoes` reúne força partidária e guinada e aparece como “Eleições” na navbar,
substituindo os dois links separados. O topo seleciona pleito e turno; força usa
esse recorte e guinada usa essa base por padrão. A referência alternativa da
guinada é opcional e local, sem mudar a principal. Eleição e turno continuam em
controles separados. Não confundir essa integração com apenas acrescentar o
filtro de turno às telas anteriores.

Somente catálogos no SSR. Cada aba monta seu componente na primeira visita e o
mantém ao alternar; redimensionar o mapa ao reativar, sem recriá-lo ou consultar
novamente. Pausar o carregador municipal oculto. A comparação atualiza a URL
preservando pleito/turno/view e o flag custom_reference; recarregar restaura a
seleção. O formulário principal redefine o contexto e limpa a comparação local.
Os endpoints são os existentes. Rotas anteriores permanecem compatíveis.

Check, testes e build passaram; Chromium confirmou navbar, dois mapas, referência
padrão/opcional, restauração pela URL, alternância sem repetir consultas e layout
320/390 px sem overflow ou erros JS. HTML local 200 em 0,47 s, sem agregação SSR.
Estado e limites em [elections.md](elections.md).

## Mapa da guinada de votos (2026-10-26)

Seletores padronizados em 2026-10-28: eleição primeiro, turno depois, em campos
separados. Na guinada, agrupar por `pleito_id` dentro do cargo/circunscrição;
`eleicao_id` pode mudar entre primeiro e segundo turnos, como no catálogo real
de Presidente/BR em 2018/2022/2026. Não agrupar esses seletores por eleicao_id.
Preservar o número de turno ao trocar de eleição quando existir, usando o
primeiro disponível caso contrário. As URLs/API da guinada conservam os IDs
de turno. Rótulo de eleição compartilhado com a força partidária.

Correção em 2026-10-28: só trocar municípios por locais no zoom 5,5 quando
existir alguma feição local desenhável. Sem locais, manter setas e pontos neutros
municipais em todos os zooms e indicar a ausência do detalhe na legenda do mapa.
Recalcular essa disponibilidade a cada comparação, restaurando o limite municipal
quando houver locais. A comparação real 2022→2026 retornou 5.416 municípios
desenháveis, zero locais e 94.556 grupos sem cadastro; o histórico local disponível
cobre apenas 2018/2020/2022. A troca incondicional escondia todas as setas ao
aproximar. Não preencher coordenadas de 2026 com endereços de anos anteriores.
Chromium confirmou municípios nos zooms 5,49/5,5/8/13/18 e no retorno ao zoom 3;
fixture com local confirmou a transição exclusiva em 5,5. Teste de regressão,
Svelte check e build passaram. Esta correção não regenera o histórico de locais.

Na execução seguinte, ainda em 2026-10-28, foi baixado somente o pacote de locais
de 2026 e regenerado o cadastro pelo script isolado. O histórico passou a incluir
2026; a comparação real 2022→2026 agora retorna 93.227 locais, 85.808 comparáveis
e 85.674 desenháveis. Permanecem 1.329 grupos de votação sem cadastro; seus
1.571.210 votos estão preservados no total nominal. A correção de exibição acima
continua válida para comparações sem locais. Detalhes da carga na seção seguinte
e em `docs/audits/voting_locations_2026-10-28.json`.

`/guinada` compara duas bases do mesmo cargo/circunscrição, com os turnos
escolhidos pelo usuário. Decisão explícita: alinhar por posição, primeiro com
primeiro e segundo com segundo, mesmo que pessoas/partidos mudem. Guinada é a
diferença entre vantagens `(v1 - v2) / total_nominal * 100`; positiva para o
primeiro, negativa para o segundo, zero neutro. Não substituir essa regra por
alinhamento partidário automático.

Revisão de UI em 2026-10-28: legenda “Mais [nome do candidato]”, usando a eleição
comparada e fallback pelo número. O usuário escolhe a seta do primeiro colocado
(↗ vermelha ou ↖ azul); a outra representa automaticamente o segundo. Padrão ↗.
Mapa municipal/local, lotes novos, rankings, busca e detalhes acompanham a escolha.
Atualizar apenas `icon-image` ao inverter: preservar votos, cálculo, câmera,
seleção e dados no worker, sem nova consulta. Preferência dura enquanto a página
estiver aberta e é mantida ao trocar bases. A escolha não implica alinhamento
por partido nem modifica os sinais da guinada.
Validação: arquivo de testes do mapa, Svelte check e build passaram. Chromium
confirmou legenda, cores e detalhes coerentes ao inverter, sem mover câmera ou
repetir a consulta, e layout de 390 px sem overflow nem erros JavaScript.

Posição da legenda (28/10): dentro do mapa, no canto inferior esquerdo, com
20 px de margem lateral e 52 px inferiores (80 px em telas até 540 px para
acomodar a quebra dos créditos). Acima das setas, o cartão identifica a comparação:
“Guinada de votos do Nº turno da eleição de ANO em relação ao Nº turno de ANO”,
usando primeiro a eleição comparada e depois a referência do resultado aplicado.
Alterar seletores sem aplicar não modifica a descrição. O seletor da seta
continua acima do mapa. A legenda não intercepta gestos do mapa.
Svelte check sem diagnósticos; Chromium confirmou posição, separação dos créditos
e ausência de overflow em 1440/390/320 px, mantendo a troca de setas funcional.

Core/query service/controller `vote_shift` montados no core real. Catálogo em
`/opendata/vote_shift/elections`; comparação em `/opendata/vote_shift` por
`reference_round_id`, `round_id` e `office` TSE. Cargo é filtro explícito: os
valores legados de `election.cargo` não correspondem aos códigos TSE e o ID da
eleição sozinho não distingue todos os cargos das candidaturas.

Ranking e votos usam o número nominal do BU dentro da eleição/turno/cargo exatos.
Isso preserva os votos com `candidatura_id` ausente/ambíguo, sem escolher uma
pessoa arbitrariamente. No exemplo local, número 13 de 2018 mantém 31.342.005
votos e aparece como Candidato 13/PT; identidade pessoal segue nula. Consultas
reduzem fatos por BU antes da geografia. Falta de registro de um líder em alguma
seção torna seu total local nulo; zero registrado permanece zero.

Históricos resolvidos pela data/turno e município físico/zona/local do BU;
comparação pelo ID cadastral. Coordenada da base comparada: par IBGE único no
cluster, com fallback para o par TSE. Não misturar eixos/fontes nem usar endereço
antigo para preencher a posição nova. Ausências/ambiguidades preservam votos.

Frontend carrega catálogo no SSR e comparação diretamente do Fons (90 s), sem
persistir o payload nacional em IndexedDB/TanStack. Um resultado atual, uma
consulta por vez; troca aplica por botão e limpa seleção antiga. MapLibre usa
BR leve e feições com apenas ID/guinada no worker. Decisão atual do usuário:
abaixo do zoom 5,5, uma seta por município; a partir de 5,5, setas por local de
votação. Os níveis são exclusivos e a indicação no mapa acompanha a escala.
Essa decisão substitui a apresentação anterior de todos os locais em qualquer
zoom. Não usar círculos numerados. Revisão atual: ocultar setas que se sobrepõem
na tela com `icon-allow-overlap: false` e `icon-ignore-placement: false`, incluindo
colisões entre lotes. `icon-padding: 0` usa a caixa do próprio ícone, com margens
transparentes recortadas para 32×32 (mesmo desenho/tamanho visível). Ordem da
fonte, sem priorizar cor ou intensidade. Aproximar revela mais setas; isso é
seleção visual, sem agregar votos ou deslocar coordenadas. A busca mantém todos
os locais, inclusive os que ocupam a mesma coordenada e não se separam pelo zoom.
Validação da colisão: Chromium com payload real salvo mostrou 215 setas de 5.151
municípios disponíveis e 500 no detalhe de SP. Fixture de quatro pontos em três
lotes: uma seta no zoom 8, três no zoom 18; os dois coincidentes permaneceram
com um ícone. Nenhum erro JS; check sem diagnósticos. Mudança apenas no frontend.
As setas têm traço fino e tamanho fixo em pixels, independente da guinada e do zoom.
`municipios` na resposta traz votos/totais/vantagens/guinada e coordenadas do
cadastro municipal. Agregar cada base completa por município físico do BU antes
do vínculo com o histórico dos locais; incluir locais novos, extintos, sem
coordenadas ou sem cadastro. Não usar média de guinadas nem apenas a interseção
de escolas. Se faltar registro de um líder em alguma seção, preservar nulo no
respectivo total municipal. BU sem município não recebe atribuição arbitrária.
Reutilizar os agregados por local já lidos; não fazer novo scan dos fatos. O clique
municipal mostra seus votos gerais e aproxima o mapa para o nível dos locais.
Os seletores de eleição/turno são independentes, inclusive entre turnos do mesmo ano.
Usar `promoteId: 'id'` para distinguir símbolos de locais próximos. Camadas de
setas recebem no máximo 16.000 feições cada: uma camada nacional única causou
erro real de comprimento dos buffers de opacidade de ícones no MapLibre.
Isso apenas divide o desenho; não agrega, desloca nem remove locais. Fade zero.
Para circunscrição BR, enquadrar o Brasil; coordenadas TSE fora do país não devem
afastar a câmera inicial. Outras circunscrições seguem a extensão dos locais.
Não restringir o mapa com maxBounds do Brasil: isso força zoom mínimo e corta
a malha no viewport móvel alto. Ao sair, destruir mapa/worker e abortar HTTP.

Validação: 76 testes API/infra e 51 frontend, check sem diagnósticos, build e
Chromium com API/dados reais. Amostra nacional 2018→2022, primeiros turnos:
91.295 locais, 86.403 comparáveis e 81.037 desenháveis; consulta direta 3,67 s
e carga de navegador 7,61 s, sem benchmark controlado. Polars conferiu ranking,
totais e todos os cálculos; não houve reauditoria dos CSVs brutos nesta feature.
Reiniciar Fons. Contrato, limites e relatório em
[vote_shift_map.md](vote_shift_map.md).

Evidência histórica, antes da troca por escala: Chromium confirmou 81.031 setas
dentro do enquadramento do Brasil, também no zoom mínimo 1,5, de 81.037 feições
enviadas ao worker. Seis
coordenadas ficam fora desse enquadramento. Formulário 2022 1º→2º turno retornou
85.170 locais desenháveis. Clique/busca, layout móvel e descarte do mapa passaram
sem erros JavaScript. Check sem diagnósticos, teste de seleção/feições/busca e
build passaram; não foi necessário alterar backend ou regenerar dados.

Validação da escala municipal/local: sete testes API/core passaram, incluindo
totais de locais novos/extintos e sem histórico, ausências e paridade dos três
retornos. Arquivo de testes do frontend, check sem diagnósticos e build passaram.
Chromium com API/dumps reais confirmou 5.570 municípios retornados e 5.151
desenháveis em 2018→2022 (primeiros turnos); os restantes preservam ausências.
Totais nominais municipais: 106.855.508 na referência e 117.934.401 na comparada.
No viewport de SP, zoom 5,49 mostrou 1.760 setas municipais e nenhum local;
zoom 5,5 mostrou 26.379 locais e nenhum município. Formulário 2022 1º→2º turno:
5.426 municípios desenháveis e 85.170 locais no detalhe. Clique municipal,
busca local, retorno ao Brasil, mobile e descarte passaram sem erros JS e com
um download da malha por mapa. Reiniciar Fons para obter `municipios` no payload.

## Locais de votação do TSE (2026-10-26)

`downloaders/tse_voting_locations.py` usa o `Downloader` padrão e os mesmos
`TSE_ELECTION_YEARS` dos downloads eleitorais (agora 2018, 2020, 2022 e 2026). Não exige
CSV nacional nem quantidade/nome específico de membros: os arquivos estaduais
também entram no tratamento. Normalizar cada layout antes de concatenar e
deduplicar sobreposições. Excluir `ZZ`, sem filtrar cargos/situação cadastral.

Entidade `LocalVotacao` em `avoar/core/opendata/voting_location/domain.py`.
`opendata_voting_location` tem uma última observação por identidade cadastral
UF/município TSE/zona/número; `opendata_voting_location_history` mantém os registros
por ID/data eleitoral/turno. Não presumir que o ID garante permanência física.
O município IBGE é associado sem descartar locais não resolvidos. Coordenadas
TSE permanecem explícitas em `latitude_tse`/`longitude_tse`, como fallback de
`endereco_cluster_id`. O cluster só é preenchido com correspondência existente
única por município/CEP/número predial; ausência/ambiguidade fica nula.

Valores divergentes entre seções da mesma observação ficam nulos e são listados
em `campos_divergentes`; pares de coordenadas não são misturados. Brutos preservam
os valores originais. `data_geracao` registra o snapshot TSE; os arquivos dos
anos históricos desta carga foram regenerados em 2024, sem garantia de congelar
endereços no ano da eleição. Não trocar o local atual pelos campos de local
original da seção. O catálogo inclui locais que só aparecem em anos antigos.

Carga real: 100.799 locais, 481.339 observações, 27 UFs, sem chaves ausentes/extras
contra os brutos e sem município IBGE ausente. 82.745 observações com cluster;
63.691 sem coordenadas TSE. 1.262 observações divergentes, sendo quatro com
conflitos de localização de dois IDs em 2022. Todos os registros validaram no
core; sessão DataFusion real consultou ambas as tabelas. Bloom filters aplicados
e auditados nos dois novos arquivos. Suíte Turi: 48 testes passaram, 12 novos.

Atualização operacional de 2026-10-28: o cache de 26/10 ainda continha apenas
2018/2020/2022 e era aceito pela validade de quatro semanas, mesmo após incluir
2026 nas fontes. Download incremental via `download_from_sources`, com
`sources_override` limitado ao ZIP de 2026 e `is_retry=True`, preservou os três
brutos anteriores (SHA-256 conferido) e acrescentou 29 arquivos. Metadado final:
32 arquivos, sucesso e nenhuma URL pendente. Não foi alterada a política de cache.
Executado somente `scripts.operations.voting_locations.locations`, sem entrypoints
globais. Os dois cadastros passaram a 108.184 locais e 671.539 observações; 2026
tem 95.100 locais em cada turno, nas 27 UFs. Auditoria por chaves naturais contra
todos os brutos: nenhuma observação ausente/extra; todos os valores do histórico
de 2018/2020/2022 e os IDs anteriores foram preservados. Todos os 779.723 registros
dos dois cadastros validaram no core. Bloom filters reaplicados somente nos dois
arquivos, com auditoria completa de valores. Sessão nova DataFusion confirmou
85.674 locais desenháveis na comparação 2022→2026 e conservação dos votos.
Não foram reiniciados processos existentes nem invalidados caches Redis.
Relatório: [voting_locations_2026-10-28.json](audits/voting_locations_2026-10-28.json).
Reiniciar Fons/DataFusion para descartar metadados dos arquivos anteriores;
respostas Redis anteriores podem persistir até o TTL.

Na preparação inicial, mapa/API/agregação ficaram para etapa posterior, agora
implementada na seção acima. A auditoria inicial dos locais não alterou BUs nem
verificou cobertura dos votos.
Reiniciar sessões da API para registrar as tabelas novas. Comando isolado,
contrato, limites e relatório em
[voting_location/doc.md](../avoar/core/opendata/voting_location/doc.md).

## Fotos de candidatos do TSE

`tse_candidatures_photos` pesquisa os pacotes do grupo `candidatos` no CKAN do TSE
e seleciona recursos chamados "Fotos de candidatos" com MIME `application/zip`.
O portal anuncia esses recursos no formato `JPEG`, embora as URLs baixem ZIPs;
filtrar pelo campo `format=ZIP` perde as fotos. O pacote de 2020 usa o slug
`candidatos-2020-subtemas`, por isso a descoberta pesquisa o grupo em vez de
montar o slug somente pelo ano. A busca é paginada para incluir todas as eleições
disponíveis. Falhas da API devem interromper a descoberta, em vez de produzir
uma lista aparentemente completa.

O `Downloader` com `keep_raw=True` extrai cada ZIP em uma pasta própria dentro de
`downloads/tse/candidatures_photos/`, preserva os caminhos internos e apaga o ZIP
temporário. Não tenta converter as imagens para Parquet. O retorno e o metadado
contêm o caminho da pasta de cada recurso, evitando listar cada foto no JSON;
na renovação, essas pastas são substituídas. `keep_zip=True` guarda somente o
arquivo ZIP; com as duas opções ativas, guarda o ZIP e a pasta extraída. O
downloader de fotos usa apenas `keep_raw=True` neste momento.
O CDN permite HTTP direto; o downloader de fotos usa `httpx` com gravação em
blocos, sem depender do Chromium do Playwright. Na execução local de 2026/AC,
o ZIP de 2,2 MB foi extraído em 389 arquivos. A chamada está ativa no entrypoint
atual e pode transferir centenas de arquivos. O entrypoint agora registra uma
amostra dos erros e falha se qualquer download de fotos falhar; o metadado
sozinho armazena apenas as URLs que falharam.

O script de candidaturas move fotos correspondentes a IDs gerados para
`assets/candidatures/`, associando ano, UF e `SQ_CANDIDATO`. Não incorpora o
sequencial à identidade da candidatura nem altera o schema do parquet.
Chaves ambíguas e fotos ausentes são ignoradas; cada substituição de arquivo
usa `Path.replace` no mesmo filesystem. Veja
[candidature_identity.md](candidature_identity.md).

O entrypoint de dumps contém chamadas ativas e comentadas que podem mudar durante
experimentos. Leia antes de executar: ele pode gerar múltiplos datasets e índices.
Não assuma que roda somente a operação mencionada na tarefa.

## Deduplicação do Turi com hash em disco (2026-10-27)

`infra.diskful_unique.diskful_unique(lf, "coluna", ...)` executa a etapa agora e
devolve `LazyFrame` sobre resultado Parquet temporário. Aceita também `subset`,
os quatro keeps e linha inteira sem argumentos. O índice usa marcadores vazios
SHA-256 por prefixo e `.key` separados com chave original/contadores, tratando
colisões sem descartar linhas diferentes. DataFusion lê batches Arrow; Polars
unique só reduz repetições dentro de batches limitados, não mantém estado global.
Não é um DISTINCT global DataFusion nem dependência nova de banco.

Primeiros produtores migrados: urnas e boletins, sem trocar IDs, formatos nem
ordenação final. Projete colunas necessárias antes da fronteira de execução:
urna precisa só de `NR_URNA_EFETIVADA`. Operações posteriores não podem mais ser
empurradas pelo otimizador para antes da chamada. Não substituir todos os uniques
do projeto automaticamente, especialmente picks first/last após sorts/joins.

`@diskful_unique_session()` envolve o `process_data` que consome os scans e remove
temporários ao retornar. Sem sessão, só o resultado fica retido até exit/cleanup
explícito. Não sair da sessão antes de consumir planos derivados. Diretório em
disco `.turi_unique_tmp` (`TURI_UNIQUE_TEMP_DIRECTORY`), batches de 16.384 linhas
e pool `256MiB` (`TURI_UNIQUE_MEMORY_LIMIT`). Pool não é teto RSS: buffers,
metadados Parquet e operações Polars anteriores usam RAM adicional; cada chave
distinta consome dois arquivos/inodes no índice enquanto a chamada executa.

Evidência progressiva: o plano físico do Polars 1.38 mostrou `in-memory-join`
causado por `validate="m:1"` nos BUs. Agora a validação ocorre só no mapa municipal
pequeno antes do join streaming, preservando rejeição de destinos ambíguos e
tratamento de nulos. Join final tem unicidade provada por unique(id)/group_by(id),
evitando outro fallback de `validate="1:1"`. Não remover validações sem provar
as invariantes. A proteção do benchmark interrompeu os casos que excederam RSS.

Os 74 testes Turi passaram, incluindo 14 novos métodos. Cobrem keeps entre
batches, colisões forçadas, tipos/nanossegundos,
reutilização/limpeza e produtores reais com fixtures. Fontes reais foram medidas
até 19.167.373 linhas por arquivo, com auditoria completa dos valores por
EXCEPT ALL bidirecional contra DataFusion independente. Produtores completos
sobre esse arquivo: urnas 3,856 s/398,9 MiB RSS e boletins 12,225 s/1.733,8 MiB
RSS (picos incluem auditoria; tempos não). As saídas foram temporárias, com
101.072 linhas cada. A carga completa de
222 arquivos/254.350.014 linhas não foi publicada nem executada integralmente.
Não extrapolar o orçamento DataFusion nem tempos de cache quente para teto RSS
ou capacidade de toda a carga. Procedimento, medidas e limites em
[turi_diskful_unique.md](turi_diskful_unique.md); contrato do produtor em
[evm/doc.md](../avoar/core/opendata/evm/doc.md).

## Estouro na carga completa de itens de BU (2026-10-27)

O usuário interrompeu `run_all_scripts` com consumo reportado de aproximadamente
73 GB. A validação anterior de `diskful_unique` cobria urnas/metadados de BUs,
não itens/votos. Os metadados locais confirmaram sucesso de boletins, pessoas e
candidaturas, mas não de itens. Não tratar medições de uma projeção reduzida ou
de um arquivo como evidência de capacidade do pipeline completo.

O produtor de itens concatenava os 222 arquivos, fazia três joins validados
com fallback em memória no Polars 1.38 e terminava em sort global Polars.
Agora inspeciona o schema global sem ler linhas, alinha cada arquivo a esse
schema antes de gerar hashes, materializa/valida somente as dimensões uma vez,
processa uma fonte por vez e grava partes. `validated_lookup` preserva m:1,
inclusive chaves compostas e a exclusão de nulos da validação, antes do join.
O helper eleitoral compartilhado também valida apenas seu mapa pequeno.

Ordenação final DataFusion usa pool 256MiB, spill Zstd em disco e quota 24G.
O primeiro teste completo passou pelas 254.345.786 linhas elegíveis, mas sort
com spill sem compressão falhou na quota de disco. A tentativa foi preservada
no relatório; não aumentar RAM/swap para contornar consumo de disco.
Staging, checks de linhas/votos e troca atômica protegem o dump publicado.
Não deduplicar os itens para reduzir volume: manter multiplicidades dos brutos.

Em 2026-10-28, a supervisão global acrescentada ao `run_all_scripts` foi retirada
por pedido do usuário. O runner executa as operações diretamente, sem teto de
RAM/swap nem mudança automática de threads. Não impor ao pipeline completo um
limite escolhido para benchmarks; as ferramentas de validação explícitas podem
usar seus próprios limites. Orçamentos locais de DataFusion continuam distintos
de um limite global do processo. `DataScript.run` registra início/fim com ID;
os itens registram cada arquivo, contagem de votos e fase de sort.

Piloto real com dois arquivos: 23.535.235 itens/180.121.777 votos, 25,56 s,
pico RSS 3.580 MiB e swap zero, incluindo auditorias por localidade/cargo/tipo
e ordenação. Validação integral posterior com spill Zstd: 222 arquivos,
254.345.786 itens/2.841.719.245 votos, 39.370 grupos conferidos, ordenação global
verificada, 334,836 s, pico RSS 3.931,7 MiB e swap zero. O worker ficou sob
proteção de 4 GiB/512 MiB. Saída temporária de 5.263.748.521 bytes removida ao
terminar; dump publicado e metadados de execução preservados. Os 80 testes Turi
passaram. Não confundir validar integralmente este produtor com executar todos
os demais scripts do entrypoint. Código, limites e procedimento
para validar toda a carga sem publicar em
[turi_bulletin_items.md](turi_bulletin_items.md).

## Bloom filters dos dumps (2026-10-15)

O entrypoint de dumps executa `scripts.maintenance.bloom_final_parquets` após os
produtores e antes dos índices. Desde a reforma de 2026-11-07, restringe a
manutenção às saídas dos scripts efetivamente executados. O módulo isolado
continua descobrindo todos os Parquets finais por padrão, sem alterar os
`sink_parquet`, e usa PyArrow 25.0.1 para reescrever somente arquivos sem
cobertura completa. Pode executar o módulo isoladamente, sem ETL. Não criar banco.

Um row group por vez em temporário no mesmo disco; FPP alvo 5%, NDV igual ao
maior grupo. Inclui folhas aninhadas; BOOLEAN/INT96 são exceções explícitas do
writer. Compara todos os valores em ordem, schema/metadados, limites dos grupos
e cobertura física antes da troca atômica. Reexecução consulta os metadados reais;
`--force` refaz filtros existentes. Relatório incremental, proteção de tamanho
dos grupos e verificação de alteração da fonte. Reinicie sessões da API após a
manutenção; não executar simultaneamente com produtores sobre os mesmos arquivos.
Detalhes, limites de memória/NDV e comando em [parquet_bloom_filters.md](parquet_bloom_filters.md).

Execução isolada concluída: 38 arquivos, 538.197.632 linhas e 52.987 filtros;
16,913 → 18,436 GiB (+9,004%) em 7min07s. Todos passaram pela comparação completa.
Reexecução ignorou os 38 arquivos e não restaram temporários. Suítes Turi/API:
32/52 testes passaram com PyArrow 25.0.1. Relatório em
`docs/audits/parquet_bloom_2026-10-15.json`. Sem benchmark comparativo de API.

## Ordenação física dos dumps (2026-10-14)

Corrigidos 14 scripts/16 datasets sem sort final, com chaves compartilhadas em
`scripts/bricks/parquet_order.py`. Preserve sorts já existentes nos helpers:
pleitos, candidaturas e itens de boletim já ordenavam a saída. Não confundir
ordenação de uma etapa intermediária com a saída após joins/unique/concat.

Os dados finais podem ser reordenados por
`scripts.maintenance.sort_final_parquets`, sem rodar o ETL. A ferramenta usa
DataFusion com memória/partições configuráveis e PyArrow para restaurar o schema,
audita conteúdo e ordenação antes de publicar por troca atômica de cada arquivo.
Não deduplica nem gera IDs. Spill no disco do projeto, fora do tmpfs /tmp.
Schema, linhas, nulos, totais e fingerprints são conferidos; codecs permanecem,
mas tamanho/encodings podem mudar. Ver [parquet_ordering.md](parquet_ordering.md)
e o relatório da execução. Reinicie sessões após a manutenção dos arquivos.

## Padrões de consulta e API

- Pesquisa de empresas (2026-10-25): `business/search` combina razão social e
  nome fantasia dos índices existentes e deduplica por empresa. Permite paginação
  por ID unsigned (padrão) ou relevância original do Tantivy. Por relevância,
  usar o maior score por empresa entre os dois índices, ID crescente como
  desempate e cursor composto `score|ID`, sem offset. Scores dos índices são
  calculados em corpora distintos; o máximo é uma política explícita de fusão.
  `EmpresaPesquisa` declara as opções ordenáveis e retorna score/cursor;
  preservar a ordem do ranking ao hidratar dados via SQL. Estabelecimentos
  fornecem `empresa_id`, não seu próprio `id`.
  Hidratar somente lotes do tamanho da página no DataFusion; referências antigas
  no índice não devem encurtar a página. `/empresas` integra SSR/TanStack/proxy
  e navega para os detalhes existentes. Venato evita materializar uma lista de
  documentos para extrair IDs, mas ainda coleta todos os hits/IDs da expressão:
  não confundir paginação HTTP com custo limitado de busca. Contrato, validação
  e medição local em [business_details.md](business_details.md).
  A ajuda “Saiba mais” abre um dialog com exemplos conferidos no parser Tantivy;
  apresentar expressões sem qualificadores de campo, compatíveis com os dois
  índices. Sintaxe e exemplos documentados no contrato de empresas.

- Empresa detalhada: `/opendata/business/{business_id}` inclui estabelecimentos
  e sociedades com `socio: Socio | Empresa | None`. Resolver pelo `tipo_socio`,
  em lotes, e não expandir recursivamente empresas sócias. Duplicidades de vínculos
  e de dados básicos embutidos são aceitas nesse detalhe. Preservar centavos de
  `capital_social` com Decimal. O detalhe `/opendata/business_establishment/{id}`
  recebe o `fornecedor_id` de fornecedores CNPJ e inclui os dados básicos da
  empresa; mantém `business_id` mesmo se a empresa estiver ausente. Veja
  [business_details.md](business_details.md).

- A paginação padrão do projeto para todas as listagens é **keyset**, usando
  `KeysetPaginationParams` (`limit`, `order`, `pull_by`, `pull_after`), sem OFFSET.
  Declare os campos ordenáveis na própria classe de domínio como
  `sortables: ClassVar[list[str]]`, conforme `PessoaPublica`. Valide a whitelist,
  direção e cursor antes da consulta; valores de filtros devem ser parametrizados.
  Campos não únicos precisam de desempate e cursor composto antes de serem
  oferecidos: apenas ordenar também por ID não evita perdas entre páginas.
- CEAPs por mandato: `GET /opendata/mandates/{mandate_id}/ceap`, com ordenação
  inicial somente por `ReembolsoCeap.sortables = ["id"]`, cursor exclusivo,
  direção `asc`/`desc` e limite entre 1 e 1000. A resposta usa
  `ReembolsoCeapDetalhado`: comprovantes são carregados em lote somente para as
  despesas da página, na mesma transação, preservando a paginação e os caminhos
  rápidos sem Pydantic. Veja [ceap.md](ceap.md).
  A rota declara query parameters explicitamente: nos testes HTTP desta sessão,
  agrupar parâmetros em um `msgspec.Struct` chamado `query` não expôs os campos
  no OpenAPI e não preservou listas de parâmetros repetidos.
- Emendas por mandato: `GET /opendata/mandates/{mandate_id}/amendments` pagina
  emendas por ID e carrega autoria, recursos com itens normalizados, pagamentos
  com fornecedor e convênios em lotes para a página. Filtros repetíveis: ano,
  tipo de autoria do mandato e fornecedor. O vínculo de pagamento permanece
  mesmo se o cadastro de fornecedor estiver ausente. Veja
  [amendment/doc.md](../avoar/core/opendata/amendment/doc.md).
  Para CNPJ, restrinja primeiro os estabelecimentos aos IDs da página e só
  então busque os nomes das empresas correspondentes. O join direto entre as
  duas tabelas grandes teve custo alto. No banco local, mandato
  `15664400621148139699`, 23 emendas e 400 pagamentos, a listagem otimizada
  levou 1,06 s na primeira execução e 0,44–0,45 s aquecida com 12 threads,
  medidos no query service sem HTTP em 2026-09-29. Pelo app real via ASGITransport,
  a mesma rota levou 0,99 s e 0,45 s em duas chamadas consecutivas. Esses valores são evidência
  local, não uma meta garantida para outros mandatos ou máquinas.

- Os GETs de mandato e pessoa usam `JSON_STRING` nas rotas e devolvem uma `Response`
  com `Content-Type: application/json`. Não serializar novamente a string como
  um valor JSON entre aspas. Os query services usam `anyio.to_thread.run_sync`
  e um reader próprio para executar trabalho síncrono do DataFusion.
- `MODEL_PARSED` valida o modelo. `JSON_STRING` e `DICT` contornam Pydantic.
  Em `mandate/details.py`, os agregados são montados em dicionários e codificados
  por `msgspec`. IDs `UBIGINT` viram strings conforme o schema do resultado;
  `Decimal` permanece string no JSON e datas usam ISO 8601.
- Campos opcionais continuam nulos; coleções ausentes continuam `[]`. Ausência de
  registros de votos não significa zero votos. Mandato/pessoa inexistente retorna 404.
- Detalhes do mandato não dependem da presença da pessoa no dataset `public_people`.
- Agregue fatos financeiros separadamente de exercícios, filiações e eventos.
  Relações de autoria repetidas não podem multiplicar os recursos de emendas.
  `EXISTS` é usado para filtrar autoria sem multiplicar valores.
- Para texto, o Venato usa o parser de query por string para aceitar expressões.
  Seus IDs são buscados no DataFusion, onde se aplicam os mesmos filtros da listagem.
- O workaround de `u64` do Tantivy é orientado pelo YAML: campos declarados `u64`
  são armazenados como `i64` por causa do problema observado na API unsigned.
  Na leitura, converter todos os `u64` com `stored=True`, não um único ID fixo.
- O Litestar captura exceções antes do servidor ASGI. O app habilita
  `LoggingConfig(log_exceptions="always")`; não depender somente do logger de
  Granian/Uvicorn para obter o traceback de um 500.

## Como e por que testar

Comandos a partir da raiz, usando o ambiente local existente:

```bash
PYTHONPATH=apps/fons:. uv run python -m unittest discover -s tests -v
PYTHONPATH=apps/turi/src:. POLARS_MAX_THREADS=2 uv run python -m unittest discover -s apps/turi/tests -v
```

`POLARS_MAX_THREADS=2` limita recursos dos testes/ETL local; não é uma configuração
obrigatória da aplicação nem deve ser confundida com partições do DataFusion.

- `tests/test_public_people_details.py`: fixtures produzidas e consultadas em DataFusion, finanças sem
  multiplicação, ausência versus zero, diferentes casas legislativas, equivalência
  dos formatos, rotas 200/404 e montagem real do core com apenas a conexão substituída.
  Há teste bloqueando construção/validação/dump Pydantic nos caminhos rápidos.
- `apps/turi/tests/test_candidature_links.py`: identidade e relacionamentos eleitorais.
- `apps/turi/tests/test_mandate_candidature.py`: associação genérica com contexto
  eleitoral, incluindo ausência e ambiguidade.
- `apps/turi/tests/test_tse_bulletin_schema.py`: layouts antigos, precedência dos
  campos canônicos e descrições desconhecidas.

Priorize invariantes reais, não testes que reproduzem o código. Mudanças apenas
na documentação não precisam disparar cargas grandes ou testes de dados.
Após os testes, use `git diff --check` nos arquivos alterados.

Nos testes assíncronos atuais existe uma tarefa curta de heartbeat para evitar
um travamento observado com Python 3.14/AnyIO no ambiente local. É um workaround
de testes, não uma solução que deve ser transferida automaticamente para a API.

Para importar o app real a partir da raiz, use `PYTHONPATH=apps/fons:.` e
`from apps.fons.main import app`. `from main import app` pode selecionar o `main.py`
da raiz. Confira também o schema OpenAPI gerado pelo app ao adicionar uma rota;
um arquivo exportado em `assets/` não se atualiza necessariamente sozinho.

## Desempenho: o que a regressão ensinou

Estado atual (2026-10-14): Fons/infra usam DataFusion 55 Python, instalado por
`uv`, sobre Parquet direto. Cada pasta é uma tabela. Uma sessão por processo,
readers por operação, parâmetros Arrow preservando uint64, resultados Arrow e
serialização msgspec mantêm os contratos. Somente `MODEL_PARSED` valida modelos.
Transações DuckDB foram removidas: não presumir snapshot entre datasets.
Listagem/pesquisa de pessoas monta coleções em lotes após selecionar a página;
a regra da filiação mais recente foi preservada com SQL compatível.

Recursos usam `DATAFUSION_*`, com memória 1GB, 2 partições e spill até 10G por
runtime. Partições não equivalem a limite de threads. Aquecimento continua
opcional e compartilhado no lifespan. A materialização, o código legado, as
configurações e as dependências Python/Go de DuckDB foram removidos. Fixtures
mutáveis usam DataFusion e snapshots Arrow; ordenação usa DataFusion com spill,
PyArrow e auditoria Polars em batches. Não recriar `.duckdb`. Arquivos de dados
existentes foram preservados. Validação após remoção: 52 testes API/infra e 27 Turi,
com `uv sync --locked --offline` e DuckDB ausente do ambiente.
Registro local anterior de 36 tabelas: 0,064 s; detalhe de mandato: 0,659 s,
sem comparação controlada. Veja [datafusion_resources.md](datafusion_resources.md).

Correção posterior da migração (2026-10-14): `IN (SELECT UNNEST(...))`
podia produzir semi-join após cruzar tabelas grandes, sem filtro no scan Parquet.
Usar `IN (?)` com expansão em placeholders escalares; não interpolar valores.
Coleta de estatísticas e pushdown durante decodificação agora estão habilitados.
Emendas de um mandato restringem recursos por IDs distintos de autoria antes de
cruzar a tabela de emendas. A regressão de memória tem teste com tabela larga
sob pool de 1 MB. Pessoa `849990518947443184` e home retornaram HTTP 200
simultaneamente, com 512 MB e sem Redis. Não aumentar memória como substituto
de analisar os planos. Ver detalhes e limites da medição no documento de recursos.

As medições e implementações DuckDB descritas abaixo são evidência histórica.

Configuração de recursos (2026-10-09): API e staging Turi usam a fábrica
`infra/duck/client.py`, com limites pela env da raiz. Padrões: memória 1GB,
2 threads, spill até 10GB e `preserve_insertion_order=false`. Temporários são
isolados por PID/banco. São escolhas conservadoras sem benchmark de RAM desta
carga; o limite não cobre todo o RSS e cada worker/banco tem orçamento próprio.
Veja [duckdb_resources.md](duckdb_resources.md). Reinicie conexões ao alterar env.

Em 2026-10-13, `connect()` passou a usar views em memória sobre as pastas de
Parquet por padrão (`DUCKDB_BACKEND=parquet`), preservando os nomes consultados
pela infra e a leitura direta existente. `native` mantém o banco materializado;
bancos explícitos e `DuckDBSync` continuam no caminho anterior. Aquecimento
agora inclui views de usuário. Registro local de 36 views: 0,063 s; 9 testes
passaram, incluindo montagem real/HTTP. Sem benchmark comparativo de endpoints.
Não apagar o banco existente automaticamente nem regenerar datasets relacionados
sob consultas ativas: as views não oferecem snapshot nativo do conjunto.

Fons agora cria o core e mantém uma conexão por processo durante o lifespan.
Antes de aceitar requisições, aquece até 32 linhas de cada tabela persistente ou view
(`DUCKDB_WARMUP_ENABLED=true`, `DUCKDB_WARMUP_ROWS_PER_TABLE=32`). Cursores
reutilizam a instância; shutdown/falha fecha a conexão. Provider DI consulta o
state, sem cache permanente entre ciclos. Aquecimento local de 36 tabelas levou
0,550 s; não comprova eliminar custo frio de joins/agregações ou qualquer ID.
Não transferir essa leitura para cada conexão nem para a sincronização Turi.

Compare a mudança isoladamente, com os mesmos dados, ID, conexão/configuração e
máquina. Registre threads (`SELECT current_setting('threads')`), memória, cache
frio/quente e se o tempo inclui HTTP. Aqueça o banco, alterne versões e use várias
medições; latência de uma consulta não demonstra capacidade sob concorrência.

Na sessão de 2026-09-23, uma SQL única com muitas subconsultas correlacionadas
substituiu consultas menores para eliminar o parsing Pydantic. Isso regrediu com
a configuração padrão da API. A mediana local após aquecimento, no mesmo mandato
`12687308247382280863` e com 12 threads DuckDB, foi:

| Implementação | Mediana histórica |
|---|---:|
| Consultas menores + Pydantic | 126 ms |
| SQL correlacionada + JSON DuckDB | 212 ms |
| Consultas menores + msgspec, sem Pydantic | 89 ms |

São medidas de consulta/serialização, não HTTP nem garantia atual. Com dois
threads a comparação tinha outro comportamento; isso invalidou a extrapolação
inicial para a API. A implementação mantida foi a terceira. Pré-agregar votos
ou cachear respostas são possibilidades discutidas, não features já implementadas.

## Regenerar dados com recursos limitados

Procedimento usado na correção de 2018; os scripts auxiliares foram temporários,
não constituem um comando de produção versionado. Não depender de arquivos em
`/tmp` de sessões anteriores. A geração em lotes foi executada separadamente;
verifique se uma operação normal já oferece esse modo antes de presumir suporte.

1. Confira quais dados brutos existem, por ano/layout, e as dependências do dataset.
   Reutilize downloads existentes; não baixe nem regenere tudo por padrão.
2. Gere os resultados em um diretório separado. Para eleições, projete somente
   os metadados necessários e deduplique antes dos joins. Normalize cada arquivo
   antes de concatenar layouts históricos.
3. Para BUs, processe arquivo a arquivo; use partes para boletins e lotes limitados
   para itens. Na execução anterior foram usados lotes de 500.000 linhas e
   `PyArrow.ParquetWriter`, evitando acumular os itens de todos os anos em RAM.
   Streaming não elimina o custo de operações bloqueantes como sort/unique/join;
   preserve a deduplicação global e a identidade ao dividir o processamento.
4. Gere na ordem das dependências: eleições/turnos → candidaturas → itens → mandatos.
   Boletins físicos também precisam ser coerentes com os itens. Pessoas,
   identificadores, municípios e legislaturas devem estar disponíveis conforme
   a operação. Consulte os documentos de identidade antes de mudar um ID.
5. Audite os parquets novos usando DataFusion/Arrow e limites explícitos de memória
   e partições adequados à máquina, com espaço de spill e espaço livre suficiente.
6. A API DataFusion consulta os dumps diretamente: não exige sincronizar um banco.
7. Publique um conjunto coerente após validar e coordene consultas durante a troca.
   `os.replace` de um arquivo não torna atômico o conjunto de Parquets.
8. Depois, abra uma sessão nova e confira as tabelas publicadas e uma resposta real.
   Reinicie a API após mudar schemas ou incluir pastas. Remova só temporários desta
   tarefa após concluir a verificação, preservando auditorias úteis fora do diretório
   temporário.

Na correção histórica, hardlinks dos parquets antigos permitiram manter uma cópia
para recuperação sem duplicar os dados no mesmo filesystem. Isso exige que os
arquivos antigos não sejam modificados em lugar; novos arquivos substituem os
anteriores. Não reutilizar essa técnica sem conferir as condições.

## Auditorias de cobertura e integridade

Verifique tanto os produtores quanto os consumidores:

- Contagem de linhas e soma de votos dos itens versus entradas brutas, explicando
  filtros intencionais. Quebre por ano, tipo de voto, cargo e localidade.
- Duplicidade de IDs; referências a eleição, turno, boletim e candidatura;
  coerência de eleição/localidade/cargo/número entre os relacionados.
- `candidatura_id` preenchido somente quando há correspondência nominal única.
  Conte ausências e ambiguidades separadamente; ambas podem ser legitimamente nulas.
- Cobertura dos mandatos por legislatura/casa, preservação dos IDs e correspondência
  da pessoa da candidatura. Teste retorno de mandatos antigos e recentes da mesma pessoa.

A auditoria histórica após recuperar o layout de 2018 encontrou 184.398.705 itens,
sem referências quebradas nos relacionamentos verificados. Havia 591/592 vínculos
na 56ª legislatura e 601/601 na 57ª. Candidaturas de 2014 e anteriores não estavam
nos arquivos locais. Esses números são evidência de uma carga passada, não
asserts permanentes: novos downloads podem mudar contagens e cobertura.

## Decisões de domínio para não perder

### Rostra/Fons: votos municipais da candidatura (2026-10-23)

`GET /opendata/candidature/{id}/votes/municipalities` retorna votos nominais
por município físico do boletim, separados por turno. Filtrar por ID exato da
candidatura/eleição antes do join; nunca atribuir por número/nome/partido. Turnos
sem registros têm total null; zero explícito é preservado; votos sem município
entram no total e em `votos_sem_municipio`. DICT/JSON_STRING sem Pydantic.

Em Mandato → Histórico → Candidatura, carregar somente a UF da circunscrição
(inclusive resolução de código municipal para UF), ao abrir a aba. BR não
determina UF; não adivinhar. O mapa usa números abreviados no interior dos
polígonos (`5.2K`) e lista lateral com valores exatos, sem escala de cor por votos.
Trocar turno reutiliza a fonte. Rótulos usam expressão por código IBGE sobre o
GeoJSON no worker; não converter malhas estaduais grandes em objetos na página.
MapLibre 6 rasteriza fontes locais quando não há glyphs URL. Contrato e evidências
em [candidature_votes_map.md](candidature_votes_map.md). Sem ETL; reiniciar Fons.

### Rostra: mapa de força partidária (2026-10-22)

`/partidos` adiciona filtro múltiplo de pleitos, cores por sigla e legenda de
votos. O novo catálogo `/opendata/pleito` usa keyset numérico por ID e preserva
uint64 como string; o frontend percorre todas as páginas. Os mesmos pleitos
entram na URL/chave de cache e nas consultas estaduais/municipais. Não misturar
dados de um recorte anterior durante a navegação.

MapLibre desenha BR leve e, a partir do zoom 5,5, estados próximos ao centro que
intersectem o viewport. O seletor “Estados detalhados” permite de 1 a 27 UFs,
com padrão de dois; conta arquivos estaduais com todos os municípios, não feições
individuais. Reduzir o limite remove fontes excedentes imediatamente.
Contornos estaduais usam uma única borda branca, mais espessa que a municipal,
sem halo ou traço escuro, acima dos detalhes municipais.
Insira novas camadas municipais antes de `country-line` para preservar
essa ordem durante o carregamento progressivo. Reutilize a fonte nacional.
Um job por vez; geometrias chegam ao worker
por URL do Fons, fora do proxy JSON e do cache IndexedDB/TanStack. Remova fontes
fora do viewport e preserve geometria ao mudar filtros, atualizando só feature
state/votos. Aguarde consultas de votos obsoletas antes de iniciar outra, pois
cancelar HTTP não cancela a agregação no servidor. O worker do MapLibre precisa
ser importado com ?url e configurado explicitamente no Vite.

Cor padrão indica o partido mais votado, empate/ausência/partido não resolvido
são neutros. Clicar na legenda mostra a participação local de uma sigla. Não
transformar votos por vários cargos e turnos em contagem de eleitores únicos.
A paleta de apresentação fica em `PartyStrength/model.ts`: PL azul `#0068B5`,
PT vermelho `#ED1C24` e outras siglas conhecidas; o hash/HSL anterior continua
para as demais. Normalize caixa/acentos somente na busca da paleta, preservando
siglas e agrupamentos históricos nos dados.
Contrato, limites dos arquivos estaduais grandes e validação em
[party_strength_map.md](party_strength_map.md).

### Carregamento inicial da força partidária (2026-10-28)

Filtro de turno acrescentado posteriormente no mesmo dia: `numero_turno=1|2`
opcional nos endpoints estadual/municipal. Omitido, continua somando todos.
Resolver IDs em `opendata_election_round` antes da consulta grande e aplicar
IN escalar de `turno_eleicao_id` no scan, reduzindo também as eleições
participantes. Não juntar a dimensão de turnos aos fatos. UI escolhe eleições
e turno separadamente; manter `numero_turno` na URL, cache, query key e nos
detalhes municipais. Trocar turno atualiza votos sem refazer geometrias residentes.
Testes verificam separação/soma dos turnos, paridade estadual/municipal, ausência,
validação HTTP/OpenAPI e os três retornos. Sem regeneração; reiniciar Fons.
Validação: dez testes API/core, suíte de 16 arquivos do Rostra, check e build
passaram. Chromium confirmou agrupamento pelo pleito real, seleção separada,
preservação/fallback de turno e propagação aos dois níveis do mapa. Manter
geometrias residentes enquanto a nova consulta nacional está pendente; pausar
o pump municipal em vez de esvaziar o viewport desejado. A troca 2º → 1º turno
não repetiu downloads geométricos de SP/PR. Sem erros JS/overflow em 320/390 px.

O loader de `/partidos` agora busca somente o catálogo e votos já presentes no
cache local; não inicia agregação nacional no SSR/preload. A consulta começa no
navegador e o mapa nacional é montado independentemente. Não apresentar totais
zero antes dos dados; detalhes municipais aguardam a resposta nacional.

Força partidária usa prazo de 90 s no navegador e no proxy do Rostra, por política
compartilhada de endpoint; demais consultas mantêm 15 s. Desativar retentativas
automáticas, refetch em foco e reconexão para a consulta nacional, mantendo botão
manual. Cancelar HTTP não cancela o worker DataFusion e repetir pode sobrepor
agregações. Antes, timeout no SSR seguido de consultas/retries na hidratação
impedia a montagem do mapa enquanto o servidor continuava trabalhando.

Reprodução: catálogo em 0,24 s, HTML anterior em 15,01 s sem mapa; perfil isolado
com 254.345.786 itens agregou em 28,59 s, pool 512 MB/duas partições e RSS máximo
1.137 MiB. Essa primeira medição tinha limites externos e não alterou `.env` ou
SQL. O ajuste inicial da tela não corrigia o custo da agregação; diagnóstico e
correção da SQL na seção seguinte. Fluxo em [party_strength_map.md](party_strength_map.md).

Svelte check, 16 arquivos de testes e build passaram. Chromium com resposta
simulada de 20 s confirmou mapa antes dos votos, uma requisição nacional,
cores ao concluir, falha sem retry automático e tentativa manual; sem erros JS
ou overflow móvel. HTML local após a correção: 0,86 s, sem agregação no SSR.

### Força partidária: ordenação inferida e regressão da SQL (2026-10-28)

Regenerar os itens pelo gravador externo PyArrow passou a declarar
`sorting_columns=(tipo, quantidade, boletim_id)`. O writer Polars anterior não
declarava essa ordem no footer. O arquivo também passou de 481 para 3.882 row
groups; linhas aumentaram de 184.398.705 para 254.345.786. A SQL inalterada passou
a usar agregação parcialmente ordenada por `tipo`, preservando ordem ao
redistribuir centenas de milhões de fatos. Mesma SQL/mesmos bytes: 23,616 s com
ordenação inferida e 15,361 s com inferência removida apenas no provider de teste.

A SQL atual usa somas filtradas para votos nominais e de legenda, sem `tipo` no
GROUP BY. Não remover ordenação física ou metadados dos arquivos para corrigir
este endpoint. Resolver partido separadamente para cada tipo e tratar SUM nulo
como tipo ausente, preservando zero explícito. A fixture com Parquet ordenado
detecta o plano anterior e cobre as duas regras de contagem.

Comparação integral: país 27,579 → 16,435 s e SP/2022 municipal 6,144 → 3,299 s,
com todos os registros idênticos. Sem 2026, os totais reproduzem a auditoria
antiga, mas levaram 12,686 s: não atribuir todo o custo restante a volume nem
declarar restaurada a latência histórica de 6,618 s. Layout/codec não foram
isolados. Nove testes passaram. Pool 512 MB/duas partições, execução sequencial
protegida; RSS máximo acumulado 1.110,9 MiB. Detalhes e relatório em
[political_parties.md](political_parties.md#regressão-após-regenerar-os-boletins-2026-10-28).
Reiniciar Fons; sem regeneração dos Parquets.

### Força partidária por UF/município e memória (2026-10-22)

`/opendata/political_party/strength` e `/strength/{uf}` somam votos nominais e
de legenda, com `pleito_id` repetível/opcional. Por decisão explícita do usuário,
somam todos os cargos e turnos. A geografia é a física do boletim; preserve
siglas históricas e um grupo null para partido não resolvido. A soma municipal
de cada partido deve reproduzir seu total estadual. Contrato em
[political_parties.md](political_parties.md).

O usuário reportou travamento do SO por consumo de RAM durante a validação real,
com swapfile desligada. Após reinício, a swap estava ativa; o .env continuava com
pool DataFusion de 12GB e seis partições para 14 GiB de RAM. Esse orçamento não
limita todo o RSS. Não repetir validações grandes sem orçamento temporário baixo
e proteção externa do subprocesso; não tratar swap como correção da consulta.

A primeira SQL de força podia construir hashes com os fatos de 184 milhões de
linhas. A versão atual separa dimensões/partidos, usa apenas boletim como entrada
pequena do join principal e aplica filtros de IDs no scan. Outro ponto de alto
consumo era COUNT(DISTINCT sigla) em centenas de milhares de grupos de candidatura:
MIN/MAX detecta siglas conflitantes com o mesmo resultado e menor alocação.
As listas de IDs na consulta das candidaturas são arrays UNNEST tipados, sobre
uma dimensão pequena. Na consulta dos votos, preservar IN escalar para não
reintroduzir semi-joins posteriores à junção dos fatos.

Fixtures cobrem montagem real da API, dados históricos/ambíguos, ausência versus
zero e formatos rápidos. Regressões com pool pequeno abrangem tanto volume de
votos quanto cardinalidade de candidaturas. Medições reais com pool de 512 MB,
duas partições e monitor externo em
[party_strength_2026-10-22.json](audits/party_strength_2026-10-22.json).
Os três GETs reais sequenciais passaram, inclusive país sem filtro, com pico
acumulado de 884,8 MiB. SP detalhado reproduziu os totais estaduais por partido.
Oito testes de força/catálogo passaram; não houve teste de capacidade concorrente.

- Não usar `SQ_CANDIDATO` como identificador estável. A identidade compartilhada
  inclui eleição, localidade, cargo TSE e número; consulte o documento específico
  para ambiguidade e discriminador de pessoa. Nomes/tipos/ordem/seed e versão do
  Polars importam para reproduzir o hash.
- `turno_eleicao_id` pertence ao item de BU, pois um boletim físico pode conter
  várias eleições. `codigo_local` usa BR/UF/IBGE conforme a circunscrição; converter
  município TSE pelo mapa adequado, sem descartar por isso votos nacionais/estaduais.
- Não reintroduzir `situacao_vinculo_candidatura`: o usuário pediu sua remoção.
  `candidatura` nula comunica ausência de correspondência na resposta.
- Não escolher candidatura ambígua pelo maior número de votos nem pela posse mais
  recente. Contexto eleitoral vem do adaptador da fonte; data de exercício de um
  suplente não determina o ano eleitoral de origem.
- O enum de tipo de eleição do ETL e o do domínio têm numerações diferentes no
  código observado. Não trocar um pelo outro sem migrar produtores e dados juntos.
- Fornecedor é polimórfico: CNPJ referencia estabelecimento; os demais casos
  referenciam `opendata_services_supplier`. Para contagens, preserve o par de tipo
  de documento e ID; não consolidar filiais implicitamente.
- Endereços possuem `id` e `cluster_id` diferentes. O vínculo de endereço do
  estabelecimento usa o cluster; não tratá-lo como FK para um endereço único.

Detalhes das regras ficam nos documentos do domínio apontados pelo `AGENTS.md`.
Ao atualizar esta memória, não registrar segredos, conteúdo de `.env` nem depender
de paths temporários ou de contagens históricas como configuração permanente.

### CEAP: filtro de comprovantes

`ComprovanteReembolsoCeap.fonte` é a URL bruta do comprovante. No adaptador da
Câmara, preserve `urlDocumento` nesse campo; não grave a sigla `cd`.

Em expressões Polars, coloque comparações entre parênteses ao combiná-las com
`&`/`|`. O filtro de URLs de comprovantes descartava comprimentos pares por
precedência de operadores. A auditoria de 2026-09-27 comparou URLs brutas e
vínculos, além de integridade referencial; veja `docs/ceap.md` para evidência e
estado da publicação local. Hashes sobre `pl.all()` após joins também podem
mudar quando o schema relacionado muda, mesmo com a mesma despesa de origem.

### Estatísticas gerais para o frontend

`GET /opendata/rude_insights` reúne emendas pagas (`valor_pago + rap_pago`), reembolsos
CEAP (`valor_liquido`), contagens e top 10 por pessoa. `start_year`/`end_year`
são opcionais e inclusivos: ano orçamentário da emenda e ano de emissão CEAP.
Deduplicar autoria por emenda/pessoa antes de atribuir o valor, somando mandatos
da mesma pessoa. Totais gerais preservam fatos sem autoria/mandato resolvido;
rankings podem ter nome nulo. Autoria compartilhada recebe valor integral,
sem rateio. Veja [rude_insights.md](rude_insights.md) para contrato e evidência.

Os rankings incluem `mandatos` com os campos básicos do mandato e `candidatura`
básica aninhada (nullable), carregados em lotes somente para o top 10. Listar
os mandatos que contribuíram no intervalo de cada ranking, preservando a
agregação por pessoa. Usar os IDs para links de detalhes e fotos publicadas;
não carregar votação de BUs para montar cartões do ranking.

O modelo de domínio `RudeInsights` fica em `core/opendata/rude_insights/domain.py`.
Os filtros `start_year`/`end_year` são somente entradas da querystring, sem eco
no payload ou campos no schema de resposta.

### Rostra: esboço da homepage

Em 2026-10-03, a homepage SvelteKit usa `TemplatePortalScreen` (navbar, conteúdo
por `Snippet` e footer) e `Homepage`, cada um em sua pasta com `style.scss`
importado no componente. Subcomponentes ficam em `components/`; a rota
`+page.svelte` compõe a tela e declara os metadados. Sass é processado pelo Vite.
A interface usa runes Svelte 5 e não depende de fontes ou imagens externas.

O esboço contém panorama financeiro, filtro anual, alternância emendas/CEAP e
expansão do ranking, navegação mobile e seções de exploração/projeto. Dados de
ranking em `Homepage/demo.ts` são fictícios e explicitamente sinalizados. O
filtro valida e atualiza o período selecionado, mas não altera os exemplos nem
consulta a API. A integração futura deve usar `/opendata/rude_insights`, manter
valores decimais/IDs sem perda de precisão e aproveitar mandatos/candidaturas
para fotos e links. Os destinos de exploração ainda são apresentados como
"Em breve". `npm run check` e `npm run build` passaram no diretório do Rostra.

### Rostra: integração Fons (estado atual)

A integração substitui o estado demonstrativo descrito acima. `+page.server.ts`
consulta os insights pelo cliente `$lib/server/fons.ts`, com `FONS_URL` privada
(padrão `http://127.0.0.1:8000`) e timeout. Filtros GET vão à URL; navegação
SvelteKit reaplica a consulta e mostra carregamento. Anos inválidos, ausência
e indisponibilidade têm estados próprios; não há fallback para fixtures.

O contrato TypeScript fica em `lib/api/insights.ts`, alinhado ao JSON do core.
Monetários usam centavos BigInt; IDs permanecem strings. Fotos e links dos
mandatos/pessoas passam por um proxy restrito; links abrem o JSON do Fons até
existirem telas de detalhe. Partido/localidade referem-se à candidatura.
Veja [rostra_homepage.md](rostra_homepage.md) para configuração e verificações.

### Rostra: organização de portal

Desde 2026-10-15, `routes/+error.svelte` trata erros de página com o template
completo do portal e `components/ErrorPage`. Há mensagens distintas para 404 e
indisponibilidade 5xx (incluindo 502), além de fallback para outros status.
Preservar os status HTTP reais, o título com o código e `robots=noindex`; não
exibir mensagens internas de exceção. Retry é um link com
`data-sveltekit-reload`, mantendo pathname e query string para repetir o loader
mesmo sem JavaScript. Links para início, parlamentares, municípios e sobre
oferecem caminhos alternativos. Ilustração em CSS reutiliza os `PortalIcon`
existentes; não trocar o logotipo. Validado em Chromium desktop/mobile: 404/502,
ausência de overflow e retry que recupera a página após a API voltar, mantendo
os filtros e sem erros JavaScript. Check e build passaram.

Desde 2026-10-15, a navbar usa apenas `assets/files/icon-avoar.svg`, sem wordmark
ou legenda. Preserve esse logotipo oficial. Os desenhos de `PortalIcon` foram
extraídos sem alterações para `assets/files/portal-icons/`; o componente referencia
os SVGs como máscaras para herdar a cor. `$assets` aponta para os assets da raiz;
`?no-inline` mantém arquivos separados no build. Não substituir os desenhos pelos
outros ícones legados de `assets/files`. Veja [rostra_homepage.md](rostra_homepage.md).

A homepage usa menu lateral fixo, cabeçalho compacto, indicadores e cards de
ranking (primeiro resultado destacado), preservando a integração Fons. Busca
local filtra apenas os top 10 por nome/partido/localidade, sem acentos e sem
alterar posições originais. A metodologia é recolhível; destinos futuros ficam
sinalizados no menu. No mobile, menu superior e cards empilhados. A estrutura
substitui o hero e os blocos promocionais do esboço inicial.

No card destacado do ranking, preservar o indicador de posição no canto superior
direito e o bloco de identidade centralizado ao lado da foto. Os overrides antigos
de `left` no indicador e de padding superior na identidade foram removidos.

Os rankings municipais (votos e autores de emendas) e de recebimentos de empresas
seguem o agrupamento da homepage: nome, número do candidato e logo do partido.
`CandidateName` compartilha essa apresentação, com logo 20 × 15. Votos municipais
expõem `numero_candidato` da candidatura votada. Autores financeiros recebem
`candidatura_recente`, resolvida em lote após o top 10 pelo helper também usado
nas empresas; não trocar a candidatura votada pela mais recente. Sem candidatura,
preservar o nome e o lugar no ranking. Sem ETL; reiniciar Fons para os campos novos.
Ver [municipalities.md](municipalities.md) e [business_details.md](business_details.md).

### Rostra: acesso direto e TanStack Query (substitui o proxy)

Por decisão do usuário, removeram-se o proxy e a consulta SSR dos insights.
O navegador acessa o Fons usando `PUBLIC_FONS_URL` e TanStack Svelte Query 6.
O layout fornece QueryClientProvider; createQuery recebe callback reativo.
Queries são desabilitadas no servidor. Cache por intervalo com staleTime de
5 minutos e gcTime de 30 minutos; cancelamento, retries e refetch gerenciados
pela biblioteca. Fotos e links também apontam diretamente ao Fons.

O Fons usa `FONS_CORS_ALLOWED_ORIGINS` (lista separada por vírgula), com origens
locais 5173 por padrão, GET/HEAD/OPTIONS e sem credenciais. Configurar no ambiente
ou .env da raiz e reiniciar o Fons. O exemplo em apps/fons/.env.example não é
carregado automaticamente. A documentação atual está em rostra_homepage.md.

O resumo do período agrupa emendas e CEAP em duas subseções, cada uma com total,
contagens secundárias e nota do recorte. Contagens não têm cards próprios. Mantém
o filtro e o cache existentes, com grupos lado a lado e empilhados no mobile.

A base do Rostra usa branco levemente quente (#F7F7F5), com gradiente neutro
sem halos azuis (ajuste de 2026-10-08). Mantém texto marinho, destaques azuis e superfícies
leves de glassmorphism. Amarelo/preto identificam controles e seleção.
O mixin Sass compartilhado de superfícies tem fallback sólido via @supports.

`RudeInsights.ceap` inclui `quantidade_comprovantes`, contando registros de provas
por EXISTS nas despesas filtradas, sem multiplicar fatos financeiros. Inclui
despesas sem mandato resolvido e exclui provas órfãs. A homepage exibe a contagem
ao lado dos reembolsos. URLs repetidas continuam provas distintas; não confundir
com quantidade de despesas com comprovantes ou de URLs únicas.

### Pleito: evento geral compartilhado por localidades

Por decisão do usuário, `Pleito` representa um evento geral, não um registro por
município. O core define `id`, `ano`, `tipo` e `data_inicio`; `Eleicao` ganha
`pleito_id` obrigatório e mantém sua circunscrição. O script `elections` gera
`opendata_pleito` junto com eleições/turnos. Os IDs antigos não mudam: a adição
não requer regenerar candidaturas ou boletins. É preciso regenerar as eleições
e reiniciar a sessão DataFusion para registrar a coluna e a nova tabela.

A identidade do evento usa ano/tipo/data do primeiro turno. O código TSE de
pleito pode mudar por turno e não serve sozinho como identidade do evento.
Suplementares são agrupados por data, com associação dos segundos turnos pelo
primeiro turno anterior da localidade; os limites dessa convenção estão em
[pleito.md](pleito.md). O tipo novo segue o enum do core (1/2); o tipo histórico
nas eleições continua 0/1. Testes cobrem a geração dos três parquets isolados;
os dados completos não foram regenerados nesta alteração.

### Rostra: página sobre o Avoar

A rota `/sobre` retoma o formato de landing page para apresentar o projeto,
componente `About` e Sass próprio dentro do template do portal. Conteúdo estático
SSR, sem chamadas ao Fons; mantém a paleta azul e controles amarelos. Menu e
rodapé passam a apontar para a nova rota; links do painel incluem `/` e o estado
ativo considera também o pathname. A metodologia permanece em `/#sobre`.
Detalhes em [rostra_homepage.md](rostra_homepage.md).

### Rostra: tecnicidade

`/tecnicidade` é a página informativa técnica, estática SSR dentro do template
do portal, com fluxo HTML/CSS, etapas expansíveis nativas, verificações e exemplo
de identidade eleitoral. Descreve a arquitetura atual e distingue testes e
procedimentos de auditoria de um relatório de aprovação automática da carga.
Não executar ETL para validar essa página. Conteúdo e organização documentados
em [rostra_homepage.md](rostra_homepage.md).

### Rostra: detalhes de pessoas e mandatos (2026-10-07)

Em 2026-10-15, `PartyLabel` passou a exibir logos nas candidaturas, mandatos e
filiações, incluindo busca e rankings. Descobre SVGs do submodule
`assets/files/partidos-brasil-svg/partidos` pelo glob de build; sempre prioriza
`_typo.svg`, com fallback ao logo completo. Ausência de asset/falha da imagem
mostra a sigla. Não mapear partidos históricos aos
sucessores. Inicializar o submodule antes do build; detalhes e aliases explícitos
em [rostra_details.md](rostra_details.md).

O cadastro TSE `opendata_political_party` agora tem endpoint
`GET /opendata/political_party/`, com `nome`, `sigla`, `notas` e keyset por sigla.
Core monta query service DataFusion/caso de uso; JSON/DICT sem Pydantic. Nas
filiações do histórico e da busca, Rostra mostra logo e nome do cadastro, ou
sigla quando ausente. SSR carrega catálogo opcional; TanStack compartilha cache
de cinco minutos. Falha do catálogo não impede a página. As outras aparições
mantêm logos sem texto conforme ajuste do usuário. Sem ETL; reiniciar Fons para
registrar a rota. Ver [political_parties.md](political_parties.md).

Rotas `/pessoas/[id]` e `/mandatos/[id]`, conectadas aos rankings. Estatísticas
e mandatos ficam na pessoa; registros CEAP/emendas são explorados no mandato,
com páginas keyset de 10, scroll incremental e opção de recolher. As consultas
cronológicas usam desempate por ID e cursores compostos; não usar o hash como
indicador de recência. O modo anterior por ID continua disponível.

O detalhe da pessoa acrescenta candidatura recente independente de mandato.
A casa já tem endpoint de listagem; foi acrescentada a rota de legislaturas
por casa, sem limitar IDs dessa rota a duas letras. Nenhuma mudança de ETL ou
regeneração é necessária. Reiniciar o Fons para usar os contratos novos.

`lib/styles/global.scss` concentra tokens e convenções visuais; fontes do Rostra
usam rem. Detalhes, limitações de agregação e validação estão em
[rostra_details.md](rostra_details.md).

As listas unitárias do mandato usam altura limitada (44rem ou 75svh) e scroll
interno no componente Records, com separador discreto. O observer usa essa área
como root e carrega páginas automaticamente, sem controles de expandir, recolher
ou carregar mais. Sem IntersectionObserver, usa evento de scroll. O loader fica
no fim da lista; erros mantêm tentativa explícita, evitando ciclos de erro.

### Legibilidade do markup

O AGENTS.md registra a preferência obrigatória de HTML/Svelte: elementos de
blocos visuais diferentes em linhas separadas e indentação por hierarquia.
Tags inline do mesmo texto/fluxo podem compartilhar a linha. Diretivas Svelte
e seus fechamentos ficam em linhas próprias. A revisão de markup do Rostra
preserva os textos existentes e não altera as consultas ou regras de domínio.

## Cache Fons/Rostra e SSR (2026-10-07)

### Cache de navegação em IndexedDB (2026-10-15)

Rostra agora persiste respostas JSON públicas no IndexedDB (`avoar-responses`,
store `responses`, versão 1), com memória por aba. Os loaders de homepage,
pessoa, mandato, empresa, busca parlamentar e municípios passaram de
`+page.server.ts` para `+page.ts`: SSR usa o proxy existente e mantém Redis/Fons;
navegação interna reutiliza respostas locais com menos de cinco minutos.
Persistir somente o QueryClient não evitaria os requests dos loaders no retorno
empresa → parlamentar. Por isso, o cache fica no transporte compartilhado com
os loaders; não é uma serialização completa do estado do QueryClient.

Hidratação consome as respostas SSR antes de habilitar leituras locais via
`afterNavigate`; SSR novo prevalece sobre cópias antigas. Leituras não renovam
timestamps, e `initialDataUpdatedAt` usa a resposta mais antiga do loader.
`fetchFons` sempre consulta a API nas atualizações do TanStack, inclusive no
Aplicar do mesmo período, e grava as respostas novas no cache. Primeiras páginas
são reutilizadas pelos loaders; o estado de paginação infinita continua em memória.

Chaves incluem caminho normalizado e query string completa, ordenada por nome
sem reordenar valores repetidos. Não converter IDs/dinheiro para Number. Somente
respostas HTTP bem-sucedidas com JSON válido são gravadas. Limite de 200 entradas
ou aproximadamente 10 MiB em UTF-16, com descarte das mais antigas e retenção
máxima de 24 horas; limpeza no próximo write. IndexedDB ausente, bloqueado,
corrompido ou com quota esgotada degrada para memória/API, com timeout de operações.
Incrementar a versão de `browser-cache.ts` ao mudar contratos incompatíveis.

A resolução pública de CNPJ (`business/resolve`) foi incluída na allowlist exata
do proxy para manter os redirects também nas navegações universais. Credenciais,
Redis e Fons privados continuam em módulos server-only. Sem ETL.

Testes de cache usam `fake-indexeddb` apenas em desenvolvimento: persistência,
idade original, isolamento de filtros/cursores, corrupção, indisponibilidade e
limites de entradas/espaço. Contrato detalhado em [redis_cache.md](redis_cache.md).

Validação: check sem diagnósticos, suíte do Rostra e build passaram. Smoke em
Chromium com API fixture confirmou zero requests de dados no retorno empresa →
mandato, inclusive em outra aba restaurando o IndexedDB; filtros distintos
consultaram a API, dados expirados após cinco minutos foram atualizados e SSR
novo prevaleceu sobre a cópia local. Proxy sem barra final evita redirects na
hidratação dos catálogos de casas/partidos. Sem erros JavaScript nesse fluxo.

### Infraestrutura compartilhada

O estado atual está em [redis_cache.md](redis_cache.md). Fons escreve respostas
JSON públicas no Redis com TTL padrão de cinco minutos; Rostra compartilha a
chave e executa somente leitura, com fallback HTTP para Fons. Não adicionar
SET/EXPIRE/invalidação ao Rostra. Configuração privada pode vir do `.env` da raiz;
credenciais jamais recebem prefixo PUBLIC_. As páginas homepage/pessoa/mandato
usam loaders universais com SSR e seed de TanStack Query, inclusive primeiras páginas de
registros. As descrições anteriores de carregamento exclusivamente no navegador
são evidência histórica, não o estado atual.

Correção do hook de cache: `Response` explícita pode ter `status_code=None` no
`after_request`; Litestar só aplica o status da rota em `to_asgi_response`.
Use o status explícito quando presente, senão o da rota. Comparar diretamente
com 200 impedia cache de pessoa, mandato, CEAP, emendas e outras respostas JSON
já serializadas. Regressão reproduzida e testada nas rotas reais, com core real,
IDs diferentes, limit/order/pull_after e filtros. Toda query string já faz parte
da chave, inclusive parâmetros repetidos; não reduzir a chave apenas ao ID.

O histórico do mandato no Rostra agora separa exercícios e filiações partidárias
em abas, com eventos em aba própria. A API já retornava `eventos`; não duplicar
consultas nem criar novo endpoint para esse histórico. O mapeamento TypeScript
espelha `TipoObjetoMandato`, com teste de cobertura dos códigos do enum Python.
Períodos sem término usam “O momento”; dados do gabinete são sequenciais.

## Editor: fotos fora dos watchers TypeScript

As pastas `assets/candidatures` e `downloads/tse/candidatures_photos` têm alto
volume de arquivos e não devem entrar nos watchers do editor. `.vscode/settings.json`
configura `typescript.tsserver.watchOptions.excludeDirectories`, além das exclusões
já existentes de watcher/busca. Os tsconfigs de Rostra e shared também declaram
`watchOptions.excludeDirectories`, sem substituir include/exclude herdados do
SvelteKit. Não usar `files.exclude`: as fotos devem continuar visíveis no Explorer.
Após alterar a configuração, reinicie o TS Server no editor. As configurações
locais em `.vscode` são ignoradas pelo Git; os tsconfigs são versionáveis.

### Detalhes: navegação e resumo lateral

Pessoa e mandato usam layout compartilhado com identidade, foto recente e resumo
financeiro na lateral; no mobile, esses blocos precedem o conteúdo. As seções
principais usam links `?aba=...`, preservando SSR, histórico do navegador e links
diretos. Perfil, emendas, despesas e histórico do mandato mantêm consultas e
paginação keyset existentes. Só a lista da aba ativa é montada; TanStack Query
preserva o cache ao trocar seções.

Emendas agora têm linhas compactas e modal nativo com dados básicos. Não há ainda
rota ou endpoint dedicado à emenda. Nenhum contrato Fons/core foi alterado nessa
reformulação; não inferir modalidade Pix, salário, escolaridade, situação atual ou
percentuais de sincronização a partir de campos que não os representam.

A listagem de CEAP do mandato agora agrega `fornecedor` no contrato do core
(`FornecedorDetalhado`, também base de `FornecedorEmenda`). A resolução em lote
por página foi extraída para `infra/opendata/mandate/suppliers.py` e reutilizada
pelas emendas. Preservar identidade (ID, tipo de documento), deduplicação de nomes,
CNPJ via estabelecimento/empresa e os caminhos rápidos sem Pydantic. Testes HTTP
com core real cobrem nomes, ausência, colisões entre tipos, comprovantes e keyset.

### Período de despesas

CEAP aceita start_date/end_date ISO inclusivos; o antigo from_date yyyy-dd-mm
continua compatível. CeapListParams ganhou to_date ao final para preservar chamadas
posicionais. Limite final inclui horários por comparação com o dia seguinte,
sem CAST na coluna. Rostra usa períodos de meses completos com URL/SSR e chave
TanStack contendo limites; próxima página repassa as mesmas datas. Não aplicar
filtro só aos dez registros já carregados. O resumo financeiro agora acompanha o período da lista (veja correção abaixo). Testes cobrem último horário do mês, ano
bissexto, limites, entradas inválidas, keyset e separação das chaves de cache.

Correção: o resumo financeiro da aba de despesas agora acompanha o período.
`GET /opendata/mandates/{id}/ceap/summary` retorna o contrato InsightsCeap, filtrado
por start_date/end_date inclusivos, sem paginação. Reutiliza a agregação existente
com consultas menores e preserva MODEL_PARSED/DICT/JSON_STRING. Rostra carrega a
agregação no SSR, com chave Redis incluindo datas; falha do resumo filtrado não
faz fallback silencioso para totais globais. Os cards e a lateral de despesas
usam esses totais; a lateral informa separadamente os períodos de CEAP e emendas. Sem
filtro, reutiliza o resumo do detalhe do mandato. Testes com 17 registros confirmam
que o total inclui páginas ainda não carregadas, além de validação e cache.

### Emendas por ano e resumo lateral

Emendas permanecem no card lateral ao abrir Despesas. O período de despesas
seleciona anos orçamentários completos para esse card, ignorando os meses; um
intervalo entre anos soma todos os anos abrangidos, com legenda própria.
A aba Emendas tem filtro por ano via amendment_year na URL e opção all. Sem
seleção explícita, herda os anos das despesas. A listagem Fons já aceita ano
repetido; SSR e paginação usam amendmentQuery, e a query key inclui os anos.
Os cards usam total_por_ano do mandato, sem somar apenas a página carregada.
Não foi necessário alterar o contrato da API para essa seleção anual.

### Rostra: mover o projeto entre discos (2026-11-07)

`vite.config.ts` acrescenta somente a pasta compartilhada `assets/` ao
`server.fs.allow` fornecido pelo SvelteKit. O caminho usa
`fileURLToPath(new URL('../../assets', import.meta.url))`, sem fixar a localização
do checkout e preservando espaços no nome do disco. O alias `$assets` continua
relativo no SvelteKit. A cópia para o HDD continha caches Vite com referências
ao diretório antigo; após mover o projeto, reinicie em `apps/rostra` com
`pnpm exec vite dev --force` e recarregue a página. Não adicione o diretório
antigo à lista permitida. Detalhes em [rostra_homepage.md](rostra_homepage.md).

Validação: `pnpm run check` sem erros e com dois avisos em `PersonDetails.svelte`,
não alterado nesta correção. Vite real confirmou transformação de `PortalIcon`
sem caminho antigo e HTTP 200 para `history.svg` e `document.svg`, com conteúdo
idêntico aos arquivos do HDD e preservação das permissões padrão do SvelteKit.

### Vite: import de componente recém-criado

Um 500 em desenvolvimento foi reproduzido na aba Despesas: Vite mantinha erro de
resolução de AmendmentYearFilter.svelte após o componente ser criado. As respostas
reais do Fons e o build SSR estavam corretos. Invalidar o importador
(MandateDetails.svelte) por atualização do arquivo resolveu, confirmado com HTTP
200 no servidor já aberto. Ao criar componentes com o dev server ativo, grave os
arquivos novos antes de adicionar os imports; se houver erro de resolução antigo,
invalide o importador ou reinicie Vite. O hook temporário de diagnóstico foi removido.

O seletor de ano de emendas inclui todos os anos das datas da legislatura,
além de anos registrados/selecionados. Antes, usava somente total_por_ano e
ocultava anos da legislatura sem emendas. Um ano sem registros continua
selecionável e apresenta o estado vazio, sem inferir ausência de atuação.

Nomes civis e de urna são normalizados na apresentação do Rostra (detalhes,
metadados/compartilhamento e ranking): palavras com três ou mais letras recebem
inicial maiúscula; as demais ficam minúsculas, inclusive no início. Acentos são
preservados, espaços normalizados e os dados originais da API permanecem intactos.
A função compartilhada está em lib/format/name.ts.

### Empresas no Rostra e recebimentos (2026-10-08)

`/empresas/[id]` usa os detalhes cadastrais existentes e o novo endpoint
`business/{id}/receipts`, com totais por estabelecimento e ranking top 10 por
mandato. Modais nas despesas/emendas consultam o estabelecimento pelo fornecedor
CNPJ e navegam pelo business_id. Filtro compartilhado ganhou ano inteiro.
CEAP usa valor líquido/data de emissão; emendas usam valor recebido do fornecedor
e anos orçamentários inteiros. Totais contam cada pagamento uma vez; ranking
atribui emendas integralmente a cada mandato, deduplicando pares de autoria.
Não somar o ranking para obter o total da empresa. Contrato, limitações e testes
em [business_details.md](business_details.md). Sem regeneração; reiniciar Fons.

O ranking da empresa inclui nome completo da casa e referência à candidatura
mais recente da pessoa (ano, última data de turno e ID como desempates),
resolvida em lote. Rostra usa Portrait e o padrão `57ª legislatura`. Esses campos
ficam no cache da resposta de recebimentos; a página não consulta a lista de
casas nem detalhes completos de cada pessoa para montar o ranking.

O ranking de empresa retorna o objeto completo `candidatura_recente` junto de
cada mandato, reutilizando CandidaturaRecente do detalhe da pessoa. Portrait
recebe `candidatura_recente.id` para resolver a URL; iniciais são apenas fallback
quando não há candidatura/foto disponível.

### Resolver empresas por CNPJ (2026-10-08)

`business/resolve?cnpj=...` usa Polars String.hash com a mesma seed do Turi;
constante compartilhada em core/opendata/common/identity.py, sem importar o
settings do produtor na API. Preservar zeros à esquerda; CNPJ completo usa a
base de oito dígitos para ID da empresa. Não verifica existência/checksum.
Rostra redireciona `/empresas/cnpj?cnpj=...` para o ID Avoar e preserva o período.
Na rota de detalhe, IDs existentes têm prioridade sobre possível CNPJ numérico;
só 404 autoriza fallback. Detalhes em business_details.md. Sem regeneração.
Mudanças de versão do Polars devem conferir hashes contra dados existentes.

Cadastro de estabelecimentos no Rostra usa componente compartilhado entre card
e modal, exibindo situação/datas, natureza jurídica, porte, CNAEs descritos e
contatos. A situação 5 significa baixada no core (08 no bruto). A tabela CNAE
local da Receita virou um JSON de apresentação; não exige chamada externa.
Não inferir CNAE principal quando o produtor pode omiti-lo, nem regularidade
pela ausência de situação especial. Veja business_details.md.

### Rostra: busca de parlamentares (2026-10-09)

Estado atual (2026-10-29): a tela e o menu se chamam “Pessoas públicas”, mantendo
`/parlamentares` para preservar links. A busca exige só nome; casa e legislatura
são opcionais e não recebem defaults dos catálogos. A API de search também aceita
filtros omitidos e inclui pessoas sem mandatos por padrão (`include_ghosts=1`).
Filtros institucionais/partidários exigem mandato no recorte. Cards sem mandato
informam a ausência na base; com mandatos, exibem casa, legislatura e exercícios.
O query service associa legislaturas por `(id, orgao_id)` e preserva mandatos
mesmo sem exercícios ou legislatura catalogada. Filtros opcionais usam contrato
próprio de pessoas públicas, sem afrouxar os parâmetros do repositório de mandatos.
Essa primeira ampliação não exigiu ETL/reindexação; reiniciar Fons. Os registros abaixo descrevem a
implementação histórica, que inicialmente exigia casa e legislatura.

Filtros de candidatura (2026-10-29): search recebe `codigo_cargo_tse` e `pleito_id`
opcionais em `PublicPeopleListParams`. Ambos filtram a mesma candidatura via
`EXISTS`, sem verificar resultado, votos ou mandato. Não usar o enum de cargos do
core no lugar dos códigos originais do TSE. A eleição da tela é o Pleito geral
(ano/tipo/data), consultado pelo catálogo paginado existente; não selecionar uma
disputa local ou um ano isolado como se fosse esse evento. Cargo/pleito ficam na
URL/SSR/chave de cache e acompanham paginação e mudanças de casa. Casa/legislatura
continuam filtros de mandato e se combinam com os de candidatura.

Para que pessoas exclusivamente não eleitas fossem encontradas, o produtor geral
foi ampliado, mantendo o recorte anterior somente no vínculo externo da Câmara.
Regeneração local: 430.723 → 599.577 pessoas (168.854 novas), todos os IDs antigos
preservados e 1.141 vínculos externos integralmente iguais. Entre as novas,
168.698 têm candidatura não eleita no bruto. Auditoria de 1.276.012 linhas brutas,
em 2.387 grupos por ano/cargo/UF/situação/tipo, sem identidades elegíveis ausentes.
Fontes locais de 2018/2020/2022/2026; não extrapolar cobertura a outros arquivos.
Restaurados Bloom filters com comparação completa e reconstruído só o índice de
pessoas, com 599.577 documentos. Mandatos e finanças não precisaram de regeneração.
Backups locais em `/tmp/avoar-people-candidature-expansion/backup`. Relatório em
[public_people_candidature_filters_2026-10-29.json](audits/public_people_candidature_filters_2026-10-29.json).
Reiniciar Fons após a publicação para renovar readers e índice. Cache anterior
pode durar seu TTL normal; Rostra não invalida o Redis.

Validação dos filtros: 12 testes focados da API, três do produtor e os 17 arquivos
de testes do Rostra passaram; check e build passaram. Cobertos cruzamento de
cargo/pleito na mesma candidatura, não eleito no produtor, independência de
mandatos, composição de filtros, ID uint64, paginação por relevância e caminhos
rápidos sem Pydantic. Chromium validou filtros/paginação/mobile com API fixture,
sem erros JavaScript; Venato/DataFusion reais após a troca validaram pessoa nova
sem mandato no recorte escolhido.

Ordenação atual da pesquisa: `pull_by=relevance&order=desc` é o padrão da API e
o pedido explícito do Rostra. Preservar a sequência de `Venato.search_ids`, até
nos empates; não reordenar por ID ao hidratar. O cursor continua sendo o ID da
última pessoa exibida, agora usado como âncora na sequência completa do Venato.
Não aplicar `id > cursor` nesse modo. A listagem mantém sua ordenação anterior;
search ainda aceita `pull_by=id`. Filtrar candidatos em lotes de até 1.000 e
montar mandatos só da página final; continuar após hits ausentes ou excluídos pelo
recorte. Não introduzir offset de página ou persistência de resultados.
Índice/texto/recorte devem permanecer iguais entre páginas; não há snapshot da
busca. Cursor fora dos hits retorna 400. Reiniciar Fons, sem ETL/reindexação.
Validação desta ordenação: 11 testes focados da API passaram, incluindo Venato
temporário real, empates e paginação de 1/2 resultados sem repetição ou perda.
Os 17 arquivos de testes do Rostra, check e build passaram.

Validação desta ampliação: dez testes focados de pessoas/API passaram, incluindo
core real, busca sem recorte, pessoas sem mandato, filtros independentes, cursor,
legislaturas de casas distintas com mesmo ID e caminhos rápidos sem Pydantic.
Os 17 arquivos de testes do Rostra, Svelte check e build passaram. Smoke Chromium
com API fixture validou busca geral, cards de várias casas, paginação, filtros,
preservação do nome digitado, mobile sem overflow e falha do catálogo, sem erros
JavaScript. A suíte global da API foi interrompida após travar na área de empresas;
não é evidência de aprovação dessa suíte inteira. Não houve regeneração de dados.

`/parlamentares` ativa o menu lateral e inaugura a pesquisa Venato no frontend,
via `/opendata/public_people/search`. Metadados vêm de casas/legislaturas; busca,
recorte e cursor ficam na URL. SSR/TanStack preservam Redis somente leitura e
proxy privado. Páginas de 20 por ID; não inferir recência/relevância. O índice
pesquisa `nome`, não `nome_completo`. Partidos são históricos do recorte.

A rota de busca explicita query parameters, listas repetidas e limites;
`pull_by=id` evita nome sem cursor composto. Teste HTTP usa core real/DuckDB e
substitui somente resolução Venato. Check/build/test do Rostra e testes de pessoas
passaram; índice real e navegador não foram verificados. Reiniciar Fons, sem ETL
se o índice existe. Detalhes em [rostra_details.md](rostra_details.md).

A busca de parlamentares foi enriquecida com legislatura e candidatura básica
vinculadas a cada mandato no contrato básico compartilhado por list/search.
`MandatoPesquisaPessoa` preserva exercícios/filiações e adiciona campos nullable,
sem puxar detalhes financeiros/votos. Rostra reutiliza Portrait com ID da
candidatura do mandato mais recente no recorte e organiza filiações por exercício,
com datas. Não confundir essa foto com candidatura_recente da pessoa nem partido
da candidatura com filiação atual. Testes cobrem JSON/DICT/MODEL_PARSED,
candidatura ausente e caminhos rápidos sem Pydantic. Reiniciar Fons; caches
existentes podem manter o payload anterior até expirar, sem invalidar pelo Rostra.

### Bandeiras de localidades (2026-10-09)

Importados 4.381 SVGs municipais em assets/localidades/UF/codigo-IBGE.svg,
27 estaduais por sigla e BR.svg. Variantes estaduais CE/ES/PB usam v2; ZIP
original preservado. Fons resolve /assets/localidades/codigo-IBGE.svg pelo
prefixo estadual do IBGE, sem banco; aceita UF.svg/BR.svg. Rotas explícitas
mantêm também o caminho UF/codigo.svg. Não montar StaticFilesRouter no mesmo
prefixo localidades: ele oculta o resolver. Testes HTTP incluem coexistência
com assets estáticos, cache e 404. Reiniciar Fons; sem ETL. Detalhes em
[locality_assets.md](locality_assets.md).

### Malhas GeoJSON por UF (2026-10-22)

Verificação HTTP (2026-10-25): a compressão global do Fons já alcança assets
estáticos, inclusive streaming. O worker MapLibre negocia Brotli/gzip
automaticamente pelo navegador; não tentar definir `Accept-Encoding` em JS ou
`transformRequest` (header proibido). Preservar as URLs normais e o processamento
no worker. Tornado explícito o fallback gzip e corrigido `Vary` via `before_send`,
depois dos middlewares: o CORS instalado apagava `Accept-Encoding` ao colocar
`Origin`. Incluir também variantes identity para cache HTTP consistente.
SP: 39,76 MB originais → 11,59 MB Brotli / 10,61 MB gzip, com igualdade byte a
byte após descompressão. Chromium carregou DF/SP reais via MapLibre; oito testes
de compressão/assets/CORS/cache passaram. Compressão já estava ativa antes;
não atribuir a esta correção um novo ganho de transferência ou de parsing.
Detalhes e limites em [brazilgeo/README.md](../apps/scripts/brazilgeo/README.md)
e no [relatório HTTP](audits/geojson_http_compression_2026-10-25.json).

`apps/scripts/brazilgeo/generate.py` usa o Downloader do Turi com `keep_raw=True`
para baixar a malha municipal IBGE 2025 e GeoPandas para gerar
`assets/brazilgeo/BR.geojson` (27 estados/DF) e `states/<UF>.geojson`.
Cada execução limpa somente `assets/brazilgeo/` e refaz o download. Os detalhes
municipais preservam a geometria original, reprojetada para WGS84; código IBGE
vem diretamente de CD_MUN como string. Não exige ETL nem cruzamento por nomes.
Os imports internos do Downloader são qualificados por `apps.turi.src`, permitindo
reutilizá-lo sem acrescentar a árvore do Turi ao PYTHONPATH.

A camada nacional dissolve os municípios e simplifica as fronteiras em conjunto,
com tolerância padrão de 1 km em EPSG:5880. A fonte possui inconsistências de
cobertura estadual; Shapely 2.2 coverage_clean normaliza somente essa camada com
snap de 1 cm, sem preencher lacunas, antes de simplificar. A diferença medida da
normalização foi de cerca de 75,3 m². `municipios_bbox` conserva a extensão
original para seleção por viewport; `municipios_url` aponta ao arquivo estadual.
Não simplificar os detalhes municipais sem uma nova decisão explícita.

A fonte inclui 5.573 feições, entre elas duas áreas operacionais de lagoas no RS
(4300001/4300002), que não são municípios. Preservar essas áreas e a ausência de
votos ao cruzar os assets. Comando, contrato e testes em
[brazilgeo/README.md](../apps/scripts/brazilgeo/README.md).
A geração real produziu BR de 1,03 MiB e cerca de 601 MiB no total. Auditoria de
todas as feições confirmou metadados e geometria municipal exatos após reprojeção
(normalizando a ordem/orientação dos anéis), IDs/cobertura completos por UF e
cobertura estadual válida. Relatório em
[brazilgeo_2026-10-22.json](audits/brazilgeo_2026-10-22.json).

### Municípios: panorama, finanças e votação local (2026-10-09)

Rostra ativa /municipios e /municipios/codigo-IBGE, com bandeiras, filtros, panorama
financeiro, evolução anual, funções, top autores e votação por casa. Contratos e
limitações em [municipalities.md](municipalities.md). Agregar recursos diretamente
para totais; deduplicar autoria por emenda/pessoa só no ranking, sem rateio.

Votos municipais exigem geografia do boletim físico, não codigo_local eleitoral.
Turi acrescenta codigo_municipio_ibge no boletim pelo mapa TSE, sem alterar hashes
ou votos. Ambiguidades de ID/localidade ficam null. Eleições históricas persistem
tipo 0 ordinário e cargo 0-based; usar códigos legislativos TSE dos itens no filtro.
O detalhe escolhe ano recente com registros por casa e só mandatos vinculados.

Enriquecimento local preservou 1.356.060 registros anteriores integralmente:
1.354.310 com município, seis ambiguidades excluídas e 1.744 não mapeados.
Arquivo de itens não mudou. Banco com lock de leitura não foi alterado; query
usa o dump enriquecido até a próxima sync normal. Não encerrar processos do usuário
para obter escrita. Uma regeneração completa também variava metadados pela
unique(subset=id); o acréscimo local foi feito por join e auditado contra todos os
campos anteriores. Reiniciar Fons; cache antigo pode durar até expirar.
