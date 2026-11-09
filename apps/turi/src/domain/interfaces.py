from typing import Protocol, List

class RunnableScript(Protocol):
    """Protocolo definindo como um Script deve se comportar."""
    def run(self) -> None:
        ...

class DownloaderProtocol(Protocol):
    """Protocolo definindo como o downloader atual do sistema funciona."""
    def get_meta_files_or_download(self, ext: str, content_type: str) -> tuple[List[str], List[Exception]]:
        ...
