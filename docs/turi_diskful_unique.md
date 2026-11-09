# Deduplicação do Turi com índice de hash em disco

Implementada em 2026-10-27 em `apps/turi/src/infra/diskful_unique.py`, com
Polars 1.38.1, DataFusion 55.0.0 e PyArrow 25.0.1 já presentes no projeto.
Não adiciona dependências nem cria um banco ou materialização para a API.

## Uso e contrato

```python
from infra.diskful_unique import diskful_unique

lf = diskful_unique(lf)                      # Linha inteira.
lf = diskful_unique(lf, "id")                # Uma coluna.
lf = diskful_unique(lf, "empresa", "socio")  # Chave composta.

# Também aceita a assinatura por nomes, sem seletores/expressões Polars.
lf = diskful_unique(lf, subset=["empresa", "socio"], keep="first")
```

A função **executa a etapa imediatamente** e devolve um `pl.LazyFrame` que
escaneia seu resultado Parquet temporário. As transformações seguintes continuam
usando a API Polars. Não é uma expressão nem uma alteração global de `.unique()`.

Aceita `keep="any"`, `"first"`, `"last"` e `"none"`. `any` escolhe a primeira
ocorrência. A ordem das linhas selecionadas é preservada mesmo quando
`maintain_order=False`; não há ordenação implícita das fontes. `last` e `none`
precisam de duas passagens. Colunas originais e tipos são preservados, incluindo
UInt64, Decimal, datas, precisão de nanossegundos, listas, structs e categorias.

Esta é uma fronteira de execução: filtros e projeções escritos **depois** da
chamada não podem mais ser empurrados para a leitura anterior pelo otimizador.
Projete antes as colunas necessárias ao domínio. No produtor de urnas basta
`NR_URNA_EFETIVADA`; materializar todas as colunas brutas seria um desperdício.
Não mova filtros ou remova colunas que participem da escolha de representantes.

## Algoritmo e recursos

1. Executa o plano anterior em Polars streaming e grava um Parquet intermediário,
   com row groups limitados a `batch_size`, padrão 16.384 linhas.
2. DataFusion lê esse arquivo em batches Arrow, com uma partição e sem
   reparticionamento da leitura, preservando as posições para first/last.
   Não há um `DISTINCT` global DataFusion no algoritmo: o estado de deduplicação
   é o índice do sistema de arquivos.
3. A chave usa MessagePack com limites e tipos, SHA-256 completo, normalização
   de NaN/zeros com sinal e valores físicos para temporais, inclusive aninhados.
   Não usa concatenação ambígua de strings nem hash Polars de 64 bits como chave.
4. Cada chave distinta cria um marcador vazio com o hash completo como nome,
   dentro de um diretório pelo prefixo hexadecimal. Um arquivo `.key` separado
   guarda a chave original e posições/contagem. No encontro de um hash, compara
   a chave original; colisões diferentes recebem sufixos e não perdem linhas.
5. Para any/first, reduz repetições **apenas dentro do batch** usando Polars
   eager antes de consultar o índice. Esse `.unique()` é limitado pelo batch,
   não pela cardinalidade global. Isto é relevante para BUs, que repetem os
   mesmos metadados em muitos votos consecutivos.
6. Escreve as linhas selecionadas em batches, elimina entrada/índice/spill e
   mantém somente o Parquet usado pelo LazyFrame devolvido.

O índice não mantém um set/dict global de chaves em RAM. Há dois arquivos por
chave distinta e até 256 diretórios de prefixo. Marcadores vazios ainda consomem
inodes e entradas de diretório; `.key` também usa blocos do filesystem. Dados
muito distintos custam mais syscalls e disco. Os caches do sistema operacional,
metadados Parquet e buffers dos motores continuam existindo.

| Configuração | Padrão | Escopo |
|---|---|---|
| `TURI_UNIQUE_TEMP_DIRECTORY` | `.turi_unique_tmp` no cwd | Entrada, índice, spill e resultados intermediários |
| `TURI_UNIQUE_MEMORY_LIMIT` | `256MiB` | Pool DataFusion, não o RSS total |
| `batch_size=` | 16.384 | Limite de linhas por batch/row group da entrada |
| `memory_limit=` | Variável acima | Sobrescreve o pool para uma chamada |
| `temp_directory=` | Variável/sessão acima | Sobrescreve o diretório para uma chamada |

Escolha um diretório em disco, não tmpfs. O custo em bytes de um batch depende
da largura das linhas. Os limites acima não abrangem alocações Polars, Python,
Arrow, writer nem operações anteriores à chamada. O helper não transforma um
join/sort anterior que materializa a entrada em uma operação limitada por RAM.

## Ciclo de vida

```python
from infra.diskful_unique import diskful_unique, diskful_unique_session

with diskful_unique_session():
    lf = diskful_unique(lf, "id")
    lf = lf.with_columns(...).sort(...)
    lf.sink_parquet(destination)
```

Também se pode aplicar `@diskful_unique_session()` a uma função que **consome ou
grava** os resultados antes de retornar. Os produtores de urnas e boletins usam
essa forma, sem reindentar suas cadeias. Não devolva scans intermediários para
fora da sessão: seus arquivos são removidos ao sair.

