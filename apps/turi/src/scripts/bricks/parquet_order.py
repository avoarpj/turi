"""Final clustering keys for datasets whose producers previously omitted sorting."""

FINAL_PARQUET_SORT_KEYS = {
    "opendata_address": (
        "municipio", "cep", "numero_logradouro", "cluster_id", "id",
    ),
    "opendata_address_complement": ("endereco_id", "nome", "valor"),

    "opendata_business": ("id",),
    "opendata_business_establishment": ("empresa_id", "id"),
    "opendata_partner": ("id",),
    "opendata_partnerhip": ("empresa_id", "tipo_socio", "socio_id", "data_entrada"),

    "opendata_amendment_agreement": ("id",),
    "opendata_amendment_to_agreement": ("emenda_id", "convenio_id"),
    "opendata_amendment_authorship": ("mandato_id", "emenda_id", "tipo_autoria"),
    "opendata_amendment_item": ("type", "id"),
    "opendata_amendment_resource": (
        "emenda_id", "codigo_local", "codigo_funcao", "codigo_subfuncao",
        "codigo_programa", "codigo_acao", "codigo_plano_orcamentario",
    ),
    "opendata_amendment_supplier": ("emenda_id", "fornecedor_id", "tipo_documento"),

    "opendata_services_supplier": ("tipo_documento", "documento"),
    "opendata_services_supplier_names": ("fornecedor_id", "nome"),

    "opendata_organ": ("id",),
    "opendata_election_round": ("eleicao_id", "numero_turno", "id"),

    "opendata_voting_location": (
        "codigo_municipio_ibge", "zona_eleitoral", "numero", "id",
    ),
    "opendata_voting_location_history": (
        "ano_referencia", "numero_turno", "codigo_municipio_ibge", "id",
    ),
}
