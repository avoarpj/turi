import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

from avoar.core.opendata.common.identity import NUMERIC_HASH_SEED

RQ_USER_AGENT = "AvoarBot (https://github.com/avoar)"

load_dotenv()

def find_project_root(start: Path | None = None) -> Path:
    start = Path(start or __file__).resolve()

    for p in [start, *start.parents]:
        if (p / "project_root.py").exists():
            return p
    raise FileNotFoundError("project_root.py not found")

PROJECT_ROOT = find_project_root()

# extensão configurável
BASE_DIR_EXTENSION = os.getenv("TURI_BASE_DIR_EXTENSION", "")
BASE_DIR = (PROJECT_ROOT / BASE_DIR_EXTENSION).resolve()

DUMPS_OUTPUT_DIR = Path(
    os.getenv("DUMPS_OUTPUT_DIR", BASE_DIR / "parquet_dumps")
)
DUMPS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCRIPTS_OPERATIONS_METADATA_DIR = PROJECT_ROOT / "apps" / "turi" / "src" / "scripts" / "__metadata__"
SCRIPTS_OPERATIONS_METADATA_DIR.mkdir(parents=True, exist_ok=True)

SDS_BASE_URL = os.getenv("SDS_BASE_URL", "http://localhost:8000")

SNOWFLAKE_INSTACE_ID = int(os.getenv("SNOWFLAKE_INSTANCE_ID", "0"))
SNOWFLAKE_EPOCH = int(os.getenv("SNOWFLAKE_EPOCH", "1741477800000")) # 08/03/2025 - primeira dev log do Avoar
