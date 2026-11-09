from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal
import pyarrow.parquet as pq

from infra.parquet_sort import write_sorted_parquets
from scripts.bricks.candidature_identity import election_lookup
from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
from scripts.operations.evm import evm_bulletin_item as items


def vote(number="22", kind="1", quantity="7"):
    return {
        "ANO_ELEICAO": "2022", "SG_UF": "SP", "CD_PLEITO": "1",
        "CD_ELEICAO": "200", "CD_TIPO_ELEICAO": "0", "CD_MUNICIPIO": "1007",
        "CD_CARGO_PERGUNTA": "6", "CD_TIPO_VOTAVEL": kind,
        "NR_VOTAVEL": number, "NR_ZONA": "1", "NR_SECAO": "1",
        "NR_LOCAL_VOTACAO": "1", "NR_URNA_EFETIVADA": "1",
        "NR_TURNO": "1", "QT_VOTOS": quantity,
        "CD_FLASHCARD_URNA_EFETIVADA": "a",
        "CD_CARGA_1_URNA_EFETIVADA": "b", "CD_CARGA_2_URNA_EFETIVADA": "c",
    }


class BulletinItemsStreamingTests(unittest.TestCase):
    def test_complete_producer_matches_global_schema_and_preserves_duplicate_votes(self):
        first = pl.DataFrame([vote(), vote(), vote("95", "2", "3"), dict(vote(), CD_TIPO_ELEICAO="2")])
        second = pl.DataFrame([vote("1111"), vote("99999")]).rename({
            "SG_UF": "SG_ UF",
            "CD_FLASHCARD_URNA_EFETIVADA": "CD_FLASCARD_URNA_EFETIVADA",
        }).with_columns(pl.col("QT_VOTOS").cast(pl.Int64), pl.col("NR_VOTAVEL").cast(pl.Int32))
        municipalities = pl.DataFrame({"CD_MUNICIPIO_TSE": ["1007"], "CD_MUNICIPIO_IBGE": ["1200138"]})
        elections = pl.DataFrame({"id": [2**63 + 1], "codigo_local": ["SP"]})
        rounds = pl.DataFrame({"codigo_tse": [200], "eleicao_id": [2**63 + 1]})
        candidates = pl.DataFrame({
            "id": [2**63 + 2, 2**63 + 3, 2**63 + 4],
            "eleicao_id": [2**63 + 1] * 3, "codigo_local": ["SP"] * 3,
            "codigo_cargo_tse": [6] * 3, "numero_candidato": [22, 1111, 1111],
        })

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            first.write_parquet(raw / "first.parquet", row_group_size=1)
            second.write_parquet(raw / "second.parquet", row_group_size=1)
            mapping = root / "municipalities"
            mapping.mkdir()
            municipalities.write_parquet(mapping / "mapping.parquet")
            paths = {}

            for name, frame in (("elections", elections), ("rounds", rounds), ("candidates", candidates)):
                paths[name] = root / f"{name}.parquet"
                frame.write_parquet(paths[name])

            output = root / "items.parquet"
            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                items,
                EVM_BULLETIN_ITEMS_RAW_PARQUETS=raw,
                EVM_BULLETIN_ITEMS_OUTPUT_PARQUETS=output,
                TSE_MUNICIPALITIES_RAW_PARQUETS=mapping,
                ELECTIONS_OUTPUT_PARQUETS=paths["elections"],
                ELECTIONS_ROUNDS_OUTPUT_PARQUETS=paths["rounds"],
                CANDIDATURES_OUTPUT_PARQUETS=paths["candidates"],
            ):
                items.EvmBulletinItemDataScript().process_data(getLogger(__name__))

            global_raw = pl.concat(
                [normalize_tse_bulletin(first.lazy()), normalize_tse_bulletin(second.lazy())],
                how="diagonal_relaxed",
            ).filter(~pl.col("tipo_eleicao_normalizado").is_in(["2"]))
            expected = items._process_data(
                global_raw, municipalities.lazy(), election_lookup(rounds.lazy(), elections.lazy()),
                candidates.lazy(),
            ).collect()
            actual = pl.read_parquet(output)

            assert_frame_equal(actual.sort(actual.columns), expected.sort(expected.columns))
            self.assertEqual(actual.height, 5)
            self.assertEqual(actual["quantidade"].sum(), 31)
            self.assertEqual(actual.filter(pl.col("candidatura_id") == 2**63 + 2).height, 2)
            self.assertEqual(list((root / "work").iterdir()), [])

    def test_external_sort_audit_failure_preserves_published_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.parquet"
            destination = root / "published.parquet"
            pl.DataFrame({"id": [3, 1, 1], "quantidade": [7, 2, 2]}).write_parquet(source)
            original = b"previous published content"
            destination.write_bytes(original)

            with self.assertRaisesRegex(ValueError, "audit failed"):
                write_sorted_parquets(
                    str(source), destination, ["id"], schema=pq.read_schema(source),
                    work_directory=root, expected_rows=3, expected_totals={"quantidade": 12},
                    memory_limit="32MiB",
                )

            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["published.parquet", "source.parquet"])
