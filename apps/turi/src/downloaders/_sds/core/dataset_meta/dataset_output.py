from pydantic import BaseModel, Field
from typing import Optional

class OutputPath(BaseModel):
    csv: Optional[str]
    jjson: Optional[str] = Field(alias="json")
    xml: Optional[str]

class Output(BaseModel):
    path: OutputPath