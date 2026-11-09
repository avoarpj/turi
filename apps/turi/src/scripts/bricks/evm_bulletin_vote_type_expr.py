import polars as pl

from avoar.core.opendata.evm.domain import TipoItemBoletim


def tse_evm_bulletin_vote_type_expr(votavel_target_col: str, tipo_votavel_target_col: str):
    """Convert TSE vote types to the public domain enum."""
    return (
        pl.when(pl.col(votavel_target_col) == "95").then(pl.lit(TipoItemBoletim.BRANCO.value))
        .when(pl.col(votavel_target_col) == "96").then(pl.lit(TipoItemBoletim.NULO.value))
        .when(pl.col(votavel_target_col) == "97").then(pl.lit(TipoItemBoletim.ANULADO_JUDICIALMENTE.value))
        .when(pl.col(votavel_target_col) == "98").then(pl.lit(TipoItemBoletim.ANULADO.value))
        .when(pl.col(tipo_votavel_target_col) == "1").then(pl.lit(TipoItemBoletim.NOMINAL.value))
        .when(pl.col(tipo_votavel_target_col) == "4").then(pl.lit(TipoItemBoletim.LEGENDA.value))
        .otherwise(pl.lit(None, dtype=pl.Int32))
    )
