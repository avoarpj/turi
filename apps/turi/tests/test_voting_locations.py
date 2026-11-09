from datetime import date
from zoneinfo import ZoneInfo
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import polars as pl

from avoar.core.opendata.voting_location.domain import LocalVotacao
from avoar.core.validation import date_value, timestamp_value, validate
from scripts.operations.voting_locations import locations


def row(**changes):
    values = {
        "DT_GERACAO": "01/11/2022", "HH_GERACAO": "10:00:00",
        "AA_ELEICAO": "2022", "DT_ELEICAO": "02/10/2022", "NR_TURNO": "1",
        "SG_UF": "SP", "CD_MUNICIPIO": "71072", "NR_ZONA": "001", "NR_SECAO": "1",
        "NR_LOCAL_VOTACAO": "01015", "NM_LOCAL_VOTACAO": "Escola São José",
        "DS_ENDERECO": "RUA DAS FLORES, 15", "NM_BAIRRO": "CENTRO", "NR_CEP": "01001000",
        "NR_LATITUDE": "-23,5505", "NR_LONGITUDE": "-46,6333",
        "CD_SITU_LOCAL_VOTACAO": "1", "QT_ELEITOR_SECAO": "500",
    }
    values.update(changes)
    return values


def observations(rows):
    normalized = locations.normalize_locations(pl.LazyFrame(rows)).collect()
    return locations.consolidate_observations(normalized)


