from pydantic import BaseModel

class CD_Deputy(BaseModel):
    uri: str
    nome: str

    idLegislaturaInicial: int
    idLegislaturaFinal: int

    nomeCivil: str
    siglaSexo: str
    
    urlRedeSocial: list[str]
    urlWebsite: list[str]
    
    dataNascimento: str
    dataFalecimento: str

    ufNascimento: str
    municipioNascimento: str

    def get_id(self) -> str:
        split_data = self.uri.split("/")

        return split_data[len(split_data) - 1]
    
class CD_DeputyRaw(BaseModel):
    dados: CD_Deputy

class CD_DeputiesRaw(BaseModel):
    dados: list[CD_Deputy]