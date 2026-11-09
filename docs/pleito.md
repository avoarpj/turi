# Pleito e eleições

## Estado atual

`Pleito`, em `avoar/core/opendata/pleito/domain.py`, representa um evento geral
compartilhado por várias localidades. Por exemplo, as eleições municipais de
2024 compõem um único Pleito, com as disputas de cada município e seus turnos.
Nas eleições gerais, disputas nacionais e estaduais também compartilham o evento.

Campos: `id`, `ano`, `tipo` (`TipoEleicao`) e `data_inicio` (data do primeiro turno).
O Pleito não tem `codigo_local`: a circunscrição continua em `Eleicao`, que agora
exige `pleito_id`. As localidades participantes podem ser obtidas pelas eleições
vinculadas; não foi criada uma tabela adicional de participação.

## Geração no Turi

`ElectionsDataScript.process_data` gera três conjuntos:

- `opendata_pleito/opendata_pleito.parquet`;
- `opendata_election/opendata_election.parquet`, incluindo `pleito_id`;
- `opendata_election_round/opendata_election_round.parquet`.

O helper `scripts/bricks/pleito_identity.py` extrai os metadados dos boletins.
A identidade do Pleito é o hash, com o seed configurado, de `ano` (`Int32`),
`tipo` (`Int32`) e `data_inicio` (`Date`), nessa ordem. Não depende de município,
UF, cargo ou código TSE do turno. O `CD_PLEITO` bruto não é usado como ID porque
pode mudar entre primeiro e segundo turno.

Os turnos ordinários de uma localidade/ano usam a data de seu primeiro turno.
Nos suplementares, cada data de primeiro turno distingue um evento; um segundo
turno usa o primeiro turno anterior mais recente daquela localidade/ano.
Eventos na mesma data e do mesmo tipo compartilham o Pleito entre localidades.
Esse agrupamento é uma convenção do conjunto atual, sem um catálogo externo de
eventos: suplementares independentes coincidentes são agrupados por data. Se
houver eventos intercalados na mesma localidade, a associação dos turnos precisará
de um identificador explícito da fonte.

Datas inválidas, tipos desconhecidos, turnos sem primeiro turno e mais de um
primeiro turno ordinário na mesma localidade/ano interrompem a geração. Também
se verifica que cada ID de eleição referencia exatamente um Pleito, antes de
escrever os arquivos. As identidades anteriores de eleições e turnos permanecem
iguais, preservando os vínculos de candidaturas e boletins.

O Pleito usa os valores do enum do core: ordinária `1`, suplementar `2`.
A coluna `tipo` das eleições conserva a codificação histórica do ETL (`0`/`1`);
esta alteração não migra essa divergência preexistente.

## Catálogo HTTP e filtro do mapa (2026-10-22)

`GET /opendata/pleito` retorna `id` como string, `ano`, `tipo` e `data_inicio`
ISO (`YYYY-MM-DD`). O catálogo lê `opendata_pleito` diretamente em DataFusion,
sem varrer boletins ou calcular totais eleitorais. O core registra query service,
caso de uso e controller reais. `JSON_STRING`/`DICT` não validam modelos;
`MODEL_PARSED` valida `Pleito`.

Usa keyset por `id`: `limit=1..1000` (padrão 1000), `order=asc|desc`,
`pull_by=id` e `pull_after` uint64 exclusivo. A ordenação é numérica antes da
serialização dos IDs; ordem de ID não significa cronologia. Filtros/cursor inválidos
retornam 400 e catálogo vazio retorna `[]`.

```text
/opendata/pleito?limit=1000&order=asc&pull_by=id
/opendata/pleito?limit=1000&order=asc&pull_by=id&pull_after=2637794076754536956
```

O Rostra percorre todas as páginas e apresenta os pleitos por data decrescente,
com ano, tipo e data. A seleção múltipla em `/partidos` usa os mesmos IDs como
`pleito_id` repetido na URL e em ambas as consultas de força partidária.
IDs permanecem strings no navegador, incluindo valores maiores que 2^63.

Desde 2026-10-28, o filtro de turno fica separado da eleição. Na guinada, o
catálogo de bases é agrupado por `pleito_id` dentro do cargo/circunscrição antes
de apresentar os turnos. Não usar `eleicao_id` para esse agrupamento: os dados
atuais podem atribuir IDs de eleição diferentes aos dois turnos do mesmo pleito.
Na força partidária, `numero_turno=1|2` aplica-se aos pleitos selecionados e é
opcional; sua ausência preserva todos os turnos.

Testes: `tests/test_pleitos_api.py` usa lifespan/app/core reais, verifica paginação
ascendente/descendente, cursor extremo, SQL inválida, OpenAPI e os três formatos.
O Parquet local atual já contém a tabela; basta reiniciar Fons para registrar a rota.

## Regeneração e verificação

Executar o script `elections` pelo fluxo do Turi e reiniciar a sessão DataFusion.
O cliente registra automaticamente a pasta `opendata_pleito`; não exige registro
manual da tabela nem materialização de banco. Não é necessário regenerar candidaturas/boletins por causa desta
coluna, pois os IDs das eleições não foram alterados. Consumidores de `Eleicao`
precisam usar o parquet regenerado para obter o campo obrigatório `pleito_id`.

A implementação foi validada com geração real dos três parquets em diretório
temporário e fixtures de localidades, turnos e suplementares. Os testes conferem
integridade dos vínculos e preservação dos IDs. O conjunto completo de boletins
locais não foi regenerado nem auditado nesta mudança.

```bash
PYTHONPATH=apps/turi/src:. POLARS_MAX_THREADS=2 .venv/bin/python -m unittest discover -s apps/turi/tests -p test_pleitos.py -v
```
