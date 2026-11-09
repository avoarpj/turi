from pydantic import BaseModel
from typing import Optional

class CD_History(BaseModel):
    id: int
    uri: str
    nome: str
    nomeEleitoral: Optional[str]
    siglaPartido: str
    uriPartido: str
    siglaUf: Optional[str]
    idLegislatura: int
    email: Optional[str]
    urlFoto: Optional[str]
    dataHora: str
    situacao: Optional[str]
    condicaoEleitoral: Optional[str]
    descricaoStatus: str

class CD_HistoryRaw(BaseModel):
    dados: list[CD_History]