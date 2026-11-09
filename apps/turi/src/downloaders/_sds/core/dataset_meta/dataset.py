from pydantic import BaseModel
from typing import Optional
from apps.turi.src.downloaders._sds.core.dataset_meta.dataset_input import Step, Download, Process
from apps.turi.src.downloaders._sds.core.dataset_meta.dataset_output import Output
from apps.turi.src.downloaders._sds.core.dataset_meta.dataset_updates import Updates
from apps.turi.src.downloaders._sds.core.paths import BASE_DIR
from pathlib import Path
from apps.turi.src.downloaders._sds.core.filetagger import filetag
from datetime import datetime
from apps.turi.src.downloaders._sds.core.date_expression_parser.humanDate import get_human_date
from apps.turi.src.downloaders._sds.core.utils.download_stream import download_stream, clear_target
from apps.turi.src.downloaders._sds.core.extractors.extractor import Extractor

class DatasetMeta(BaseModel):
    id: str
    name: str
    script: str
    description: Optional[str] = None
    inputs: list[Step]
    output: Output
    updates: Updates

    def getProcessFile(self) -> Process | None:
        for input in self.inputs:
            if input.process is not None:
                return input.process
            
        return None

    def download(self, download_input: Download, extractor: Extractor | None = None):
        output = BASE_DIR / download_input.output

        temporary = output.with_suffix(output.suffix + ".part")
        try:
            download_stream(download_input.url, temporary)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        
        if extractor != None:
            extractor.extract(output, output.parent)

        fpath = output.parent / 'ftag.json'
        filetag.write_filetag_meta(fpath, filetag.FiletagMeta(createdAt=datetime.now()))

    def downloadIfNecessary(self, extractor: Extractor | None = None):
        for input in self.inputs:
            if input.download is None:
                continue

            ftag_path = Path(BASE_DIR / input.download.output).parent / 'ftag.json'

            if ftag_path.exists() and (BASE_DIR / input.download.output).is_file():
                try:
                    ftag = filetag.read_filetag_meta_or_none(ftag_path)
                except ValueError:
                    ftag = None

                if ftag is None:
                    return self.download(input.download, extractor)
                
                current_date = datetime.now()
                download_expires = get_human_date(input.download.expires, ftag.createdAt)
                
                if current_date > download_expires:
                    self.download(input.download, extractor)
            else:
                self.download(input.download, extractor=extractor)


def ReadDatasetMeta(path: Path) -> DatasetMeta:
    metadata_path = path / "metadata.json"
    metadata_description_path = path / "description.txt"

    with open(metadata_path, 'r') as file:
        metadata = file.read()

    with open(metadata_description_path, 'r') as file:
        metadata_description = file.read()

    datasetmeta = DatasetMeta.model_validate_json(metadata)
    datasetmeta.description = metadata_description

    return datasetmeta