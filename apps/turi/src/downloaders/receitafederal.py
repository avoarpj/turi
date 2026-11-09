import asyncio
from datetime import datetime, timedelta
import functools
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx
import base64

from infra.downloader.downloader import Downloader, DynamicURL

BASE_URL = "https://arquivos.receitafederal.gov.br"
PUBLIC_TOKEN = "YggdBLfdninEJX9"

auth_token = base64.b64encode(f"{PUBLIC_TOKEN}:".encode()).decode()

http_client = httpx.Client(
    headers={
        "Authorization": f"Basic {auth_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    },
    follow_redirects=True,
    timeout=httpx.Timeout(connect=20.0, read=300.0, write=30.0, pool=30.0)
)

def generate_month_candidates(max_months_back: int = 12) -> list[str]:
    now = datetime.now()
    candidates: list[str] = []
    
    current_year = now.year
    current_month = now.month
    
    for _ in range(max_months_back):
        candidates.append(f"{current_year:04d}-{current_month:02d}")
        current_month -= 1
        if current_month == 0:
            current_month = 12
            current_year -= 1
            
    return candidates


async def list_files_in_folder(
    client: httpx.AsyncClient, token: str, folder_name: str
) -> list[str] | None:
    webdav_url = f"{BASE_URL}/public.php/webdav/{folder_name}"
    
    try:
        response = await client.request(
            "PROPFIND",
            webdav_url,
            auth=(token, ""),
            headers={"Depth": "1"},
            timeout=15.0,
        )
        
        if response.status_code != 207:
            return None

        root = ET.fromstring(response.content)
        files: list[str] = []
        for elem in root.findall(".//{DAV:}href"):
            if elem.text:
                filename = elem.text.rstrip("/").split("/")[-1]
                if filename and filename != folder_name:
                    files.append(filename)

        return sorted(list(set(files)))

    except (httpx.HTTPError, ET.ParseError):
        return None


@functools.cache
def get_cached_receita_folder_and_files(token: str = PUBLIC_TOKEN) -> tuple[str, list[str]]:
    async def _fetch():
        candidates = generate_month_candidates(max_months_back=12)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for folder in candidates:
                files = await list_files_in_folder(client, token, folder)
                if files:
                    return folder, files
        raise RuntimeError("Nenhuma pasta de dados recente foi encontrada no servidor da RFB.")

    return asyncio.run(_fetch())


def receitafederal_urls(prefix: str, token: str = PUBLIC_TOKEN):
    class ReceitaFederalDateURLS(DynamicURL):
        def gen_urls(self) -> list[str]:
            active_folder, available_files = get_cached_receita_folder_and_files(token)
            
            matched_files = sorted([
                f for f in available_files 
                if f.lower().startswith(prefix.lower()) and f.endswith(".zip")
            ])
            
            if not matched_files:
                raise RuntimeError(f"Nenhum arquivo com prefixo '{prefix}' encontrado na pasta {active_folder}.")

            return [
                f"{BASE_URL}/public.php/webdav/{active_folder}/{filename}"
                for filename in matched_files
            ]

    return ReceitaFederalDateURLS


receitafederal_cnaes = Downloader(
    meta_name="receitafederal_cnaes",
    concurrent_downloads=1,
    files_path=Path("receitafederal/cnaes"),
    http_client=http_client,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("receitafederal/cnaes") / "meta",
    sources=[],
    dynamic_sources=receitafederal_urls("Cnaes")(),
    default_encoding="ISO-8859-1",
    csv_separator=";",
    hard_suffix=".csv",
    csv_header=[
        'codigo_cnae',
        'nome_cnae'
    ]
)

receitafederal_empresas = Downloader(
    meta_name="receitafederal_empresas",
    concurrent_downloads=1,
    files_path=Path("receitafederal/empresas"),
    http_client=http_client,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("receitafederal/empresas") / "meta",
    sources=[],
    dynamic_sources=receitafederal_urls("Empresas")(),
    default_encoding="ISO-8859-1",
    csv_separator=";",
    hard_suffix=".csv",
    csv_header=[
        'cnpj_basico',
        'razao_social',
        'natureza_juridica',
        'qualificacao_do_responsavel',
        'capital_social',
        'porte',
        'ente_federativo_responsavel'
    ]
)

receitafederal_estabelecimentos = Downloader(
    meta_name="receitafederal_estabelecimentos",
    concurrent_downloads=1,
    files_path=Path("receitafederal/estabelecimentos"),
    http_client=http_client,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("receitafederal/estabelecimentos") / "meta",
    sources=[],
    dynamic_sources=receitafederal_urls("Estabelecimentos")(),
    default_encoding="ISO-8859-1",
    csv_separator=";",
    hard_suffix=".csv",
    csv_header=[
        'cnpj_basico',
        'cnpj_ordem',
        'cnpj_dv',
        'indicador_matriz_ou_filial',
        'nome_fantasia',
        'situacao_cadastral',
        'data_situacao_cadastral',
        'motivo_situacao_cadastral',
        'nome_da_cidade_no_exterior',
        'pais',
        'data_de_inicio_atividade',
        'cnae_fiscal_principal',
        'cnae_fiscal_secundaria',
        'tipo_de_logradouro',
        'logradouro',
        'numero',
        'complemento',
        'bairro',
        'cep',
        'uf',
        'municipio',
        'ddd_1',
        'telefone_1',
        'ddd_2',
        'telefone_2',
        'ddd_fax',
        'fax',
        'correio_eletronico',
        'situacao_especial',
        'data_situacao_especial'
    ]
)

receitafederal_socios = Downloader(
    meta_name="receitafederal_socios",
    concurrent_downloads=1,
    files_path=Path("receitafederal/socios"),
    http_client=http_client,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("receitafederal/socios") / "meta",
    sources=[],
    dynamic_sources=receitafederal_urls("Socios")(),
    default_encoding="ISO-8859-1",
    csv_separator=";",
    hard_suffix=".csv",
    csv_header=[
        'cnpj_basico',
        'identificador_de_socio',
        'nome_do_socio',
        'cnpjcpf_socio',
        'qualificacao_socio',
        'data_de_entrada_sociedade',
        'pais',
        'representante_legal',
        'nome_representante_legal',
        'qualificacao_representante_legal',
        'faixa_etaria_socio'
    ]
)

receitafederal_naturezas = Downloader(
    meta_name="receitafederal_naturezas",
    concurrent_downloads=1,
    files_path=Path("receitafederal/naturezas"),
    http_client=http_client,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("receitafederal/naturezas") / "meta",
    sources=[],
    dynamic_sources=receitafederal_urls("naturezas")(),
    default_encoding="ISO-8859-1",
    csv_separator=";",
    hard_suffix=".csv",
    csv_header=[
        'codigo',
        'descricao'
    ]
)