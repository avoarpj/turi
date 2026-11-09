from pydantic import BaseModel

class Updates(BaseModel):
    cron_expr: str