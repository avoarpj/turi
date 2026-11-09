*[Comentário original da equipe dos Dados Abertos da Câmara dos Deputados](https://github.com/CamaraDosDeputados/dados-abertos/issues/315#issuecomment-944548187)*

Olá, pessoal!

A classificação numérica dos tipos de despesas já está nos arquivos. São os campos `numSubCota` e `numEspecificacaoSubCota`. Talvez vocês não tenham visto [aqui mesmo, em outra issue](https://github.com/CamaraDosDeputados/dados-abertos/issues/106#issuecomment-332967520), uma tabela que descreve os campos dos arquivos, feita pela área responsável pelos dados ainda na época em que era ela a responsável pela publicação.

Os tipos de despesas cadastrados no momento, extraídos dos arquivos, são as seguintes:

| numSubCota | numEspecificacaoSubCota | txtDescricao | txtDescricaoEspecificacao |
|---|---|---|---|
| 1 | 0 | MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR |  |
| 2 | 0 | LOCOMOÇÃO, ALIMENTAÇÃO E  HOSPEDAGEM |  |
| 3 | 1 | COMBUSTÍVEIS E LUBRIFICANTES. | Veículos Automotores |
| 3 | 2 | COMBUSTÍVEIS E LUBRIFICANTES. | Embarcações |
| 3 | 3 | COMBUSTÍVEIS E LUBRIFICANTES. | Aeronaves |
| 3 | 4 | COMBUSTÍVEIS E LUBRIFICANTES. | Sem especificações |
| 4 | 0 | CONSULTORIAS, PESQUISAS E TRABALHOS TÉCNICOS. |  |
| 5 | 0 | DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR. |  |
| 6 | 0 | AQUISIÇÃO DE MATERIAL DE ESCRITÓRIO. |  |
| 7 | 0 | AQUISIÇÃO OU LOC. DE SOFTWARE | SERV. POSTAIS |
| 8 | 0 | SERVIÇO DE SEGURANÇA PRESTADO POR EMPRESA ESPECIALIZADA. |  |
| 9 | 0 | PASSAGEM AÉREA - REEMBOLSO |  |
| 10 | 0 | TELEFONIA |  |
| 11 | 0 | SERVIÇOS POSTAIS |  |
| 12 | 0 | ASSINATURA DE PUBLICAÇÕES |  |
| 13 | 0 | FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR |  |
| 14 | 0 | HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL. |  |
| 15 | 0 | LOCAÇÃO DE VEÍCULOS AUTOMOTORES OU FRETAMENTO DE EMBARCAÇÕES |  |
| 119 | 0 | LOCAÇÃO OU FRETAMENTO DE AERONAVES |  |
| 120 | 0 | LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES |  |
| 121 | 0 | LOCAÇÃO OU FRETAMENTO DE EMBARCAÇÕES |  |
| 122 | 0 | SERVIÇO DE TÁXI, PEDÁGIO E ESTACIONAMENTO |  |
| 123 | 0 | PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS |  |
| 137 | 0 | PARTICIPAÇÃO EM CURSO, PALESTRA OU EVENTO SIMILAR |  |
| 998 | 0 | PASSAGEM AÉREA - SIGEPA |  |
| 999 | 0 | PASSAGEM AÉREA - RPA |  |

Até o momento, os arquivos para download dos dados sobre uso da "Cota Parlamentar" mantêm basicamente a mesma estrutura desde quando começaram a ser publicados (2011, salvo engano), com apenas as seguintes diferenças:

* há cinco formatos na versão mais nova, todos em UTF-8. Os arquivos antigos, só XML em UTF-16.
* agora os arquivos são divididos por ano das despesas. Antes, havia um arquivo "AnoAtual.zip" e um arquivo "AnosAnteriores.zip" de uns 130 MB que se expandia para mais ou menos 4,5 GB.

Essa estrutura ainda é definida pela própria tabela de banco de onde vêm os dados, que é mantida pela área responsável pelo sistema de registro das despesas parlamentares. Apenas para a API o serviço de Dados Abertos faz alguns ajustes, para publicação pelo endpoint `/deputados/{id}/despesas`. Os arquivos realmente não seguem bem os padrões adotados pelo Dados Abertos para a API e para os demais arquivos. Mas a estrutura não foi alterada para permitir que os usuários dos arquivos antigos pudessem adotar os novos mais facilmente, e também porque temos priorizado a publicação das informações sobre as atividades legislativas propriamente ditas. 

Também por esta segunda razão ainda não criamos arquivos ou um endpoint da API que enumere os tipos de despesas e seus códigos. Não há uma tabela com esses dados na base a que temos acesso. Há pouco tempo passamos a ter uma base de dados própria para pequenos trabalhos de ETL, e esta tabela de referência é uma boa ideia para implementarmos em algum futuro breve.

Abraços!

Fabricio Rocha
Equipe Dados Abertos - Câmara