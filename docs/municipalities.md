# Panorama e detalhes municipais

Atualização de infraestrutura (2026-10-14): as consultas da API agora executam
em DataFusion sobre Parquet direto, preservando os contratos deste documento.
Referências a DuckDB e medições anteriores são históricas. A suíte atual usa
DataFusion para produzir e consultar fixtures Arrow e inclui integração
com arquivos Parquet. Não há transação de snapshot entre datasets. Veja
[datafusion_resources.md](datafusion_resources.md).

## Contrato e apresentação

`GET /opendata/municipality/panorama` retorna os municípios cadastrados com
quantidade de emendas distintas e valor pago + RAP pago dos recursos destinados
explicitamente a cada código IBGE. É um panorama completo (cerca de 5,6 mil
cadastros), não uma listagem keyset paginada. Recursos com destino UF/BR não são
rateados entre cidades. Não depende de autorias ou vínculos eleitorais.

`GET /opendata/municipality/{ibge_id}/exploration` (também disponível no GET
original sem esse sufixo) mantém emendas por ano e item e acrescenta
`totais`, `autores` e `votos`. Todas as agregações financeiras consideram o período
completo disponível. `valor_pago` em totais/autores/panorama significa pago + RAP
pago; nas séries financeiras, esses componentes continuam separados. Isso não
é toda a receita municipal e não comprova crédito direto à prefeitura.

Autores são top 10 por pessoa, deduplicando pares emenda/pessoa, inclusive entre
mandatos dessa pessoa. Autoria compartilhada recebe valor integral sem rateio;
autoria sem mandato resolvido fica no total, mas não no ranking. Não somar os
autores para obter o total municipal. Categorias são funções do orçamento,
sem inferir objeto ou modalidade de transferência a partir do código da função.

Rostra usa `/municipios` e `/municipios/[codigo_ibge]`, menu ativo, bandeiras pelo
resolver de localidades, busca por nome sem acentos ou código, filtro de UF,
ordenação por recursos pagos e páginas locais de 24 cartões. O panorama completo
fica no cache; não há OFFSET no DataFusion. URLs preservam filtros e página. Detalhes
apresentam totais, evolução anual, funções, autores e votação por casa, com links
internos para pessoas/mandatos e Portrait nas candidaturas. SSR/TanStack/proxy
restrito mantêm o fluxo de cache Redis somente leitura do Rostra.

Desde 2026-10-15, os rankings de autores e de votos agrupam nome, número do
candidato e logo do partido na mesma linha, seguindo a homepage. `CandidateName`
usa o logo em 20 × 15, priorizando `_typo.svg`; sem candidatura mantém só o nome.
No ranking de votos, `numero_candidato` e `sigla_partido` vêm exatamente da
candidatura que recebeu os votos, mesmo quando há uma candidatura mais recente.

Autores financeiros recebem `candidatura_recente` opcional, pelo mesmo critério
do ranking de empresas: ano eleitoral, última data de turno e ID decrescentes.
A resolução é em lote após selecionar o top 10, sem mudar totais, atribuições
ou ordenação. Candidatura ausente não exclui o autor. Esses metadados não indicam
filiação atual nem necessariamente a candidatura do período financeiro.
Reinicie Fons para usar a projeção nova; respostas já em cache podem manter o
contrato anterior até expirar. Não é necessário regenerar os Parquets.

## Votos e geografia dos boletins

`codigo_local` nos itens é a circunscrição eleitoral, que pode ser UF ou BR.
Não usá-lo como município onde o voto foi dado. `BoletimUrna` agora preserva
`codigo_municipio_ibge`, a partir de CD_MUNICIPIO no bruto e do mapa TSE/IBGE.
O ID físico do boletim e os IDs/votos de seus itens permanecem intactos.
Ambiguidade de município para um mesmo ID físico produz null.

Rankings usam votos nominais (tipo 1), primeiro turno, eleição ordinária mais
recente com registros municipais para cada casa e só candidaturas com mandato
vinculado. Não são rankings de todos os candidatos nem prova de mandato atual.
O adaptador histórico grava eleições ordinárias como tipo 0 e cargos baseados
em enum antigo; o filtro legislativo usa os códigos TSE 5/6/7/13/25 dos itens.
Não aplicar os códigos 1-based do enum CargoEleicao aos dados históricos.

Cada casa informa seu próprio ano: cobertura parcial pode levar a 2018 para uma
casa e 2022 para outra. A ausência de vínculos/cobertura não deve virar zero votos.
Sem coluna municipal, o query service tenta o dump colunar enriquecido; se ambos
estão antigos, devolve `disponivel=false` sem reinterpretar votos estaduais.
O fallback por Parquet permite usar uma nova projeção em sessões antigas.
Após publicar o dump, reinicie Fons para registrar o schema atualizado em DataFusion.

## Evidência local de 2026-10-09

Enriquecidos somente os boletins físicos: 1.356.060 linhas, nenhuma alteração de
campos anteriores, 1.354.310 com município unívoco e 5.570 códigos municipais.
Seis IDs têm localidades conflitantes no bruto e ficaram null; outras 1.744
linhas não têm correspondência municipal. O arquivo de itens (2,1 GB) não foi
reescrito. O banco estava aberto com lock de leitura e não foi modificado;
o dump enriquecido publicado atende ao fallback. Reiniciar Fons para o código
novo; a próxima sincronização normal incorpora a coluna no banco.

Panorama real: 5.573 cadastros, 0,04 s; finanças de São Paulo: 328 emendas,
R$ 267.386.486,65 pagos + RAP e 10 autores, 0,16 s. Ranking municipal de São Paulo:
20 registros em duas casas, 1,92 s. Medidos diretamente no DuckDB com limites da
API e duas threads; não são metas de desempenho nem comprovação de cobertura.

Testes usam core real/DataFusion e HTTP: ausência 404, formatos de retorno, caminhos
rápidos, duplicações de autoria, destino estadual excluído, voto de outra cidade,
legenda/segundo turno excluídos, ano e fallback Parquet. Turi verifica que adicionar
a geografia não muda o ID, inclusive para cargos nacionais/estaduais e município
não mapeado. Check/build/test do Rostra e testes da API/Turi completam a validação.
Aparência e interações no navegador não foram verificadas neste ambiente.

O Rostra usa o sufixo exploration para evitar hidratar o contrato novo a partir
de uma resposta antiga em cache do endpoint original.
