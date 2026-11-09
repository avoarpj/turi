import polars as pl
import core.events.events as core_events

INICIO_EXERCICIO_CONTAINS = "entrada -"
ALTERACAO_INCLUDES = "alteração"

AFASTAMENTO_COM_PRAZO_INCLUDES = "afastamento com prazo determinado"
AFASTAMENTO_SEM_PRAZO_INCLUDES = "afastamento sem prazo determinado"
AFASTAMENTO_DEFINITIVO_INCLUDES = "afastamento definitivo"

POSSE_TITULAR_INCLUDES = "posse de eleito titular"
REASSUNCAO_MANDATO_INCLUDES = "reassunção"
POSSE_SUPLENTE_INCLUDES = "posse de suplente"

CARGO_EXECUTIVO_INCLUDES = "secretário|ministro|prefeito|governador|conselheiro"
CARGO_LEGISLATIVO_INCLUDES = "deputado estadual"
LICENCA_INCLUDES = "licença"
LICENCA_CONJUNTA_INCLUDES = "afastamento conjunto consecutivo"

TERMINO_LEGISLATURA_INCLUDES = 'término da legislatura'
RENUNCIA_INCLUDES = "renúncia"
APOSENTADORIA_INCLUDES = "aposentadoria"
CASSACAO_INCLUDES = "perda de mandato"
SUSPENSAO_INCLUDES = "suspensão"
FALECIMENTO_INCLUDES = "falecimento"

ALTERACAO_PARTIDO_INCLUDES = "alteração de partido"
ALTERACAO_NOME_PARLAMENTAR_INCLUDES = "alteração de nome parlamentar"

def extract_event_context_expr():
    col = pl.col("descricaoStatus").str.to_lowercase()

    return (
        pl.when(col.str.contains(INICIO_EXERCICIO_CONTAINS))
        .then(core_events.INICIO_EXERCICIO)

        .when(col.str.contains(ALTERACAO_INCLUDES))
        .then(core_events.ALTERACAO)
        
        .when(col.str.contains(AFASTAMENTO_COM_PRAZO_INCLUDES))
        .then(core_events.AFASTAMENTO_COM_PRAZO)

        .when(col.str.contains(AFASTAMENTO_SEM_PRAZO_INCLUDES))
        .then(core_events.AFASTAMENTO_SEM_PRAZO)

        .when(col.str.contains(AFASTAMENTO_DEFINITIVO_INCLUDES))
        .then(core_events.AFASTAMENTO_DEFINITIVO)

        .otherwise(core_events.DIVERSO)
    )
def extract_event_subcontext_expr():
    col = pl.col("descricaoStatus").str.to_lowercase()

    return (
        pl.when(col.str.contains(POSSE_TITULAR_INCLUDES))
        .then(core_events.POSSE_TITULAR)

        .when(col.str.contains(REASSUNCAO_MANDATO_INCLUDES))
        .then(core_events.REASSUNCAO_MANDATO)

        .when(col.str.contains(POSSE_SUPLENTE_INCLUDES))
        .then(core_events.POSSE_SUPLENTE)

        .when(col.str.contains(CARGO_EXECUTIVO_INCLUDES))
        .then(core_events.CARGO_EXECUTIVO)

        .when(col.str.contains(CARGO_LEGISLATIVO_INCLUDES))
        .then(core_events.CARGO_LEGISLATIVO)

        .when(col.str.contains(LICENCA_INCLUDES))
        .then(core_events.LICENCA)

        .when(col.str.contains(LICENCA_CONJUNTA_INCLUDES))
        .then(core_events.LICENCA_CONJUNTA)

        .when(col.str.contains(TERMINO_LEGISLATURA_INCLUDES))
        .then(core_events.TERMINO_LEGISLATURA)

        .when(col.str.contains(RENUNCIA_INCLUDES))
        .then(core_events.RENUNCIA)

        .when(col.str.contains(APOSENTADORIA_INCLUDES))
        .then(core_events.APOSENTADORIA)

        .when(col.str.contains(CASSACAO_INCLUDES))
        .then(core_events.CASSACAO_MANDATO)

        .when(col.str.contains(SUSPENSAO_INCLUDES))
        .then(core_events.SUSPENSAO_MANDATO)

        .when(col.str.contains(FALECIMENTO_INCLUDES))
        .then(core_events.FALECIMENTO)

        .when(col.str.contains(ALTERACAO_PARTIDO_INCLUDES))
        .then(core_events.ALTERACAO_PARTIDO)

        .when(col.str.contains(ALTERACAO_NOME_PARLAMENTAR_INCLUDES))
        .then(core_events.ALTERACAO_NOME_PARLAMENTAR)

        .otherwise(core_events.DIVERSO)
    )