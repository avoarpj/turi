# Memória e validação dos itens de boletim

## Incidente e causa (2026-10-27)

Após a primeira implementação de `diskful_unique`, o usuário interrompeu
`run_all_scripts` ao observar aproximadamente 73 GB de consumo. A cobertura
anterior era dos produtores de urnas e metadados de boletins; não incluía o
produtor de itens/votos. Testar 19 milhões de linhas de metadados não provou
capacidade para a carga completa de itens.

Os metadados locais registravam sucesso de `evm_bulletin`, pessoas e candidaturas;
o dump de itens ainda era o antigo. O log final `found 222 bulletin files` era
compatível com a etapa de itens. O código anterior concatenava todas as fontes,
fazia três joins com `validate="m:1"` e ordenava todos os votos em Polars.
Na versão 1.38, esses joins têm fallback em memória. A ordenação global também
continuava fora do orçamento do DataFusion configurado para a deduplicação.

## Implementação atual

`EvmBulletinItemDataScript.process_data` agora:

1. Inspeciona schemas sem ler os registros e calcula o schema global normalizado
   que o concat anterior produziria. Cada arquivo recebe os mesmos tipos antes
   de gerar hashes. Isto preserva IDs quando fontes históricas têm tipos ou
   cabeçalhos diferentes; normalizar arquivos isoladamente sem esse alinhamento
   poderia mudar IDs silenciosamente.
2. Prepara e valida os mapas de municípios, eleições e candidaturas uma vez.
   Somente essas dimensões ficam materializadas. Na carga observada tinham
   5.571, 5.749 e 631.047 linhas, respectivamente. Candidaturas ambíguas continuam
   sem atribuição. `validated_lookup` verifica unicidade das chaves não nulas,
   incluindo chaves compostas; o join grande não usa validação em runtime.
3. Processa uma fonte por vez em Polars streaming, mantendo as expressões de
   identidade, votos, localidades e referências. Grava partes não ordenadas em
   Parquet, com row groups de 16.384 linhas. Não mantém um plano de votos de todas
   as fontes nem refaz a agregação de candidaturas para cada arquivo.
4. Confere linhas e soma de `QT_VOTOS` bruto contra linhas e `quantidade` da parte.
   Preserva multiplicidades e os filtros anteriores de tipo de eleição.
5. Ordena todas as partes via DataFusion, com spill Zstd em disco, por
   `(tipo, quantidade, boletim_id)`, ASC NULLS FIRST. Exporta batches Arrow e
   restaura o schema original, inclusive UInt64, em um staging no filesystem do
   destino. Confere novamente linhas e soma dos votos antes de `os.replace`.
   Uma falha de processamento, sort ou auditoria não substitui o dump publicado.

A função privada `_process_data` continua disponível para fixtures e pequenas
consultas, com sua ordenação original. A execução real usa a transformação
sem sort por arquivo e a ordenação externa no final.

## Configuração

| Variável | Padrão | Escopo |
|---|---|---|
| `TURI_UNIQUE_TEMP_DIRECTORY` | `.turi_unique_tmp` | Partes intermediárias e spill em disco |
| `TURI_SORT_MEMORY_LIMIT` | `256MiB` | Pool do DataFusion para ordenação |
| `TURI_SORT_MAX_TEMP_DIRECTORY_SIZE` | `24G` | Limite de spill do runtime de ordenação |

`run_all_scripts` executa as operações diretamente, sem supervisor, teto global
de RAM/swap ou alteração automática de `POLARS_MAX_THREADS`. A supervisão global
de 6 GiB acrescentada na correção inicial foi retirada em 2026-10-28 por pedido
do usuário: o consumo da execução completa não deve ser limitado pelo orçamento
escolhido para um teste isolado.

Supervisão de recursos existe somente nas ferramentas de validação chamadas
explicitamente, com os parâmetros documentados abaixo. O pool DataFusion é
um orçamento local do motor, não um teto do RSS: há dimensões, buffers
Polars/Python/Arrow e metadados Parquet.

Os logs identificam início/fim de cada DataScript, arquivo de itens em execução,
contagens conferidas e início/fim do sort. Assim, `found N bulletin files` deixa
de ser a única informação para localizar a etapa.

## Testes e validação real

As fixtures executam o produtor real com dois layouts e tipos distintos, votos
duplicados, candidaturas ambíguas/ausentes e UInt64 acima de 2^63. Comparam todos
os campos/IDs com a transformação global anterior e preservam linhas/votos.
Há teste de falha de auditoria mantendo o destino, alocação real interrompida
pelo supervisor de validação, swap contabilizada separadamente e execução direta
do runner sem criar supervisor ou aplicar limites globais.

Validação repetível, com saídas exclusivamente temporárias:

```bash
PYTHONPATH=apps/turi/src:. POLARS_MAX_THREADS=2 uv run \
  -m scripts.maintenance.validate_bulletin_items \
  --all --report docs/audits/bulletin_items_full.json
```

Pode-se passar `--raw ARQUIVO` repetidamente para uma etapa menor. O padrão do
validador é 4 GiB de RAM+swap, 512 MiB de swap e timeout de 1.800 s; ajustes via
`--memory-mib`, `--swap-mib` e `--timeout`. Não executa o entrypoint amplo nem
atualiza metadados ou dumps finais.

Além das verificações do produtor, a ferramenta compara contagens e votos dos
brutos contra o final por localidade/cargo/tipo de voto, guarda partições brutas
por ano/UF/tipo de eleição/turno e verifica ordenação entre todos os batches.
Não prova a ausência de duplicação nas fontes originais nem equivale a comparar
todos os IDs/linhas com o produtor antigo sobre a carga inteira; a equivalência
de IDs e tipos é exercitada nas fixtures.

Relatórios desta sessão:

- [Piloto com dois arquivos](audits/bulletin_items_pilot_2026-10-27.json).
- [Falha inicial do sort sem compressão](audits/bulletin_items_uncompressed_failure_2026-10-27.json).
- [Carga completa e auditoria](audits/bulletin_items_full_2026-10-27.json).

A primeira tentativa completa conferiu 254.345.786 linhas elegíveis, mas o sort
sem compressão esgotou a quota de spill. Os temporários foram removidos e o
destino publicado permaneceu intacto. A correção usa compressão Zstd para reduzir
o custo dos arquivos de spill, incluindo passagens intermediárias do merge.

Validação final concluída sobre os 222 arquivos: 254.345.786 itens e
2.841.719.245 votos, conferidos em 39.370 grupos de localidade/cargo/tipo,
incluindo a ordenação global. Tempo total com auditorias: 334,836 s; pico RSS
3.931,7 MiB e swap zero, sob supervisão de 4 GiB/512 MiB. Saída temporária de
5.263.748.521 bytes removida ao terminar. Os 80 testes Turi passaram.

Esses números validam este produtor com a carga local completa, não todos os
outros scripts do entrypoint. O dump publicado antigo e os metadados dos scripts
não foram substituídos pelo validador.