Sem sessão, o resultado permanece até o encerramento normal do processo ou
`cleanup_diskful_unique()`. Este último invalida os scans ainda dependentes dele.
Índice e entrada não ficam retidos até esse momento. Chamadas isolam seus
temporários por PID/token, inclusive em sessões aninhadas. Exceções removem os
parciais; SIGKILL ou queda do processo podem deixar diretórios órfãos. Não apagar
temporários de processos em execução. O diretório padrão está no `.gitignore`.

## Integração inicial e descoberta de memória

Somente `EvmDataScript` e `EvmBulletinDataScript` foram migrados na etapa inicial.
Permanecem a geração dos IDs, projeções e ordenações finais. Os itens/votos de
boletim não estavam cobertos por essas medidas; a correção posterior do seu
processamento e da ordenação está em [turi_bulletin_items.md](turi_bulletin_items.md).
Os demais produtores não foram migrados em massa.

O teste progressivo de 4.367.862 linhas encontrou um `in-memory-join` no plano
físico do Polars 1.38: `validate="m:1"` forçava materializar a entrada bruta,
antes da deduplicação. A unicidade agora é validada somente no pequeno mapa de
municípios, ignorando chaves nulas como a validação anterior; o join grande é
streaming. Chaves de município com dois destinos continuam falhando.

O join final de boletins não precisa de `validate="1:1"`: a deduplicação por
`id` prova a unicidade da esquerda e `group_by("id")` prova a da direita.
Mantém-se a regra de município IBGE único não nulo; conflitos ficam nulos.
Não ampliar essa retirada de validação para joins sem essas invariantes.

## Validação e repetição das medidas

Testes em `apps/turi/tests/test_diskful_unique*.py` comparam os quatro keeps com
Polars em limites de batch, forçam colisões SHA-256, preservam tipos/nanossegundos,
testam consumo repetido do LazyFrame, limpeza/erros e executam os produtores reais
em fixtures Parquet, com conflitos de município e arquivos duplicados.

```bash
PYTHONPATH=apps/turi/src:. POLARS_MAX_THREADS=2 uv run \
  -m scripts.maintenance.benchmark_diskful_unique \
  --rows 10000 100000 1000000 \
  --raw downloads/tse/evm_bulletin/ARQUIVO.parquet \
  --report docs/audits/diskful_unique.json
```

`--skip-synthetic` executa apenas fontes reais. `--producer-scripts` executa os
produtores completos, redirecionando somente seus caminhos no subprocesso para
temporários; sem essa opção mede a etapa de deduplicação da projeção real.
Não executa o entrypoint amplo, não atualiza metadados de execução e não publica
nem substitui dumps finais.

Cada caso roda em subprocesso, com timeout de 300 s, monitoramento RSS a cada
100 ms e interrupção acima de 1.536 MiB por padrão. `--max-rss-mib` ajusta esse
limite; não é um cgroup nem um limite rígido imposto pelo kernel. Interrompe
também se o espaço livre do filesystem ficar abaixo de 4 GiB. O relatório é
incremental e registra falhas antes de parar; não esconde tentativas abortadas.

A referência independente usa DataFusion DISTINCT com pool de 128 MiB e spill
no diretório temporário em disco. A auditoria é `EXCEPT ALL` nos dois sentidos,
comparando todas as colunas e multiplicidades. Para o produtor completo, aplica
a consolidação original sobre a referência já reduzida; any admite escolher a
primeira ocorrência. A auditoria de valores não verifica ordenação final, que
é coberta pela fixture do produtor.

Evidência consolidada em
[audits/turi_diskful_unique_2026-10-27.json](audits/turi_diskful_unique_2026-10-27.json).
Não há benchmark controlado contra Polars nem cache frio. `dedup_seconds` inclui
helper e gravação da saída; com `--producer-scripts`, inclui o produtor inteiro.
Preparação da referência/entrada e auditoria ficam fora desse tempo. O pico
`pipeline_peak_rss_mib` inclui preparação da entrada; `worker_peak_rss_mib`
inclui também referência/auditoria. Não confundir esses valores com o pool.

Resultado dos produtores completos sobre o arquivo de 19.167.373 linhas:

| Produtor | Linhas finais | Tempo do produtor | Pico RSS até saída | Pico RSS com auditoria |
|---|---|---|---|---|
| Urnas | 101.072 | 3,856 s | 354,8 MiB | 398,9 MiB |
| Boletins | 101.072 | 12,225 s | 1.648,6 MiB | 1.733,8 MiB |

Esses casos usaram `--max-rss-mib 2048`. O limite inicial de 1.536 MiB
interrompeu testes maiores; a ampliação para 2 GiB foi explícita e preservou
a interrupção por RSS/tempo. O relatório conserva as tentativas abortadas,
inclusive a identificação do fallback e a preparação da entrada. As 74 provas
Turi passaram, incluindo 14 novos métodos de teste para helper/produtores.

Foram testadas entradas sintéticas até 1 milhão de linhas e fontes reais até
19.167.373 linhas por arquivo. A carga de 222 arquivos/254.350.014 linhas não foi
executada integralmente na validação inicial dos metadados. A correção posterior
dos itens foi validada com todos esses arquivos, conforme
[turi_bulletin_items.md](turi_bulletin_items.md). Não confundir a cobertura de
metadados, itens e demais operações do entrypoint.
