from pydantic import BaseModel, Field
from typing import Optional, List

class XML_Party(BaseModel):
    idPartido: Optional[str] = None
    sigla: Optional[str] = None
    nome: Optional[str] = None

class XML_Office(BaseModel):
    numero: Optional[str] = None
    anexo: Optional[str] = None
    telefone: Optional[str] = None

class XML_Commission(BaseModel):
    idOrgaoLegislativoCD: Optional[int] = None
    siglaComissao: Optional[str] = None
    nomeComissao: Optional[str] = None
    condicaoMembro: Optional[str] = None
    dataEntrada: Optional[str] = None
    dataSaida: Optional[str] = None

class XML_CommissionRole(BaseModel):
    idOrgaoLegislativoCD: Optional[int] = None
    siglaComissao: Optional[str] = None
    nomeComissao: Optional[str] = None
    idCargo: Optional[int] = None
    nomeCargo: Optional[str] = None
    dataEntrada: Optional[str] = None
    dataSaida: Optional[str] = None

class XML_ExercisePeriod(BaseModel):
    siglaUFRepresentacao: Optional[str] = None
    situacaoExercicio: Optional[str] = None
    dataInicio: Optional[str] = None
    dataFim: Optional[str] = None
    idCausaFimExercicio: Optional[str] = None
    descricaoCausaFimExercicio: Optional[str] = None

class XML_PartyAffiliation(BaseModel):
    idPartidoAnterior: Optional[str] = None
    siglaPartidoAnterior: Optional[str] = None
    nomePartidoAnterior: Optional[str] = None
    idPartidoPosterior: Optional[str] = None
    siglaPartidoPosterior: Optional[str] = None
    nomePartidoPosterior: Optional[str] = None
    dataFiliacaoPartidoPosterior: Optional[str] = None

class XML_LeaderHistory(BaseModel):
    idHistoricoLider: Optional[int] = None
    idCargoLideranca: Optional[str] = None
    descricaoCargoLideranca: Optional[str] = None
    dataDesignacao: Optional[str] = None
    dataTermino: Optional[str] = None
    siglaUnidadeLideranca: Optional[str] = None

class XML_Deputy(BaseModel):
    numLegislatura: int
    email: Optional[str] = None
    nomeProfissao: Optional[str] = None
    dataNascimento: Optional[str] = None
    dataFalecimento: Optional[str] = None
    ufRepresentacaoAtual: Optional[str] = None
    situacaoNaLegislaturaAtual: Optional[str] = None
    ideCadastro: int
    nomeParlamentarAtual: str
    nomeCivil: str
    sexo: str
    partidoAtual: XML_Party
    gabinete: XML_Office
    # Listas aninhadas
    comissoes: List[XML_Commission] = Field(default_factory=list)
    cargosComissoes: List[XML_CommissionRole] = Field(default_factory=list)
    periodosExercicio: List[XML_ExercisePeriod] = Field(default_factory=list)
    filiacoesPartidarias: List[XML_PartyAffiliation] = Field(default_factory=list)
    historicoLider: List[XML_LeaderHistory] = Field(default_factory=list)

class XML_DeputiesRoot(BaseModel):
    Deputados: List[XML_Deputy]