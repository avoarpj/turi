"""Normalize historical TSE bulletin layouts before combining files."""
import polars as pl


def normalize_tse_bulletin(frame: pl.LazyFrame) -> pl.LazyFrame:
    columns = frame.collect_schema().names()
    for old, new in [('SG_ UF', 'SG_UF'), ('CD_FLASCARD_URNA_EFETIVADA', 'CD_FLASHCARD_URNA_EFETIVADA')]:
        if old in columns:
            if new in columns:
                frame = frame.with_columns(pl.coalesce(pl.col(new), pl.col(old)).alias(new)).drop(old)
            else:
                frame = frame.rename({old: new})
    columns = frame.collect_schema().names()
    description = pl.col('DS_ELEICAO').cast(pl.String).str.to_lowercase() if 'DS_ELEICAO' in columns else pl.lit(None, dtype=pl.String)
    inferred_type = (
        pl.when(description.str.contains('plebiscito|referendo')).then(pl.lit('2'))
        .when(description.str.contains('suplementar|extraordin')).then(pl.lit('1'))
        .when(description.str.contains('geral|gerais|municipa|conselho distrital|ordinária')).then(pl.lit('0'))
        .otherwise(pl.lit(None, dtype=pl.String))
    )
    raw_type = pl.col('CD_TIPO_ELEICAO').cast(pl.String).str.strip_chars() if 'CD_TIPO_ELEICAO' in columns else pl.lit(None, dtype=pl.String)
    defaults = {
        'SG_UF': None, 'CD_FLASHCARD_URNA_EFETIVADA': None,
        'DT_ABERTURA': None, 'DT_ENCERRAMENTO': None, 'DT_EMISSAO_BU': None,
        'DT_BU_RECEBIDO': None, 'CD_ELEICAO': '0', 'NR_TURNO': '1',
    }
    return frame.with_columns(
        pl.coalesce(raw_type, inferred_type).alias('tipo_eleicao_normalizado'),
        *[(pl.col(name).cast(pl.String) if name in columns else pl.lit(value, dtype=pl.String)).alias(name)
          for name, value in defaults.items()],
    )
