from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

class FiletagMeta(BaseModel):
    createdAt: datetime

def read_filetag_meta_or_none(path: Path) -> FiletagMeta | None:
    try:
        data = path.read_text(encoding="utf-8")
        return FiletagMeta.model_validate_json(data)
    except (FileNotFoundError):
        return None
    
def write_filetag_meta(path: Path, meta: FiletagMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        meta.model_dump_json(indent=2),
        encoding="utf-8"
    )