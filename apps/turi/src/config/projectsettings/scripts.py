"""Paths shared by multiple operation scripts. Script metadata lives in its producer."""
from config.projectsettings.settings import BASE_DIR, DUMPS_OUTPUT_DIR


SDS_MUNICIPALITIES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_municipality"
    / "municipalities_centroid.parquet"
)
CD_LEGISLATURES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_legislature"
    / "camaradosdeputados_legislatures.parquet"
)
ELECTIONS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_election"
    / "opendata_election.parquet"
)
ELECTIONS_ROUNDS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_election_round"
    / "opendata_election_round.parquet"
)
PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_public_people_identificators"
    / "camaradosdeputados.parquet"
)
CANDIDATURES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_candidature"
    / "opendata_candidature.parquet"
)
CD_MANDATES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_mandate"
    / "camaradosdeputados.parquet"
)
TSE_MUNICIPALITIES_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "municipalities"
CD_DEPUTIES_HISTORY_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_history"
    / "*.parquet"
)
IBGE_ADDRESSES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_address"
    / "opendata_address.parquet"
)
