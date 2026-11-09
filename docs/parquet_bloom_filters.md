# Bloom filters nos dumps finais

Estado atual em 2026-10-15: o Turi mantém os produtores Polars com `sink_parquet`
e executa uma manutenção compartilhada ao final do entrypoint de dumps, antes
dos índices textuais. PyArrow 25.0.1 reescreve os arquivos existentes com Bloom
filters; não há materialização de banco nem regeneração dos adaptadores.

## Executar somente a manutenção

Na raiz do projeto:

```bash
PYTHONPATH=apps/turi/src:. uv run python -m scripts.maintenance.bloom_final_parquets \
  --report docs/audits/parquet_bloom_2026-10-15.json
```

O comando descobre recursivamente todos os `*.parquet` em
`parquet_dumps/opendata`, sem lista fixa de tabelas. Não visita `downloads`.
`--root` permite outro diretório; no entrypoint, usa o diretório de saída
configurado do Turi. Sem `--report`, grava `bloom_filters_report.json` ao lado
da pasta raiz examinada. O relatório é atualizado atomicamente após cada arquivo,
inclusive em falhas; arquivos concluídos permanecem publicados.

São ignorados arquivos que já contêm filtros em todos os column chunks
suportados. A decisão consulta os metadados reais, sem depender do relatório
anterior. Após regenerar algum dump, a manutenção reescreve somente os arquivos
que perderam essa cobertura. `--force` permite refazer inclusive os cobertos,
por exemplo ao mudar `--fpp`. Não execute produtores ou outra manutenção sobre
os mesmos arquivos simultaneamente.

## Cobertura e tamanho

Cada coluna física recebe filtro, incluindo folhas de listas/structs. O escritor
não suporta BOOLEAN e INT96; essas exceções aparecem em `unsupported_columns`
no relatório. Os dumps examinados nesta implementação não tinham esses tipos.
Colunas nulas recebem filtros, assim como colunas de baixa cardinalidade.

O padrão é `--fpp 0.05`, probabilidade alvo de falso positivo de 5%. O NDV
configurado é o número de linhas do maior row group original do arquivo, com
mínimo de um. Esse orçamento conservador evita uma passagem adicional para
contar valores distintos de cada coluna, mas aumenta o custo de disco quando
a cardinalidade é baixa. Folhas de listas podem ter mais valores distintos
que linhas; nesse caso, a probabilidade real pode superar o alvo. Bloom filters
admitem falsos positivos e não substituem a avaliação do predicado.

Os codecs por coluna e a utilização de dicionário/estatísticas são reaproveitados.
Níveis de compressão e encodings podem variar; o crescimento total não representa
somente os bytes dos filtros. Não há benchmark de ganho de latência da API nesta
etapa. O objetivo da execução é confirmar cobertura, integridade e custo físico.

## Memória, auditoria e publicação

Cada arquivo é reescrito sequencialmente, um row group por vez, em temporário
oculto no mesmo diretório. Não carrega o dataset inteiro em RAM e não usa `/tmp`
para os dados. `--max-row-group-mib` recusa grupos com tamanho descomprimido
declarado acima de 512 MiB por padrão; é uma proteção inicial, não um limite
rígido de RSS. Arrow, filtros e leitura de colunas aninhadas também alocam memória.

Antes da troca, confere schema Arrow e seus metadados, quantidade de linhas,
limites dos row groups, metadados de ordenação e presença de filtro em cada
column chunk suportado. Uma segunda leitura compara todos os valores em ordem,
em batches de 65.536 linhas, com Polars: inclui uint64, decimais, nulos, NaNs,
listas e duplicatas. Essa comparação confirma também a preservação da ordenação
existente, sem reordenar os dados.

Se falhar, o original permanece e o temporário é removido. Após a auditoria,
confere inode/tamanho/mtime para recusar uma fonte alterada durante a operação,
preserva permissões, sincroniza o temporário e publica por `os.replace`.
A troca é atômica por arquivo; não existe transação do conjunto de tabelas.
Reinicie sessões Fons/DataFusion após a manutenção para descartar metadados
anteriores. Não interromper processos do usuário automaticamente.

DataFusion já habilita `datafusion.execution.parquet.bloom_filter_on_read=true`
na fábrica da API. O PyArrow é usado como escritor e auditor; seu leitor não
usa os filtros para pruning. Referências oficiais:
[ParquetWriter](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)
e [Parquet](https://arrow.apache.org/docs/python/parquet.html).

## Validação

Os testes em `apps/turi/tests/test_final_parquet_bloom.py` cobrem tipos sensíveis,
listas, NaNs, nulos, duplicatas, codecs, cobertura física, reexecução, arquivos
vazios, descoberta de novas tabelas, relatório e preservação do original quando
falham a auditoria, a proteção de memória ou a verificação de alteração da fonte.
O resultado da execução local está em
[parquet_bloom_2026-10-15.json](audits/parquet_bloom_2026-10-15.json).

A suíte Turi passou com 32 testes e a suíte API/infra com 52 testes após a
atualização do PyArrow. `uv sync --locked --offline` confirmou ambiente/lockfile.
Uma consulta real com `EXPLAIN ANALYZE` nos itens de boletim confirmou métricas
de avaliação de Bloom filters no DataFusion; isso não constitui comparação de
latência com o conjunto anterior.

Execução local concluída em 2026-10-15, sem rodar produtores: 38 arquivos,
538.197.632 linhas, 3.388 row groups e 52.987 column chunks com filtros.
Não houve colunas de tipos não suportados. A operação levou 426,588 segundos
(7min07s), incluindo escrita, comparação completa e sincronização dos temporários.
O conjunto passou de 18.159.868.150 para 19.794.996.142 bytes, ou 16,913 para
18,436 GiB (+1,523 GiB; +9,004%). Nenhum temporário de dados permaneceu.
Uma segunda execução examinou e ignorou os mesmos 38 arquivos por cobertura
completa, sem reescrita. Esses números descrevem esta carga e este ambiente.

Após a troca, o lifespan real do Fons abriu uma sessão nova sobre os dumps e
aqueceu 36 tabelas. Sem Redis e com pool de 512 MB, os detalhes de pessoa
`849990518947443184`, mandato `15664400621148139699` e empresa `104979372902`
retornaram HTTP 200. Não foram reiniciados servidores já abertos pelo usuário.
