# Mandato e candidatura

O mandato expõe `candidatura_id` nullable.
A associação é calculada pelo Turi e persistida no parquet, preservando o ID
original do mandato.

O componente compartilhado `link_mandate_candidatures` não restringe casas,
cargos ou anos eleitorais. Cada fonte fornece um contexto com:

| Campo | Significado |
|---|---|
| `mandato_id` | Mandato ao qual o contexto se aplica |
| `ano_eleicao` | Ano da eleição de origem |
| `codigo_cargo_tse` | Cargo disputado |
| `tipo_eleicao` | Tipo na codificação do ETL de eleições |
| `codigo_local` | Circunscrição; nulo se a fonte não a determina |

O resolvedor exige a mesma `pessoa_publica_id`, ano, cargo e tipo de eleição.
Quando o contexto informa localidade, ela também deve coincidir. Contextos
repetidos não multiplicam mandatos. Várias candidaturas distintas compatíveis
resultam em referência nula, mesmo que tenham votações diferentes.

Sem contexto suficiente, sem correspondência ou com correspondência ambígua,
`candidatura_id` permanece nulo.

## Contexto da Câmara dos Deputados

O adaptador `operations/mandates/camaradosdeputados.py` usa a legislatura para
obter o ano anterior ao seu início, o cargo TSE `6` e eleição ordinária.
A data de entrada em exercício não participa: a posse posterior de um suplente
não muda a eleição de origem. A fonte atual não informa a circunscrição nesse
fluxo; candidaturas compatíveis em mais de uma localidade permanecem ambíguas.

Essa regra pertence ao adaptador da Câmara. Outras fontes devem fornecer seu
próprio contexto, inclusive eleições de anos anteriores, circunscrições e
eleições suplementares, sem modificar o resolvedor.

O ETL existente codifica eleição ordinária como `ElectionType.ORDINARIA = 0`;
o enum de domínio possui outra numeração. O adaptador usa o enum do ETL para
comparar com os dados efetivamente gerados. Uma futura migração dessa codificação
precisa atualizar os dumps e os produtores de contexto juntos.

## Dependências e uso

Gerar identificadores de pessoas, legislaturas, eleições e candidaturas antes
dos mandatos. 

A listagem e a busca de pessoas públicas incluem o vínculo nos mandatos
retornados. A referência identifica a candidatura de origem; não certifica
eleição como titular nem a completude dos votos disponíveis. Somar votos exige
selecionar o turno correspondente nos itens de boletim. Ausência de registros
de voto não deve ser convertida automaticamente em zero.

O endpoint de [votos municipais da candidatura](candidature_votes_map.md) usa
essa referência exata e separa os turnos. O detalhe do mandato no Rostra mostra
o mapa da UF na aba Candidatura, com valores abreviados e lista de totais exatos.
