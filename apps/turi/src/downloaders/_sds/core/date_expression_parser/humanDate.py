from datetime import datetime, timedelta
import re

UNITS_IN_MS = {
    "ms": 1,
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
    "y": 31_536_000_000
}

DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|[smhdwy])")

def get_human_date(expr: str, base_date: datetime | None) -> datetime:
    if base_date is None:
        base_date = datetime.now()

    expr = expr.strip().lower()

    matches = DURATION_RE.findall(expr)
    if not matches:
        raise ValueError(f"Expressão inválida: {expr}")

    total_ms = 0.0

    for value, unit in matches:
        total_ms += float(value) * UNITS_IN_MS[unit]

    return base_date + timedelta(milliseconds=total_ms)
