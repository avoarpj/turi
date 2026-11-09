"""Gera as camadas GeoJSON nacional e municipais da malha IBGE 2025.

Execute da raiz: uv run python -m apps.scripts.brazilgeo.generate
"""

import argparse
import json
import logging
import math
import shutil
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import httpx
import shapely

from apps.turi.src.infra.downloader.downloader import Downloader


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "assets" / "brazilgeo"
SOURCE_URL = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/"
    "malhas_territoriais/malhas_municipais/municipio_2025/"
    "Brasil/BR_Municipios_2025.zip"
)
SOURCE_COLUMNS = {
    "CD_MUN": "codigo_ibge",
    "NM_MUN": "nome",
    "CD_UF": "codigo_uf",
    "NM_UF": "nome_uf",
    "SIGLA_UF": "uf",
}
STATES_SIMPLIFICATION_METERS = 1_000.0
METRIC_CRS = "EPSG:5880"  # SIRGAS 2000 / Brazil Polyconic; unidades em metros.

logger = logging.getLogger(__name__)


def download_shapefile() -> Path:
    with httpx.Client(follow_redirects=True, timeout=300.0) as client:
        downloader = Downloader(
            meta_name="ibge_municipios_2025",
            meta_age_tolerance=timedelta(0),
            meta_path=Path("ibge/brazilgeo/meta"),
            files_path=Path("ibge/brazilgeo"),
            sources=[SOURCE_URL],
            concurrent_downloads=1,
            http_client=client,
            keep_raw=True,
        )

        logger.info("Baixando e extraindo %s", SOURCE_URL)
        files, errors = downloader.download_from_sources("zip", "application/zip")

    if errors:
        messages = "; ".join(error.message for error in errors)
        raise RuntimeError(f"Falha ao baixar a malha IBGE: {messages}")

    shapefiles = [
        shapefile
        for directory in files
        for shapefile in Path(directory).rglob("*.shp")
    ]
    if len(shapefiles) != 1:
        raise ValueError(f"Esperado um shapefile na malha IBGE: {shapefiles}")

    return shapefiles[0]


def validate_geometries(frame: gpd.GeoDataFrame) -> None:
    invalid = (
        frame.geometry.isna()
        | frame.geometry.is_empty
        | ~frame.geometry.is_valid
        | ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    )
    if invalid.any():
        raise ValueError(f"Geometrias ausentes ou inválidas: {frame.index[invalid].tolist()}")


def read_municipalities(shapefile: Path) -> gpd.GeoDataFrame:
    logger.info("Lendo %s", shapefile)
    source = gpd.read_file(shapefile, engine="pyogrio")

    missing = SOURCE_COLUMNS.keys() - set(source.columns)
    if missing:
        raise ValueError(f"Campos obrigatórios ausentes da malha IBGE: {sorted(missing)}")
    if source.empty or source.crs is None:
        raise ValueError("Malha IBGE vazia ou sem sistema de coordenadas")

    municipalities = source[[*SOURCE_COLUMNS, "geometry"]].rename(columns=SOURCE_COLUMNS)
    municipalities = municipalities.to_crs("EPSG:4326")
    municipalities = municipalities.sort_values("codigo_ibge").reset_index(drop=True)

    properties = list(SOURCE_COLUMNS.values())
    if municipalities[properties].isna().any().any():
        raise ValueError("Metadados obrigatórios nulos na malha IBGE")

    municipalities[properties] = municipalities[properties].astype(str)
    if not municipalities.codigo_ibge.str.fullmatch(r"[0-9]{7}").all():
        raise ValueError("Código municipal IBGE deve ter sete dígitos")
    if municipalities.codigo_ibge.duplicated().any():
        raise ValueError("Códigos municipais IBGE duplicados")
    if not municipalities.uf.str.fullmatch(r"[A-Z]{2}").all():
        raise ValueError("Sigla de UF inválida")
    if not municipalities.codigo_uf.str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("Código estadual IBGE deve ter dois dígitos")
    if not municipalities.codigo_ibge.str[:2].eq(municipalities.codigo_uf).all():
        raise ValueError("Município com prefixo IBGE diferente do código estadual")

    state_metadata = municipalities[["uf", "codigo_uf", "nome_uf"]].drop_duplicates()
    if (
        len(state_metadata) != 27
        or state_metadata.uf.duplicated().any()
        or state_metadata.codigo_uf.duplicated().any()
    ):
        raise ValueError("Esperadas 27 UFs com metadados consistentes (incluindo o DF)")

    validate_geometries(municipalities)

    return municipalities


