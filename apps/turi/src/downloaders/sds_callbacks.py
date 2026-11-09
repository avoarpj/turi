"""Run the former SDS generators inside Downloader's transfer callback."""
import asyncio
import inspect
import shutil
from pathlib import Path

from apps.turi.src.downloaders._sds.core.dataset_meta.dataset import DatasetMeta
from apps.turi.src.downloaders._sds.core.paths import BASE_DIR

DATASETS = Path(__file__).parent / "_sds" / "datasets"


def _generate(dataset_name: str, module_name: str, target: Path) -> None:
    from importlib import import_module

    dataset = DatasetMeta.model_validate_json(
        (DATASETS / dataset_name / "metadata.json").read_text(encoding="utf-8")
    )
    # Resolve legacy paths once: no SDS operation depends on process cwd.
    for step in dataset.inputs:
        if step.download is not None:
            step.download.output = str(BASE_DIR / step.download.output)
        if step.process is not None:
            step.process.path = str(BASE_DIR / step.process.path)

    for field in ("csv", "jjson", "xml"):
        value = getattr(dataset.output.path, field)
        setattr(dataset.output.path, field, str(BASE_DIR / value) if value else None)

    module = import_module(
        f"apps.turi.src.downloaders._sds.infra.scripts.{module_name}"
    )
    result = module.Callback(dataset)

    if inspect.isawaitable(result):
        asyncio.run(result)

    output = BASE_DIR / dataset.output.path.jjson
    if not output.is_file():
        raise FileNotFoundError(f"SDS did not generate {output}")

    shutil.copyfile(output, target)


def municipalities_centroid(downloader, source: str, target: Path) -> None:
    _generate(
        "centroide-municipios-brasileiros",
        "centroide_municipios_brasileiros",
        target,
    )


def federal_deputies_history(downloader, source: str, target: Path) -> None:
    # A fresh checkout needs the complete cache before incremental updates.
    output = BASE_DIR / "public/datasets/historico_deputados_federais/historico.json"
    module = "historico_deputados_federais"
    if output.exists():
        module += "_incremental"

    _generate("historico-deputados-federais", module, target)


def federal_deputies_detailed(downloader, source: str, target: Path) -> None:
    output = BASE_DIR / "public/datasets/camaradosdeputados_deputados_federais/deputados.json"
    module = "camaradosdeputados_deputados_federais"
    if output.exists():
        module += "_incremental"

    _generate("camaradosdeputados-deputies", module, target)
