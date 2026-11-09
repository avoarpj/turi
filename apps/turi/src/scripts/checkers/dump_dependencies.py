from pathlib import Path

"""
Alguns scripts utilizam dumps prontos para fazer cruzamento de dados.
Para que possam executar na ordem correta (baseada em suas dependências), fiz este utilitário que verifica pela existência de todos os arquivos passados a ele.
"""

def check_for_dumps_dependencies(required_dumps: list[Path]) -> None:
    for dump in required_dumps:
        if not dump.exists():
            raise FileNotFoundError(f"Can't find required dump: {str(dump)}")
        
        if not dump.is_file():
            raise IsADirectoryError(f"Required dump isn't a file: {str(dump)}")