def build_states(
    municipalities: gpd.GeoDataFrame,
    simplification_meters: float,
) -> gpd.GeoDataFrame:
    logger.info("Dissolvendo limites municipais por UF")
    state_columns = ["uf", "codigo_uf", "nome_uf", "geometry"]
    states = municipalities[state_columns].dissolve(by="uf", as_index=False)
    states = states.rename(columns={"nome_uf": "nome"})
    states["municipios_bbox"] = states.geometry.bounds.to_numpy().tolist()

    if simplification_meters > 0:
        logger.info("Simplificando estados com tolerância de %.0f m", simplification_meters)
        projected = states.to_crs(METRIC_CRS)
        
        if not projected.geometry.is_valid_coverage():
            logger.info("Normalizando a topologia da camada estadual")
            projected.geometry = shapely.coverage_clean(
                projected.geometry.array,
                snapping_distance=0.01,
            )

        if not projected.geometry.is_valid_coverage():
            raise ValueError("Limites estaduais não formam cobertura válida para simplificação")

        projected.geometry = projected.geometry.simplify_coverage(simplification_meters)
        states = projected.to_crs("EPSG:4326")

    validate_geometries(states)
    states["municipios_url"] = states.uf.map(lambda uf: f"states/{uf}.geojson")

    return states.sort_values("uf").reset_index(drop=True)


def write_geojson(frame: gpd.GeoDataFrame, path: Path, id_column: str) -> None:
    indexed = frame.set_index(id_column, drop=False)
    indexed.geometry = indexed.geometry.orient_polygons()
    collection = indexed.to_geo_dict(show_bbox=True)

    with path.open("w", encoding="utf-8") as output:
        json.dump(
            collection,
            output,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        output.write("\n")

    if id_column == "codigo_ibge":
        write_municipality_bounds(collection["features"], path.with_suffix(".bounds.json"))

    logger.info(
        "%s: %d feições, %.2f MiB",
        path.relative_to(OUTPUT_DIR),
        len(frame),
        path.stat().st_size / 1024**2,
    )


def write_municipality_bounds(features: list[dict], path: Path) -> None:
    bounds = {}

    for feature in features:
        code = feature["properties"]["codigo_ibge"]
        box = feature["bbox"]

        if (
            not isinstance(code, str) or len(code) != 7 or not code.isascii() or not code.isdecimal()
            or code in bounds or len(box) != 4
            or any(not isinstance(value, (float, int)) or not math.isfinite(value) for value in box)
            or not -180 <= box[0] <= box[2] <= 180
            or not -90 <= box[1] <= box[3] <= 90
        ):
            raise ValueError(f"Limite municipal inválido: {code}")

        bounds[code] = box

    staging = path.with_suffix(".tmp")
    staging.write_text(
        json.dumps(bounds, allow_nan=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    staging.replace(path)
    logger.info("%s: limites de %d municípios", path.name, len(bounds))


def generate_bounds_indexes() -> None:
    """Backfill small navigation indexes without downloading or rewriting maps."""
    files = sorted((OUTPUT_DIR / "states").glob("*.geojson"))

    if not files:
        raise ValueError("Malhas estaduais ausentes; gere os mapas primeiro")

    for path in files:
        collection = json.loads(path.read_text(encoding="utf-8"))
        write_municipality_bounds(collection["features"], path.with_suffix(".bounds.json"))


def generate(simplification_meters: float = STATES_SIMPLIFICATION_METERS) -> None:
    if not math.isfinite(simplification_meters) or simplification_meters < 0:
        raise ValueError("A tolerância de simplificação deve ser finita e não negativa")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    states_dir = OUTPUT_DIR / "states"
    states_dir.mkdir(parents=True)

    shapefile = download_shapefile()
    municipalities = read_municipalities(shapefile)
    states = build_states(municipalities, simplification_meters)

    write_geojson(states, OUTPUT_DIR / "BR.geojson", "uf")
    for uf, state_municipalities in municipalities.groupby("uf", sort=True):
        write_geojson(state_municipalities, states_dir / f"{uf}.geojson", "codigo_ibge")

    logger.info(
        "Concluído: %d UFs e %d feições na malha municipal",
        len(states),
        len(municipalities),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bounds-only",
        action="store_true",
        help="Gera somente os índices de limites dos GeoJSONs existentes, sem baixar ou apagar mapas",
    )
    parser.add_argument(
        "--states-simplification-meters",
        type=float,
        default=STATES_SIMPLIFICATION_METERS,
        help="Tolerância da camada nacional em metros (padrão: 1000; 0 desativa)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.bounds_only:
        generate_bounds_indexes()
    else:
        generate(args.states_simplification_meters)


if __name__ == "__main__":
    main()
