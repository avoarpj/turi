import os
import xmltodict
import json
from pathlib import Path
from datetime import datetime

# Seus imports de infra/core
from apps.turi.src.downloaders._sds.core.dataset_meta.dataset import DatasetMeta
from apps.turi.src.downloaders._sds.core.filetagger.filetag import write_filetag_meta, FiletagMeta, read_filetag_meta_or_none
from apps.turi.src.downloaders._sds.core.paths import BASE_DIR
from apps.turi.src.downloaders._sds.infra.BulkDownloader import BulkDownloader, Item

# Classes de input (JSON antigo) e Output (XML novo)
from apps.turi.src.downloaders._sds.infra.dataset_types.historico_deputados_federais.deputy import CD_DeputiesRaw
from apps.turi.src.downloaders._sds.infra.dataset_types.historico_deputados_federais.api_deputy import XML_DeputiesRoot, XML_Deputy

def _onDownload(item: Item):
    write_filetag_meta(
        path=item.path.parent / "ftag.json",
        meta=FiletagMeta(createdAt=datetime.now())
    )

_downloader = BulkDownloader(
    rate=4,
    concurrency=6,
    retry_base_delay=1,
    retry_max_delay=480,
    connector_kwargs=dict(
        limit=2,
        keepalive_timeout=4,
        ttl_dns_cache=300,
        force_close=False
    ),
    timeout_kwargs=dict(
        total=120,
        connect=30,
        sock_read=60
    ),
    task_delay=2.5,
    task_jitter=5.5,
    callback=_onDownload
)

def _parse_xml_deputy(xml_content: str) -> list[dict]:
    # Mantemos o force_list para os elementos internos
    data = xmltodict.parse(xml_content, force_list={
        'Deputado', 'comissao', 'cargoComissoes', 
        'periodoExercicio', 'filiacaoPartidaria', 'itemHistoricoLider'
    })
    
    deputados = data.get('Deputados', {}).get('Deputado', [])
    
    # Lista de campos que no XML são wraps (<comissoes><comissao>...)
    # mas no Pydantic queremos que sejam apenas a lista interna.
    list_mappings = {
        'comissoes': 'comissao',
        'cargosComissoes': 'cargoComissoes',
        'periodosExercicio': 'periodoExercicio',
        'filiacoesPartidarias': 'filiacaoPartidaria',
        'historicoLider': 'itemHistoricoLider'
    }

    cleaned_deputados = []
    for dep in deputados:
        for pydantic_key, xml_child_key in list_mappings.items():
            # Pega o valor atual (ex: dep['comissoes'])
            val = dep.get(pydantic_key)
            
            if val and isinstance(val, dict) and xml_child_key in val:
                # Remove o wrapper: {"comissao": [...]} -> [...]
                dep[pydantic_key] = val[xml_child_key]
            else:
                # Se for None ou vazio, garante lista vazia para o Pydantic
                dep[pydantic_key] = []
        
        cleaned_deputados.append(dep)

    return cleaned_deputados

async def Callback(dataset: DatasetMeta) -> None:
    await _update_deputies(dataset, _downloader)


async def _update_deputies(
    dataset: DatasetMeta,
    downloader: BulkDownloader,
    *,
    current_legislature: int | None = None,
    max_size: int | None = None,
    ftag_max_age: float = 259200.0,
) -> None:
    """Baixa detalhes legados e consolida todo o cache, inclusive o histórico."""
    dataset.downloadIfNecessary()
    fpath = dataset.getProcessFile()

    if fpath is None: raise FileNotFoundError("Cannot find process file")
    if dataset.output.path.jjson is None: raise FileNotFoundError("No json path provided")

    deputies_path = BASE_DIR / Path(fpath.path)

    with open(deputies_path, 'r') as f:
        json_data = f.read()

    # Usando a classe original para processar a lista inicial
    deputies_list = CD_DeputiesRaw.model_validate_json(json_data=json_data)
    
    download_urls: list[Item] = []
    all_ids: list[str] = []

    for deputy in deputies_list.dados:
        deputy_id = str(deputy.get_id())
        
        folder = deputies_path.parent / deputy_id
        xml_file = folder / f"{deputy_id}.xml"
        ftag = folder / "ftag.json"

        all_ids.append(deputy_id)

        if current_legislature is not None:
            # A lista moderna inclui a primeira e a última legislatura de cada deputado.
            if (deputy.idLegislaturaFinal < current_legislature - 1
                    or deputy.idLegislaturaInicial > current_legislature):
                continue

        if max_size is not None and len(download_urls) >= max_size:
            continue

        needs_download = not xml_file.exists()
        if current_legislature is not None and not needs_download:
            try:
                meta = read_filetag_meta_or_none(ftag)
            except ValueError:
                meta = None
            needs_download = (
                meta is None
                or (datetime.now(meta.createdAt.tzinfo) - meta.createdAt).total_seconds() >= ftag_max_age
            )

        if needs_download:
            download_urls.append(Item(
                url=f"https://www.camara.leg.br/SitCamaraWS/Deputados.asmx/ObterDetalhesDeputado?ideCadastro={deputy_id}&numLegislatura=",
                path=xml_file
            ))

    # Executa os downloads pendentes
    await downloader.download_all(download_urls, 86400)

    consolidated_data: list[XML_Deputy] = []

    # Processamento pós-download
    for id in all_ids:
        folder = deputies_path.parent / id
        xml_file = folder / f"{id}.xml"

        if not xml_file.exists():
            continue

        with open(xml_file, 'r', encoding='utf-8') as f:
            content = f.read()

        try:
            # Converte as legislaturas encontradas no XML para a lista global
            legislaturas = _parse_xml_deputy(content)
            for leg_dict in legislaturas:
                # Valida contra o novo schema XML_Deputy
                deputy_model = XML_Deputy.model_validate(leg_dict)
                consolidated_data.append(deputy_model)
        except Exception as e:
            raise ValueError(f"Erro ao validar XML do deputado {id}") from e

    # Gera o dump final consolidado
    full_output = XML_DeputiesRoot(
        Deputados=consolidated_data
    )

    final_json_path = BASE_DIR / dataset.output.path.jjson
    final_json_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = f"{final_json_path}.temp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(full_output.model_dump_json(indent=4))

    os.replace(temp_path, final_json_path)
    
    return
