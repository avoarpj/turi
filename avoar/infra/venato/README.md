# 👋 Olá!

Venato é um motor de pesquisa baseado em `tantivy` e `tantivy-py`.

## Estado atual de atendimento e concorrência (2026-11-07)

O Venato é uma biblioteca embutida no processo Fons. As buscas rodam em threads,
mas ainda coletam todos os hits/IDs da expressão antes da paginação da API.
O limite de resultados HTTP não limita esse custo nem isola CPU/memória das
demais rotas. Não há uma versão servidor implementada neste repositório.

O [relatório de concorrência e proposta de servidor](../../../docs/venato_server.md)
registra a análise do código, medições com o app real, limites da evidência e
alternativas de admissão/processo separado, preservando Parquet e os YAMLs.
O recorte proposto pelo usuário é um servidor de consulta sobre índices existentes,
sem ingestão, com QUIC e Arrow IPC. Essa versão ainda não está implementada.

## Proposta de armazenamento

A grande maioria dos motores de pesquisa modernos (ElasticSearch, MeiliSearch, LanceDB com FTS) são feitos para serem seu banco de dados principal.<br>
Em ambientes com quantidades ultra-massiva de dados (casa dos bilhões), isso só é aceitável quando você tem terabytes em disco.

Formatos colunares se tornaram populares para lidar com esse tipo de workload, mas nenhuma solução de pesquisa sabe tirar proveito.<br>
O Venato trás uma proposta diferente: seus dados colunares **nunca** deveriam sair do lugar para acomodar um search engine.

## Porque simplesmente não usar Tantivy?
O Tantivy é uma biblioteca de baixo nível. Você gerencia, você desenvolve, você precisa controlar.

Usando diretamente as bibliotecas que movem os gigantes (Apache Lucene e Tantivy), você não tem abstração nenhuma. Precisa de scripts para criar, armazenar e gerenciar os dados para serem pesquisados.

Venato te dá agilidade ao desenvolver cuidando de tudo isso para você, enquanto você implementa no seu projeto igual qualquer outro cliente, e ainda não explode seu armazenamento duplicando seus dados. Só precisa de arquivos `.parquet` e um schema.

A comodidade dos motores de pesquisa modernos é você não precisar mexer em quase nada do seu código. Defina seus schemas em arquivos yaml, json ou permita que seja inferido automaticamente. Com isso vem o pedágio invisível: seu motor de pesquisa vira uma versão em miniatura do seu banco de dados. Difícil e caro de manter.

## Em quais workloads o Venato se encaixa?
Primeiramente, Python (versões futuras podem ser portadas para outra linguagem para permitir bindings).

Segundamente; Quando você tem muitos, muitos dados colunares e não pode ou não quer explodir o uso de armazenamento transferindo-os para um motor de pesquisa convencional.

