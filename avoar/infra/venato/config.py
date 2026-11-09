from dataclasses import dataclass
from pathlib import Path

@dataclass
class VenatoConfig():
    data_dir: Path