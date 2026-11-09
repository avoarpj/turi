from abc import ABC, abstractmethod
from pathlib import Path

class Extractor(ABC):
    @abstractmethod
    def extract(self, input: Path, output: Path) -> None:
        pass