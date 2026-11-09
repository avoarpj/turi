# BrazilGEO - Assets geojson do mapa do Brasil

Gera as camadas para um mapa com carregamento progressivo: o país contém apenas
estados/DF; cada arquivo estadual contém as geometrias municipais originais.
A fonte única é a [malha municipal IBGE 2025](https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_Municipios_2025.zip).

## Execução

Na raiz do repositório:

```bash
uv sync --locked
uv run python -m apps.scripts.brazilgeo.generate
```

O script importa `Downloader` de
`apps.turi.src.infra.downloader.downloader`; o import usa as configurações e o
`.env` do Turi. Não executa os entrypoints de downloads ou dumps.

**A geração completa apaga integralmente `assets/brazilgeo/` antes do download.**
Essa pasta deve conter exclusivamente os mapas gerados. O downloader baixa o ZIP
novamente, extrai o shapefile e seus arquivos auxiliares com `keep_raw=True` e
guarda o bruto em `downloads/ibge/brazilgeo/` (sob o `BASE_DIR` do Turi).
O ZIP temporário é removido. Falhas de download ou validação interrompem o script.

Para acrescentar somente os índices de navegação aos GeoJSONs já existentes,
sem apagar mapas ou baixar a fonte novamente:

```bash
uv run python -m apps.scripts.brazilgeo.generate --bounds-only
```

Esse modo lê uma UF por vez e escreve apenas `states/<UF>.bounds.json`, usando
o `bbox` original de cada feição. A geração completa também produz esses índices.

GeoPandas/Pyogrio lê o shapefile; o script exige CRS, IDs únicos, os campos de
identificação e as 27 UFs. Geometrias ausentes, vazias ou inválidas causam erro.
Os arquivos municipais preservam todos os vértices, ilhas e buracos, com apenas
a transformação SIRGAS 2000 → WGS84 para uso no navegador.

O país é obtido dissolvendo os municípios por UF. Para ficar leve, essa camada
é simplificada em conjunto, em projeção métrica `EPSG:5880`, com tolerância de
1.000 m. A simplificação conjunta preserva as fronteiras compartilhadas entre
estados. Antes dela, se necessário, `shapely.coverage_clean` normaliza a topologia
estadual com snap de 1 cm e sem preencher lacunas. Isso afeta somente a camada
nacional. A malha original de 2025 tem arestas sem correspondência exata; a
normalização medida nesta execução alterou cerca de 75,3 m² no conjunto das UFs,
antes da simplificação.

Para mudar a tolerância (zero desativa simplificação e normalização):

```bash
uv run python -m apps.scripts.brazilgeo.generate --states-simplification-meters 500
```

## Arquivos e contrato do frontend

```text
assets/brazilgeo/
├── BR.geojson
└── states/
    ├── AC.geojson
    ├── AC.bounds.json
    ├── AL.geojson
    ├── AL.bounds.json
    ├── ...
    └── TO.geojson
```

São 28 GeoJSONs, todos `FeatureCollection`, em WGS84 (`EPSG:4326`), com
coordenadas `[longitude, latitude]` e orientação dos anéis conforme RFC 7946.
Cada coleção e feição possui `bbox` na ordem
`[oeste, sul, leste, norte]`. Códigos IBGE permanecem **strings**.

Os 27 arquivos `states/<UF>.bounds.json` são índices pequenos no formato
`{"codigo_ibge":[oeste,sul,leste,norte]}`. A lista de votos usa esses limites para
navegar diretamente até um município, mesmo fora do viewport, sem ler a malha
completa na thread principal. Os índices referenciam os limites exatos das
feições originais. A malha continua por URL direta ao worker. A UF clicada tem
prioridade dentro do limite de estados residentes do mapa.

Backfill local de 2026-10-29: 27 índices, 5.573 feições e 395.363 bytes no total.
SHA-256 dos 28 GeoJSONs antes/depois permaneceu igual; nenhum novo download.

Propriedades das 27 feições de `BR.geojson`:

| Campo | Exemplo | Uso |
|---|---|---|
| `Feature.id` e `properties.uf` | `"SP"` | Identificador da UF |
| `codigo_uf` | `"35"` | Código IBGE estadual |
| `nome` | `"São Paulo"` | Nome da UF |
| `municipios_url` | `"states/SP.geojson"` | Caminho relativo a `assets/brazilgeo/` |
| `municipios_bbox` | `[oeste, sul, leste, norte]` | Extensão original dos municípios, para seleção pelo viewport |

Use `municipios_bbox` para decidir quais arquivos estaduais carregar: a caixa
abrange o detalhe original mesmo se a simplificação mudar a extensão do desenho
nacional. `bbox` descreve a geometria efetivamente desenhada em cada feição.

Propriedades das feições de `states/<UF>.geojson`:

