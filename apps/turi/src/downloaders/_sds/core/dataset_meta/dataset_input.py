from pydantic import BaseModel
from typing import Optional

class Download(BaseModel):
    url: str
    output: str
    extractFrom: str
    expires: str

class Process(BaseModel):
    path: str

class Step(BaseModel):
    download: Optional[Download] = None
    process: Optional[Process] = None