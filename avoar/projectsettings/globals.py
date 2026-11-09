import os
from pathlib import Path
from dotenv import load_dotenv

def find_project_root(start: Path | None = None) -> Path:
    start = Path(start or __file__).resolve()

    for p in [start, *start.parents]:
        if (p / "project_root.py").exists():
            return p
    raise FileNotFoundError("project_root.py not found")

PROJECT_ROOT = find_project_root()

load_dotenv(PROJECT_ROOT / ".env")

OPENDATA_DUMPS_OUTPUT_DIR = PROJECT_ROOT / "parquet_dumps" / "opendata"
VENATO_DATA_DIR = PROJECT_ROOT / os.getenv("VENATO_DATA_DIR", "venato_data")