| Campo | Exemplo |
|---|---|
| `Feature.id` e `properties.codigo_ibge` | `"3550308"` |
| `nome` | `"São Paulo"` |
| `uf` | `"SP"` |
| `codigo_uf` | `"35"` |
| `nome_uf` | `"São Paulo"` |

`codigo_ibge` vem diretamente de `CD_MUN` do shapefile e corresponde à chave
municipal do Avoar; não é necessário cruzar nomes com os brutos do Turi.
A coleção preserva as **5.573 feições** da fonte, incluindo Brasília, Fernando
de Noronha e duas áreas operacionais do RS: `4300001` (Lagoa Mirim) e `4300002`
(Lagoa dos Patos). Essas áreas operacionais não são municípios; ausência de
dados eleitorais para elas deve permanecer ausência, sem inferir zero votos.
A malha de 2025 também não garante correspondência administrativa com toda
eleição histórica.

## Transferência HTTP comprimida

O Fons já aplica `CompressionConfig` também ao router estático `/assets`,
incluindo os GeoJSONs municipais em streaming. Usa Brotli com qualidade 4,
modo texto, tamanho mínimo de 500 bytes e fallback gzip nível 6. O fallback
está explícito em `apps/fons/main.py`.

O MapLibre recebe a URL normal `assets/brazilgeo/states/<UF>.geojson` e seu
worker usa o Fetch do navegador. A negociação e a descompressão são automáticas:
o navegador anuncia os formatos que aceita, e o servidor responde com
`Content-Encoding: br` ou `gzip`. `Accept-Encoding` é um cabeçalho controlado
pelo navegador, [não pode ser definido pelo JavaScript](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Accept-Encoding),
mesmo usando os [headers de transformRequest do MapLibre](https://maplibre.org/maplibre-gl-js/docs/API/type-aliases/RequestParameters/).
Não é necessário trocar a URL para `.br`/`.gz` nem descomprimir na aplicação.

Em 2026-10-25, a auditoria confirmou que a compressão já estava ativa. Identificou
também que o CORS da versão instalada do Litestar substituía o `Vary` de
compressão por `Origin`. O hook `before_send` agora preserva os valores presentes
e acrescenta `Accept-Encoding` às respostas GET/HEAD, incluindo a representação
sem compressão. Assim respostas cross-origin informam
`Vary: Origin, Accept-Encoding`. Reiniciar Fons após essa correção.

Medição dos bytes do corpo pelo app real via ASGI, com arquivos locais:

| UF | Original | Brotli | gzip |
|---|---:|---:|---:|
| DF | 302.537 B | 81.125 B (−73,19%) | 78.733 B (−73,98%) |
| SP | 39.758.077 B | 11.588.493 B (−70,85%) | 10.614.347 B (−73,30%) |

As respostas descomprimidas foram comparadas byte a byte com os arquivos.
No Chromium, o worker MapLibre real carregou DF e SP anunciando
`gzip, deflate, br, zstd` e recebendo Brotli, sem headers manuais no frontend.
As fontes ficaram prontas em 0,238 s e 1,734 s no teste local; isso inclui
inicialização do mapa, download e processamento no worker. Não é benchmark
controlado de antes/depois nem simulação de rede lenta. Compressão reduz os
bytes transferidos; o JSON e a geometria completos ainda precisam ser processados.
Arquivos de saída e geometrias continuam os mesmos.

Configuração, hashes, bytes e medições estão no
[relatório HTTP](../../../docs/audits/geojson_http_compression_2026-10-25.json).
`tests/test_fons_static_compression.py` usa o app real com fixtures pequenas e
maiores que 1 MiB para conferir streaming, Brotli, fallback gzip, identity,
integridade do conteúdo e `Vary` com/sem CORS.

## Verificação

```bash
uv run python -m unittest discover -s tests -p test_brazilgeo.py -v
```

Os testes passam um ZIP com shapefile pelo downloader real, simulando somente o
HTTP. Verificam a limpeza restrita ao diretório de mapas, os 28 arquivos,
identificadores, acentos, preservação das geometrias municipais (incluindo ilhas
e buracos), normalização estadual e interrupção em falhas de download.

Na execução de 2026-10-22, `BR.geojson` ficou com 1,03 MiB e o conjunto completo
com aproximadamente 601 MiB. Os detalhes permanecem grandes: MG tem 80 MiB,
AM 72,5 MiB e SC 69,6 MiB, pois não são simplificados. A auditoria comparou todas
as 5.573 feições com o shapefile, conferindo igualdade exata das geometrias
reprojetadas (desconsiderando orientação/ordem de anéis) e dos metadados
exportados, além da cobertura válida da camada nacional. Contagens e tamanhos
por UF estão no [relatório da execução](../../../docs/audits/brazilgeo_2026-10-22.json).
