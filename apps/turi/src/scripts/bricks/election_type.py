import polars as pl
from enum import Enum

class ElectionType(Enum):
    ORDINARIA = 0
    EXTRAORDINARIA = 1

"""
Converte o campo "CD_TIPO_ELEICAO" do boletim de urna do TSE para o tipo de eleição no core do Avoar
Veja: core/opendata/election.domain.go
"""
def tse_bulletin_election_type_expr(check_col_name: str):
    return (
        pl.when(
            pl.col(check_col_name) == "0"
        ).then(pl.lit(ElectionType.ORDINARIA))
        .when(
            pl.col(check_col_name) == "1"
        ).then(pl.lit(ElectionType.EXTRAORDINARIA))
        .otherwise(
            pl.lit(None)
        )
    )