# Ordenação física dos Parquets finais

Em 2026-10-14 foram identificados 16 datasets em 14 produtores Turi sem sort
final. Os produtores passaram a aplicar `FINAL_PARQUET_SORT_KEYS`, definido em
`apps/turi/src/scripts/bricks/parquet_order.py`, após as transformações e antes
de escrever o resultado. Nenhum produtor foi executado novamente nessa operação.

Os sorts anteriores foram preservados. Em particular, candidaturas e itens de
boletim já ordenam no helper final, e pleitos em `build_pleitos`: ausência de
`.sort()` na linha do writer não significa que a saída esteja desordenada.

| Dataset | Chaves, em ordem crescente |
|---|---|
| Endereços IBGE | município, CEP, número, cluster, ID |
| Complementos de endereço | endereco_id, nome, valor |
| Empresas | id |
| Estabelecimentos | empresa_id, id |
| Sócios | id |
| Sociedades (`partnerhip`) | empresa_id, tipo_socio, socio_id, data_entrada |
| Convênios | id |
| Vínculos emenda/convênio | emenda_id, convenio_id |
| Autoria de emendas | mandato_id, emenda_id, tipo_autoria |
| Itens de emendas | type, id |
| Recursos de emendas | emenda_id, localidade, função, subfunção, programa, ação, plano |
| Pagamentos de emendas | emenda_id, fornecedor_id, tipo_documento |
| Fornecedores GOV | tipo_documento, documento |
| Nomes de fornecedores GOV | fornecedor_id, nome |
| Casas legislativas | id |
| Turnos de eleição | eleicao_id, numero_turno, id |

Nulos ficam primeiro, conforme o padrão desses sorts Polars. As chaves secundárias
organizam registros dentro da chave principal; não tornam todas as colunas
independentemente ordenadas. Por exemplo, ordenar estabelecimentos por empresa
favorece seus detalhes/vínculos; consultas somente pelo ID do estabelecimento
não recebem a mesma seletividade de min/max de uma ordenação por ID global.
Endereços preservam agrupamento geográfico por município/CEP/número; um filtro
isolado por cluster_id não equivale a um índice global nesse campo.

A ordenação permite estatísticas min/max mais seletivas para as chaves principais
e pode melhorar compressão dentro dos grupos. Isso não garante redução de disco:
ordenar hashes de identidade pode reduzir repetição nas outras colunas. O relatório
registra bytes antes/depois; não houve benchmark comparativo de endpoints.

## Reordenar dados existentes

A ferramenta abaixo lê somente os dumps finais, sem adaptadores, downloads,
geração de IDs ou deduplicação:

```bash
PYTHONPATH=apps/turi/src:. POLARS_MAX_THREADS=2 .venv/bin/python \
  -m scripts.maintenance.sort_final_parquets \
  --report docs/audits/parquet_sort_2026-10-14.json
```

Pode-se limitar a execução com `--table opendata_business`; são aceitas várias
ocorrências. Padrões: 2GB de memória gerenciada e 2 partições para ordenação externa
DataFusion. Ajustes: `--memory-limit` e `--target-partitions`; partições não são
um limite rígido de threads. O writer agrupa batches nos row groups originais.
Para pools pequenos, reduza também `--target-partitions` (por exemplo, 1):
merge e buffers ainda precisam caber em memória. O limite gerenciado cobre
DataFusion; auditoria Polars e buffers do writer usam memória adicional.
Spill fica em `.parquet_sort_tmp` no filesystem do projeto, não no tmpfs de `/tmp`.
Os Parquets de cada pasta são tratados individualmente; o processo não declara
ordenação global entre arquivos de fontes diferentes.

Arquivos já ordenados são detectados em batches e mantidos. Para os demais:

1. Guarda schema Arrow, contagem, codec e tamanho dos row groups.
2. Audita o conteúdo original, ordena com spill e exporta batches Arrow para
   um arquivo temporário invisível aos globs `*.parquet` da API.
3. Restaura o schema original, incluindo large_string/large_list, uint64, datas,
   Decimal e metadados. Mantém codec e limite de linhas dos row groups; encodings
   e tamanho físico podem mudar ao trocar de writer.
4. Compara contagem de linhas, soma/xor dos hashes de todas as colunas, contagens
   de nulos e totais inteiros/Decimal, e verifica ordenação física em batches,
   inclusive nos limites entre batches. Fingerprints são uma auditoria
   probabilística do multiconjunto de linhas, não uma prova criptográfica.
5. Recusa publicar se o arquivo de origem mudou durante o trabalho. Após validar,
   cria um hardlink de recuperação e usa `os.replace` por arquivo, removendo
   o link após sucesso. Uma falha de auditoria mantém o original intacto.
6. Remove apenas os spills e temporários próprios; registra o progresso no JSON
   após cada arquivo. Uma execução interrompida pode ser retomada: arquivos
   publicados e ordenados serão pulados na nova execução.

A publicação por arquivo preserva linhas e relações, mas não invalida metadados
já mantidos por sessões da API. Coordene a manutenção e reinicie Fons ao concluir.
Não encerre processos do usuário para obter acesso aos dados.

## Verificação

`apps/turi/tests/test_final_parquet_sort.py` cobre duplicidades, unsigned até
2^64-1, listas com nulos/vazias, datas anteriores a 1900, frações de segundo,
Decimal, metadados, preservação do codec, ordenação entre batches, skip idempotente,
colunas ausentes e falha de auditoria sem publicação.

O relatório da execução local está em
[audits/parquet_sort_2026-10-14.json](audits/parquet_sort_2026-10-14.json).
Essa execução precedeu a retirada de DuckDB e seus fingerprints usam o hash
histórico daquele motor. A ferramenta atual usa `polars_hash_rows_v1` (soma/xor),
comparável somente dentro da mesma versão Polars. Os dados finais não foram
reprocessados na migração da ferramenta para DataFusion.

Execução local concluída: 18 arquivos examinados, 16 reordenados e dois já
ordenados, totalizando 346.342.315 linhas. O conjunto examinado passou de
14,515 GiB para 14,636 GiB (+124,482 MiB). O arquivo de endereços caiu de
5.002.224.658 para 3.767.217.614 bytes; agrupamento por hashes nos demais
arquivos compensou essa redução. Todos os temporários próprios foram removidos.
A suíte Turi passou com 26 testes na execução original (27 após a migração da ferramenta). O smoke da API após a manutenção, com sessões
novas, retornou HTTP 200 para pessoa, estatísticas da home e detalhe de empresa.

Após a retirada de DuckDB, a ordenação DataFusion foi verificada com 500.000
linhas sintéticas, pool de 64MB e uma partição. O EXPLAIN ANALYZE confirmou
spill; conteúdo e row groups foram preservados. A suíte cobre também agrupamento
de batches DataFusion em row groups de 10.000 linhas.
