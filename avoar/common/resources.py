"""Resource-size parsing shared by producers and serving applications."""
from decimal import Decimal
import re


def parse_size(value: str) -> int:
    match = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?\s*",
        value,
        re.I,
    )
    if match is None:
        raise ValueError(f"Invalid DataFusion resource size: {value}")

    unit = (match[2] or "B").upper()
    units = {
        "B": 1,
        **{f"{prefix}B": 1000 ** power for power, prefix in enumerate("KMGT", 1)},
        **{f"{prefix}IB": 1024 ** power for power, prefix in enumerate("KMGT", 1)},
    }
    size = int(Decimal(match[1]) * units[unit])
    if size <= 0:
        raise ValueError("DataFusion resource sizes must be positive")

    return size
