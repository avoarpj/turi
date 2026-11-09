from apps.turi.src.downloaders._sds.core.dataset_meta.dataset import DatasetMeta
import geopandas as gpd
from pathlib import Path
from apps.turi.src.downloaders._sds.core.paths import BASE_DIR
from apps.turi.src.downloaders._sds.infra.extractors.from_zip import zipInstance

def Callback(dataset: DatasetMeta) -> None:
    """
        Esta função gera centróides de todos os municípios do Brasil derivados da malha digital do território brasileiro, disponibilizada pelo IBGE.
    """

    dataset.downloadIfNecessary(extractor=zipInstance)

    fpath = dataset.getProcessFile()

    if fpath is None:
        raise FileNotFoundError(f"Cannot find process file")

    shp_path = BASE_DIR / Path(fpath.path)

    gdf = gpd.read_file(shp_path) # type: ignore

    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4674)

    gdf_proj = gdf.to_crs(epsg=5880)
    gdf_proj["centroid"] = gdf_proj.geometry.centroid

    centroids = gdf_proj.set_geometry("centroid").to_crs(epsg=4674)

    centroids["lon"] = centroids.geometry.x
    centroids["lat"] = centroids.geometry.y

    result = centroids[
        [
            "CD_MUN",
            "NM_MUN",
            "SIGLA_UF",
            "lat",
            "lon",
        ]
    ]

    result = result.rename(
        columns={
            "CD_MUN": "codigo_municipio",
            "NM_MUN": "nome_municipio",
            "SIGLA_UF": "uf",
            "lat": "latitude",
            "lon": "longitude"
        }
    )

    if dataset.output.path.csv is not None:
        csv_path = BASE_DIR / Path(dataset.output.path.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        result.to_csv(csv_path, index=False)

    if dataset.output.path.jjson is not None:
        json_path = BASE_DIR / Path(dataset.output.path.jjson)
        json_path.parent.mkdir(parents=True, exist_ok=True)

        result.to_json( # type: ignore[call-arg]
            str(json_path),
            orient="records",
            force_ascii=False,
            indent=4
        )

    if dataset.output.path.xml is not None:
        xml_path = BASE_DIR / Path(dataset.output.path.xml)
        xml_path.parent.mkdir(parents=True, exist_ok=True)

        result.to_xml(
            xml_path,
            index=False,
            root_name="centroides",
            row_name="municipio",
            parser="etree"
        )

    return