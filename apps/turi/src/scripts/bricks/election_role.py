import polars as pl
from enum import Enum
from avoar.core.opendata.election.domain import CargoEleicao

class ElectionRole(Enum):
    PRESIDENTE = 0
    VICE_PRESIDENTE = 1
    SENADOR = 2
    GOVERNADOR = 3
    DEPUTADO_FEDERAL = 4
    DEPUTADO_ESTADUAL = 5
    VEREADOR = 6

"""
Converte o campo "CD_CARGO_PERGUNTA" do boletim de urna do TSE para o tipo de cargo do core do Avoar.
Veja: core/opendata/election.domain.go
"""
def tse_bulletin_election_role_expr(check_col_name: str):
    return (
        pl.when(
            pl.col(check_col_name) == "1"
        ).then(pl.lit(ElectionRole.PRESIDENTE))
        .when(
            pl.col(check_col_name) == "3"
        ).then(pl.lit(ElectionRole.GOVERNADOR))
        .when(
            pl.col(check_col_name) == "5"
        ).then(pl.lit(ElectionRole.SENADOR))
        .when(
            pl.col(check_col_name) == "6"
        ).then(pl.lit(ElectionRole.DEPUTADO_FEDERAL))
        .when(
            pl.col(check_col_name) == "7"
        ).then(pl.lit(ElectionRole.DEPUTADO_ESTADUAL))
        .when(
            pl.col(check_col_name) == "25"
        ).then(pl.lit(CargoEleicao.CONSELHEIRO_DISTRITAL.value))
        .when(
            pl.col(check_col_name) == "13"
        ).then(pl.lit(ElectionRole.VEREADOR))
        .otherwise(
            pl.lit(None)
        )
    )
