from urllib.request import urlopen
from pathlib import Path
import shutil

def clear_target(path: Path) -> None:
    path = Path(path)

    if not path.exists():
        return

    if path.is_file() or path.is_symlink():
        path.unlink()
        return

    if path.is_dir():
        for item in path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()


def download_stream(url: str, target: Path, chunk_size: int = 8192) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    with urlopen(url) as response, open(target, "wb") as f:
        shutil.copyfileobj(response, f, length=chunk_size)