"""TSE source codes mapped to the public party-directory vocabulary."""
from avoar.core.opendata.political_parties.domain import AbrangenciaDiretorio, TipoDiretorio


tse_codigo_para_abrangencia_diretorio = {
    81: AbrangenciaDiretorio.NACIONAL,
    82: AbrangenciaDiretorio.ESTADUAL,
    83: AbrangenciaDiretorio.MUNICIPAL,
    84: AbrangenciaDiretorio.REGIONAL,
    85: AbrangenciaDiretorio.ZONAL
}

tse_codigo_para_tipo_diretorio = {
    169: TipoDiretorio.ORGAO_DEFINITIVO,
    471: TipoDiretorio.COMISSAO_EXECUTIVA,
    472: TipoDiretorio.ORGAO_PROVISORIO,
    473: TipoDiretorio.COMISSAO_INTERVENTORA
}
