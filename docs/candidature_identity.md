# Candidaturas e votos nominais

`scripts.bricks.candidature_identity.candidature_id_expr()` calcula o hash
Polars com `NUMERIC_HASH_SEED` do seguinte struct, nesta ordem:

| Campo | Tipo Polars | Significado |
|---|---|---|
| `eleicao_id` | `UInt64` | Eleição do Avoar |
| `codigo_local` | `String` | `BR`, UF ou código IBGE do município |
| `codigo_cargo_tse` | `Int32` | Código original do cargo no TSE |
| `numero_candidato` | `Int32` | Número digitado na urna |

Os nomes, tipos, ordem dos campos, seed e versão do Polars devem ser os mesmos
nos datasets que recalculam a chave. Este hash não é um identificador portátil
entre implementações ou versões arbitrárias do Polars.

O cargo faz parte da chave: titulares, vices e suplentes podem compartilhar
o número. `codigo_cargo_tse` não é o enum de cargos do domínio do Avoar.

A localidade municipal é obtida pela correspondência
`CD_MUNICIPIO_TSE → CD_MUNICIPIO_IBGE`. Códigos TSE são normalizados como
inteiros para aceitar valores com ou sem zeros à esquerda. A ausência de uma
correspondência municipal não elimina votos nacionais ou estaduais.
Conselheiro distrital (cargo TSE `25`) também usa a localidade convertida pelo
mapa de municípios.

O mapa municipal é materializado e validado separadamente, antes do join com
candidaturas/votos. Chaves TSE não nulas duplicadas com destinos distintos
continuam falhando. Isto mantém m:1 sem o fallback em memória de `validate` no
Polars 1.38. Nos itens, as demais dimensões também são preparadas uma vez;
o schema global das fontes é preservado antes de gerar IDs por arquivo.
Detalhes operacionais em [turi_bulletin_items.md](turi_bulletin_items.md).

A eleição é resolvida por `(codigo_tse, codigo_local)` usando os dumps de
eleições e turnos. Um dicionário indexado somente por `codigo_tse` perde as
demais localidades. Esta mudança mantém a definição existente de `eleicao_id`,
inclusive sua dependência de `CD_ELEICAO`.

## Ambiguidade

Para chaves associadas a uma única `pessoa_publica_id`, o hash acima é o `id`
da candidatura. Registros repetidos da mesma pessoa e chave são deduplicados.
`SQ_CANDIDATO` não participa dessa identidade.

## Fotos das candidaturas

Na geração das candidaturas, o Turi associa cada ID aos campos brutos
`ANO_ELEICAO`, `SG_UF` e `SQ_CANDIDATO`. A combinação localiza a imagem no
diretório extraído `downloads/tse/candidatures_photos/foto_cand<ano>_<UF>_div_*`.
O nome da imagem usa `F<UF><SQ_CANDIDATO>_div` e extensão JPEG ou PNG.
O sequencial do TSE não é usado como ID global e o schema do parquet de
candidaturas continua sem esses campos auxiliares.

Uma foto só é publicada quando os registros brutos da candidatura concordam
quanto à chave da foto e há um único arquivo correspondente. A imagem é movida
para `assets/candidatures/<candidatura_id>.<extensão>` com `Path.replace`, que
substitui atomicamente um arquivo de mesmo nome no mesmo filesystem. Se a
extensão mudar, as variantes antigas são removidas após a publicação da nova.
Fotos sem candidatura nos parquets locais e associações ambíguas permanecem
na pasta de download. Reexecutar o script preserva as imagens já publicadas
quando os arquivos de origem foram movidos.

Na auditoria local de 2026-10-02, antes de mover arquivos, os parquets de
2018, 2020 e 2022 tinham 615.615 candidaturas: 614.068 tinham uma imagem
correspondente, 834 apresentavam mais de uma chave de foto nos registros
brutos e 371 chaves sem imagem correspondente. São contagens dessa carga,
não invariantes para outras versões dos dados.

Se a chave estiver associada a pessoas distintas, todas as candidaturas são
preservadas. Seus IDs passam a ser o hash do struct
`(_chave_candidatura: UInt64, pessoa_publica_id: UInt64)`, com o mesmo seed.
Nesses casos, apenas o número e a localidade não bastam para atribuir votos:
o item de boletim recebe `candidatura_id = null`.

Essa política depende do conjunto de candidaturas disponível: se uma carga
posterior revelar outra pessoa para uma chave antes única, os IDs desse grupo
mudam. Candidaturas e itens de boletim precisam ser regenerados juntos.

## Itens de boletim

Os itens expõem `eleicao_id`, `turno_eleicao_id`, `codigo_local`, `codigo_cargo_tse` e
`candidatura_id`. A referência à candidatura só é preenchida para votos
nominais com correspondência única no dump de candidaturas. Votos de legenda,
brancos, nulos, anulados, chaves ausentes e chaves ambíguas ficam sem referência.
O item e a quantidade de votos são preservados em todos esses casos.

O turno pertence ao item, não ao boletim: um único boletim físico pode conter
itens de várias eleições. `election_round_id_expr()` calcula a referência com
o struct `(eleicao_id: UInt64, numero_turno: Int32)`; o script de eleições usa
a mesma expressão para gerar o ID do turno. Sem eleição resolvida, a referência
ao turno também é nula. O boletim mantém sua identidade física e não depende
de um join com o mapa de municípios para ser preservado.

`tipo` usa diretamente `TipoItemBoletim` do domínio: nominal `1`, legenda `2`,
branco `3`, nulo `4`, anulado `5` e anulado judicialmente `6`. Dumps anteriores
à correção usavam outra numeração e precisam ser regenerados.

## Regeneração

Antes de concatenar boletins de anos diferentes, `normalize_tse_bulletin`
normaliza os cabeçalhos históricos `SG_ UF` e `CD_FLASCARD_URNA_EFETIVADA`.
Quando `CD_TIPO_ELEICAO` não existe, reconhece o tipo por descrições conhecidas
em `DS_ELEICAO`; descrições desconhecidas permanecem sem classificação.
Os scripts de eleições, boletins e itens usam essa mesma normalização.
Isso evita descartar eleições de 2018 apenas por diferenças no layout.

Após disponibilizar os arquivos brutos e o mapa de municípios do TSE:

1. Gerar eleições e turnos.
2. Gerar candidaturas.
3. Gerar boletins e itens de boletim.
4. Publicar os novos parquets e reiniciar a sessão DataFusion. O campo `turno_eleicao_id` deixa
   de existir na tabela de boletins e passa para a tabela de itens.

Os IDs de candidaturas mudam em relação ao formato anterior. Consumidores
devem atualizar suas referências. A geração dos IDs de itens de boletim
continua usando os campos anteriores à inclusão das novas referências.

Testes locais:

```bash
PYTHONPATH=apps/turi/src:. .venv/bin/python -m unittest discover -s apps/turi/tests -v
```

## Agrupamento por Pleito

`Eleicao.pleito_id` agrupa eleições de várias localidades em um evento geral.
Esse campo não participa do hash da eleição nem da candidatura: os vínculos
existentes permanecem estáveis. A geração e a regeneração estão descritas em
[pleito.md](pleito.md).