class VotingLocationsTests(TestCase):
    def test_identity_normalizes_numbers_and_distinguishes_scope(self):
        rows = [
            row(), row(NR_ZONA="1", NR_LOCAL_VOTACAO="1015"),
            row(NR_ZONA="2"), row(CD_MUNICIPIO="71080"), row(SG_UF="RJ"),
        ]
        normalized = locations.normalize_locations(pl.LazyFrame(rows)).collect()
        self.assertEqual(normalized["id"][0], normalized["id"][1])
        self.assertEqual(normalized["id"].n_unique(), 4)

    def test_sections_deduplicate_but_dates_and_rounds_remain(self):
        result = observations([
            row(), row(NR_SECAO="2"),
            row(NR_TURNO="2", DT_ELEICAO="30/10/2022"),
            row(AA_ELEICAO="2018", DT_ELEICAO="07/10/2018", DS_ENDERECO="RUA ANTIGA, 10"),
        ])
        self.assertEqual(result.height, 3)
        self.assertEqual(result["id"].n_unique(), 1)
        self.assertNotIn("QT_ELEITOR_SECAO", result.columns)
        self.assertNotIn("NR_SECAO", result.columns)

    def test_latest_snapshot_supersedes_old_metadata_without_mixing_rows(self):
        result = observations([
            row(DT_GERACAO="01/10/2022", DS_ENDERECO="RUA ANTIGA, 10"),
            row(), row(NR_SECAO="2", NM_BAIRRO=None),
        ])
        self.assertEqual(result.height, 1)
        self.assertEqual(result["endereco"][0], "RUA DAS FLORES, 15")
        self.assertEqual(result["bairro"][0], "CENTRO")

    def test_conflicting_sections_preserve_the_place_and_mark_unknown_fields(self):
        for changes in [
            {"DS_ENDERECO": "RUA OUTRA, 15"},
            {"NR_LATITUDE": "-22.5"},
        ]:
            with self.subTest(changes=changes):
                result = observations([row(), row(NR_SECAO="2", **changes)])
                self.assertEqual(result.height, 1)
                if "DS_ENDERECO" in changes:
                    self.assertIsNone(result["endereco"][0])
                    self.assertEqual(result["campos_divergentes"][0].to_list(), ["endereco"])
                else:
                    self.assertIsNone(result["latitude_tse"][0])
                    self.assertIsNone(result["longitude_tse"][0])
                    self.assertEqual(result["campos_divergentes"][0].to_list(), ["latitude_tse"])

        result = observations([row(), row(CD_SITU_LOCAL_VOTACAO="5")])
        self.assertIsNone(result["codigo_situacao"][0])
        self.assertEqual(result["latitude_tse"][0], -23.5505)

    def test_invalid_coordinate_pairs_are_null_without_losing_the_place(self):
        for latitude, longitude in [
            ("-1", "-46"), ("-1,0", "-46"), ("-23", None), ("NaN", "-46"),
            ("91", "-46"), ("-23", "181"), ("0", "0"),
        ]:
            with self.subTest(latitude=latitude, longitude=longitude):
                result = observations([row(NR_LATITUDE=latitude, NR_LONGITUDE=longitude)])
                self.assertEqual(result.height, 1)
                self.assertIsNone(result["latitude_tse"][0])
                self.assertIsNone(result["longitude_tse"][0])

        result = observations([row(NR_LATITUDE="0", NR_LONGITUDE="-51")])
        self.assertEqual(result["latitude_tse"][0], 0)

    def test_layout_is_normalized_per_file_and_exterior_is_excluded(self):
        legacy = row()
        legacy["ANO_ELEICAO"] = legacy.pop("AA_ELEICAO")
        for name in ["NR_LATITUDE", "NR_LONGITUDE", "NM_BAIRRO"]:
            legacy.pop(name)

        normalized = locations.normalize_locations(pl.LazyFrame([legacy])).collect()
        self.assertEqual(normalized.height, 1)
        self.assertIsNone(normalized["latitude_tse"][0])
        self.assertTrue(observations([row(SG_UF="ZZ")]).is_empty())

        with self.assertRaisesRegex(ValueError, "incompleto"):
            locations.normalize_locations(pl.LazyFrame([{"SG_UF": "SP"}]))

    def test_invalid_identity_or_temporal_metadata_fails(self):
        for changes in [
            {"SG_UF": "XX"}, {"NR_ZONA": "0"}, {"NR_LOCAL_VOTACAO": None},
            {"DT_ELEICAO": "invalid"}, {"AA_ELEICAO": "2020"}, {"NR_TURNO": "3"},
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "inválida"):
                observations([row(**changes)])

    def test_address_cluster_requires_an_existing_unique_match(self):
        rows = observations([
            row(),
            row(NR_LOCAL_VOTACAO="2", DS_ENDERECO="RODOVIA BR 364 KM 15"),
            row(NR_LOCAL_VOTACAO="3", DS_ENDERECO="RUA OUTRA, 20"),
        ]).with_columns(pl.lit("3550308").alias("codigo_municipio_ibge"))
        addresses = pl.LazyFrame({
            "municipio": ["3550308"] * 4, "cep": ["01001000"] * 4,
            "numero_logradouro": ["15", "015", "20", "20"],
            "cluster_id": [123, 123, 456, 789],
        })
        result = locations.with_address_clusters(rows, addresses).sort("numero")
        self.assertEqual(result["endereco_cluster_id"].to_list(), [123, None, None])
        self.assertTrue((result["latitude_tse"] == -23.5505).all())

    def test_missing_address_catalog_does_not_invent_cluster_ids(self):
        rows = observations([row()])
        result = locations.with_address_clusters(rows, None)
        self.assertIsNone(result["endereco_cluster_id"][0])
        self.assertEqual(result["longitude_tse"][0], -46.6333)

    def test_script_writes_current_and_history_and_preserves_unknown_municipalities(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            mapping = root / "municipalities"
            raw.mkdir()
            mapping.mkdir()
            pl.DataFrame([
                row(), row(NR_SECAO="2"),
                row(AA_ELEICAO="2018", DT_ELEICAO="07/10/2018", DS_ENDERECO="RUA ANTIGA, 10"),
                row(CD_MUNICIPIO="99999"), row(SG_UF="ZZ"),
            ]).write_parquet(raw / "national.parquet")
            # A state copy can overlap another archive member without adding
            # observations, even when its layout omits optional coordinates.
            state_copy = row()
            state_copy["ANO_ELEICAO"] = state_copy.pop("AA_ELEICAO")
            state_copy.pop("NR_LATITUDE")
            state_copy.pop("NR_LONGITUDE")
            pl.DataFrame([state_copy]).write_parquet(raw / "state-copy.parquet")
            pl.DataFrame({
                "CD_MUNICIPIO_TSE": ["71072"], "CD_MUNICIPIO_IBGE": ["3550308"],
            }).write_parquet(mapping / "mapping.parquet")
            outputs = {
                "VOTING_LOCATIONS_RAW_PARQUETS": raw,
                "TSE_MUNICIPALITIES_RAW_PARQUETS": mapping,
                "IBGE_ADDRESSES_OUTPUT_PARQUETS": root / "absent-addresses.parquet",
                "VOTING_LOCATIONS_OUTPUT_PARQUETS": root / "current" / "tse.parquet",
                "VOTING_LOCATIONS_HISTORY_OUTPUT_PARQUETS": root / "history" / "tse.parquet",
            }

            with patch.multiple(locations, **outputs):
                locations.script_instance.process_data(getLogger(__name__))

            current = pl.read_parquet(outputs["VOTING_LOCATIONS_OUTPUT_PARQUETS"])
            history = pl.read_parquet(outputs["VOTING_LOCATIONS_HISTORY_OUTPUT_PARQUETS"])
            self.assertEqual(current.height, 2)
            self.assertEqual(current["id"].n_unique(), 2)
            self.assertEqual(history.height, 3)
            self.assertEqual(current["codigo_municipio_ibge"].null_count(), 1)
            self.assertEqual(set(current["endereco"]), {"RUA DAS FLORES, 15"})
            self.assertEqual(set(history["data_eleicao"]), {date(2018, 10, 7), date(2022, 10, 2)})
            for record in history.to_dicts():
                record = {key: value for key, value in record.items() if value is not None}
                record["data_eleicao"] = date_value(record["data_eleicao"])
                if "data_geracao" in record:
                    generated = record["data_geracao"].replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
                    record["data_geracao"] = timestamp_value(generated)

                validate(LocalVotacao(**record))

            first = current.to_dicts()
            with patch.multiple(locations, **outputs):
                locations.script_instance.process_data(getLogger(__name__))
            self.assertEqual(pl.read_parquet(outputs["VOTING_LOCATIONS_OUTPUT_PARQUETS"]).to_dicts(), first)

            original = outputs["VOTING_LOCATIONS_OUTPUT_PARQUETS"].read_bytes()
            pl.DataFrame([row(NR_ZONA="0")]).write_parquet(raw / "national.parquet")
            with patch.multiple(locations, **outputs), self.assertRaises(ValueError):
                locations.script_instance.process_data(getLogger(__name__))
            self.assertEqual(outputs["VOTING_LOCATIONS_OUTPUT_PARQUETS"].read_bytes(), original)
