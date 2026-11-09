from datetime import date
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import polars as pl

from avoar.core.opendata.pleito.domain import Pleito
from avoar.core.validation import date_value, validate
from scripts.bricks.candidature_identity import election_id_expr
from scripts.bricks.pleito_identity import build_pleitos
from scripts.operations.election import elections


def metadata(locality, day, turn=1, kind="0", year=2024):
    return {
        "ano_eleicao": date(year, 1, 1), "codigo_local": locality,
        "DT_PLEITO": day, "NR_TURNO": str(turn),
        "tipo_eleicao_normalizado": kind,
    }


class PleitosTest(TestCase):
    def test_event_groups_localities_and_both_rounds(self):
        rows = [
            metadata("2611606", "06/10/2024"),
            metadata("3550308", "06/10/2024"),
            metadata("2611606", "27/10/2024", turn=2),
            metadata("3550308", "27/10/2024", turn=2),
        ]
        pleitos, lookup = build_pleitos(pl.LazyFrame(rows + rows))
        result = pleitos.collect()
        self.assertEqual(result.height, 1)
        self.assertEqual(lookup.collect()["pleito_id"].n_unique(), 1)
        self.assertEqual(result["data_inicio"][0], date(2024, 10, 6))
        self.assertNotIn("codigo_local", result.columns)
        record = result.row(0, named=True)
        record["data_inicio"] = date_value(record["data_inicio"])
        validate(Pleito(**record))

        first_round_only, _ = build_pleitos(pl.LazyFrame(rows[:2]))
        self.assertEqual(result.to_dicts(), first_round_only.collect().to_dicts())

        reversed_result, _ = build_pleitos(pl.LazyFrame(list(reversed(rows))))
        self.assertEqual(result.to_dicts(), reversed_result.collect().to_dicts())

    def test_general_elections_group_national_and_state_disputes(self):
        rows = [metadata(locality, "02/10/2022", year=2022) for locality in ["BR", "SP", "RJ"]]
        result, _ = build_pleitos(pl.LazyFrame(rows))
        self.assertEqual(result.collect().height, 1)

    def test_supplementary_events_are_separate_from_ordinary_and_other_dates(self):
        rows = [
            metadata("2611606", "06/10/2024"),
            metadata("2611606", "2024-03-03", kind="1"),
            metadata("2611606", "2024-03-24", kind="1", turn=2),
            metadata("2611606", "2024-06-02", kind="1"),
            metadata("3550308", "2024-06-02", kind="1"),
        ]
        pleitos, lookup = build_pleitos(pl.LazyFrame(rows))
        result = pleitos.collect()
        self.assertEqual(result.height, 3)
        links = lookup.collect()
        march = links.filter(pl.col("DT_PLEITO").str.starts_with("2024-03"))
        self.assertEqual(march["pleito_id"].n_unique(), 1)
        self.assertEqual(result.filter(pl.col("tipo") == 2).height, 2)

    def test_incomplete_or_invalid_metadata_is_rejected(self):
        for rows in [
            [metadata("SP", "not-a-date")],
            [metadata("SP", "27/10/2024", turn=2)],
            [metadata("SP", "06/10/2024", kind="unknown")],
        ]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                build_pleitos(pl.LazyFrame(rows))

    def test_script_writes_linked_outputs_without_changing_election_ids(self):
        rows = []
        for municipality in ["1007", "1015"]:
            for turn, code, day in [(1, "426", "06/10/2024"), (2, "427", "27/10/2024")]:
                rows.append({
                    "ANO_ELEICAO": "2024", "CD_MUNICIPIO": municipality,
                    "CD_CARGO_PERGUNTA": "11", "SG_UF": "AC", "CD_ELEICAO": code,
                    "DT_PLEITO": day, "NR_TURNO": str(turn), "tipo_eleicao_normalizado": "0",
                })

        with TemporaryDirectory() as directory:
            root = Path(directory)
            municipalities = root / "municipalities"
            municipalities.mkdir()
            pl.DataFrame({
                "CD_MUNICIPIO_TSE": ["1007", "1015"],
                "CD_MUNICIPIO_IBGE": ["1200138", "1200179"],
            }).write_parquet(municipalities / "mapping.parquet")
            legislatures = root / "legislatures.parquet"
            pl.DataFrame({
                "id": [57], "orgao_id": ["cd"], "data_inicio": [date(2023, 1, 1)],
            }).write_parquet(legislatures)
            outputs = {
                "PLEITOS_OUTPUT_PARQUETS": root / "opendata_pleito" / "pleitos.parquet",
                "ELECTIONS_OUTPUT_PARQUETS": root / "opendata_election" / "elections.parquet",
                "ELECTIONS_ROUNDS_OUTPUT_PARQUETS": root / "opendata_election_round" / "rounds.parquet",
                "TSE_MUNICIPALITIES_RAW_PARQUETS": municipalities,
                "CD_LEGISLATURES_OUTPUT_PARQUETS": legislatures,
            }

            with patch.multiple(elections, **outputs), patch.object(
                elections, "_scan_tse_bulletins_dynamic", return_value=pl.LazyFrame(rows),
            ):
                elections.ElectionsDataScript().process_data(getLogger(__name__))

            # Reusing a historical election code for distinct events must fail
            # before any output replaces the valid files.
            ambiguous = [
                dict(rows[0], DT_PLEITO=day, tipo_eleicao_normalizado="1")
                for day in ["03/03/2024", "02/06/2024"]
            ]
            with patch.multiple(elections, **outputs), patch.object(
                elections, "_scan_tse_bulletins_dynamic", return_value=pl.LazyFrame(ambiguous),
            ), self.assertRaisesRegex(ValueError, "multiple pleitos"):
                elections.ElectionsDataScript().process_data(getLogger(__name__))

            pleitos = pl.read_parquet(outputs["PLEITOS_OUTPUT_PARQUETS"])
            elected = pl.read_parquet(outputs["ELECTIONS_OUTPUT_PARQUETS"])
            rounds = pl.read_parquet(outputs["ELECTIONS_ROUNDS_OUTPUT_PARQUETS"])
            self.assertEqual(pleitos.height, 1)
            self.assertEqual(elected.height, 4)
            self.assertEqual(rounds.height, 4)
            self.assertEqual(set(elected["pleito_id"]), set(pleitos["id"]))
            self.assertTrue(set(rounds["eleicao_id"]).issubset(set(elected["id"])))

            expected = pl.DataFrame([
                {"ano_eleicao": date(2024, 1, 1), "codigo_local": locality, "codigo_tse": code}
                for locality in ["1200138", "1200179"] for code in [426, 427]
            ]).select(election_id_expr()).to_series()
            self.assertEqual(set(elected["id"]), set(expected))
