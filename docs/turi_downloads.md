# Downloads Turi

## Ambiente e execução

O pacote Python do Playwright e o executável do Chromium são instalações
separadas. Depois de sincronizar ou atualizar o ambiente, instale a revisão do
navegador exigida pela versão atual do Playwright, a partir da raiz:

```bash
uv sync
uv run playwright install chromium
```

Para executar os downloads, dentro de `apps/turi`:

```bash
uv run python src/download_all.py
```

`BrowserType.launch: Executable doesn't exist` indica ausência do navegador
esperado pelo pacote instalado. `playwright_headless=False` apenas torna a janela
visível; não instala o executável.

## Cookie do catálogo CKAN do TSE

Configure `TSE_CKAN_COOKIE` no ambiente ou no `.env` da raiz com o conteúdo
completo do header `Cookie`. Quando ausente, vazio ou contendo apenas espaços,
o header não é enviado na configuração inicial da sessão CKAN. Não há cookie
fixo nem fallback no código. A configuração é lida ao importar o downloader;
reinicie o processo após alterá-la.

## Seleção de transporte e cache

O `Downloader` consulta o metadado antes de resolver URLs dinâmicas ou abrir o
Playwright. Metadados recentes, bem-sucedidos e com arquivos existentes retornam
o cache. Retentativas usam `failed_sources`. Alterar anos ou URLs configurados não
invalida automaticamente o cache existente.

Na configuração de 2026-10-27, candidatos, boletins, municípios e diretórios
partidários usam `driver_mode="playwright"`; fotos e locais de votação usam
HTTP direto. O entrypoint seleciona quais downloads são executados: chamadas
comentadas não abrem navegador.

Os boletins descobrem recursos no catálogo CKAN via `curl_cffi` antes de baixar
arquivos. `driver_mode="playwright"` se aplica ao download dos arquivos e não
transfere a consulta CKAN para o navegador. Uma falha de catálogo ocorre antes da
janela; aumentar opções de download do Playwright não resolve essa etapa.
Anos cujo pacote retorna `NotFound` são registrados e ignorados; outros erros
interrompem a descoberta. Uma lista final vazia também é erro.

## Diagnóstico e validação

Os logs distinguem cache (`Using cached files`), descoberta (`Resolving dynamic
sources`) e abertura (`Starting Playwright Chromium`). Falhas no pool registram
a URL e o erro. O entrypoint interrompe a execução se houver falhas nos downloads
ativos de locais de votação, boletins ou candidatos.

Na investigação de 2026-10-27, a revisão Chromium 1234 estava ausente. Após
`uv run playwright install chromium`, o driver real abriu uma janela visível e
baixou dois ZIPs de um servidor local usando o pool e metadados temporários.
Uma consulta real ao CKAN de boletins de 2022 retornou 112 recursos; esse teste
não demonstrou bloqueio do catálogo naquele momento nem validou uma carga
completa do CDN. A suíte Turi passou com 58 testes.

## Link de checksum anunciado como boletim

Na recuperação seguinte de 2026-10-27, o único `failed_sources` restante era
`bweb_2t_RR_261020260742.zip.sha512`. O catálogo de 2026 anunciava esse checksum
como `format=CSV`, com o nome do boletim de RR/2º turno. O servidor respondia
`200 application/zip`, mas o conteúdo tinha 158 bytes de texto com o hash e o nome
do ZIP. O MIME, o formato CKAN e o status HTTP não bastavam para identificar o
arquivo. Repetir a URL não recuperaria o boletim.

O adaptador de boletins normaliza caminhos terminados em `.zip.sha512` para o
ZIP correspondente, preserva query/fragmento e deduplica URLs. A mesma regra é
aplicada aos `failed_sources` já salvos pelo `TSEBulletinsDownloader`; apenas
corrigir a descoberta não alcançaria essas retentativas. Essa regra pertence ao
adaptador TSE e não ao `Downloader` genérico.

O ZIP correspondente, de 500.520 bytes, foi baixado pelo Playwright e teve SHA-512
conferido. Todas as 5.332 linhas e 45 colunas do Parquet foram comparadas com o
CSV bruto, incluindo ano/UF/turno e soma de 308.597 votos. Foram preservados os
221 arquivos anteriores; o metadado passou a 222 arquivos, `successful=true` e
`failed_sources=[]`. A validação de linhas/votos foi específica do arquivo
recuperado. Relatório em
[tse_bulletin_rr_2026_recovery_2026-10-27.json](audits/tse_bulletin_rr_2026_recovery_2026-10-27.json).

A suíte passou com 60 testes, incluindo normalização de URLs e retentativa de
checksum salvo, tanto com sucesso como com nova falha, preservando os arquivos
anteriores. O downloader ainda faz uma tentativa por URL em cada execução;
essa correção não acrescenta retentativas automáticas para falhas transitórias.
