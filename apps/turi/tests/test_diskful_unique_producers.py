from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal

from config.projectsettings.settings import NUMERIC_HASH_SEED
from scripts.operations.evm import evm, evm_bulletin


def _bulletin(urn: str, municipality: str) -> dict:
    return {
        "NR_URNA_EFETIVADA": urn,
        "CD_MUNICIPIO": municipality,
        "CD_TIPO_ELEICAO": "2",
        "CD_ELEICAO": "100",
        "NR_TURNO": "1",
        "NR_ZONA": "1",
        "NR_SECAO": urn,
        "NR_LOCAL_VOTACAO": "1",
        "DT_ABERTURA": "02/10/2022 08:00:00",
        "DT_ENCERRAMENTO": "02/10/2022 17:00:00",
        "DT_EMISSAO_BU": "02/10/2022 17:01:00",
        "DT_BU_RECEBIDO": "02/10/2022 17:02:00",
        "QT_APTOS": "100",
        "QT_COMPARECIMENTO": "90",
        "QT_ABSTENCOES": "10",
        "CD_FLASHCARD_URNA_EFETIVADA": "flash-" + urn,
        "CD_CARGA_1_URNA_EFETIVADA": "a",
        "CD_CARGA_2_URNA_EFETIVADA": "b",
    }


class DiskfulUniqueProducerTests(unittest.TestCase):
    def test_lookup_validation_rejects_ambiguous_matches_and_ignores_null_keys(self):
        raw = pl.LazyFrame([_bulletin("1", "1007")])
        ambiguous = pl.LazyFrame({
            "CD_MUNICIPIO_TSE": ["1007", "1007"],
            "CD_MUNICIPIO_IBGE": ["1200138", "1200179"],
        })

        with self.assertRaisesRegex(pl.exceptions.ComputeError, "m:1 validation"):
            evm_bulletin._process_data(raw, ambiguous).collect()

        null_keys = pl.LazyFrame({
            "CD_MUNICIPIO_TSE": ["1007", None, None],
            "CD_MUNICIPIO_IBGE": ["1200138", "unknown-a", "unknown-b"],
        })
        actual = evm_bulletin._process_data(raw, null_keys).collect(engine="streaming")
        self.assertEqual(actual["codigo_municipio_ibge"].to_list(), ["1200138"])

    def test_real_producers_preserve_ids_values_locality_rules_and_cleanup(self):
        conflicting_metadata = dict(_bulletin("1", "1007"), DT_BU_RECEBIDO="02/10/2022 18:00:00")
        first = pl.DataFrame(
            [_bulletin("1", "1007")] * 3 + [conflicting_metadata, _bulletin("2", "1007")]
        )
        second = pl.DataFrame([_bulletin("1", "1015"), _bulletin("2", "1007")])
        municipalities = pl.DataFrame({
            "CD_MUNICIPIO_TSE": ["1007", "1015"],
            "CD_MUNICIPIO_IBGE": ["1200138", "1200179"],
        })

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            mapping = root / "municipalities"
            raw.mkdir()
            mapping.mkdir()
            first.write_parquet(raw / "a.parquet", row_group_size=1)
            second.write_parquet(raw / "b.parquet", row_group_size=1)
            municipalities.write_parquet(mapping / "mapping.parquet")
            urn_output = root / "urns.parquet"
            bulletin_output = root / "bulletins.parquet"

            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                evm, EVM_RAW_PARQUETS=raw, EVM_OUTPUT_PARQUETS=urn_output,
            ), patch.multiple(
                evm_bulletin,
                EVM_BULLETINS_RAW_PARQUETS=raw,
                EVM_BULLETINS_OUTPUT_PARQUETS=bulletin_output,
                TSE_MUNICIPALITIES_RAW_PARQUETS=mapping,
            ):
                evm.EvmDataScript().process_data(getLogger(__name__))
                evm_bulletin.EvmBulletinDataScript().process_data(getLogger(__name__))

            raw_frame = pl.concat([first, second]).lazy()
            expected_urns = raw_frame.select("NR_URNA_EFETIVADA").unique().select(
                pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                pl.col("NR_URNA_EFETIVADA").alias("numero_serie_urna"),
            ).sort("id").collect()
            assert_frame_equal(pl.read_parquet(urn_output), expected_urns)

            processed = evm_bulletin._process_data(raw_frame, municipalities.lazy())
            localities = processed.group_by("id").agg(
                pl.when(pl.col("codigo_municipio_ibge").drop_nulls().n_unique() == 1)
                .then(pl.col("codigo_municipio_ibge").drop_nulls().first())
                .otherwise(pl.lit(None, dtype=pl.String))
                .alias("codigo_municipio_ibge")
            )
            expected_bulletins = (
                processed.drop("codigo_municipio_ibge")
                .unique(subset="id", keep="first")
                .join(localities, on="id", how="left", validate="1:1")
                .sort(["zona_eleitoral", "local_votacao", "secao_eleitoral", "data_abertura", "urna_id"])
                .collect()
            )
            actual = pl.read_parquet(bulletin_output)
            assert_frame_equal(actual, expected_bulletins)
            self.assertEqual(actual["codigo_municipio_ibge"].null_count(), 1)
            self.assertEqual(list((root / "work").iterdir()), [])

    def test_per_file_urn_reduction_keeps_global_types_and_leading_zeros(self):
        first = pl.DataFrame({"NR_URNA_EFETIVADA": [-0.0, 0.0, 1.0, 1.0]})
        second = pl.DataFrame({"NR_URNA_EFETIVADA": ["0001", "1", "3", "3"]})

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            first.write_parquet(raw / "a.parquet")
            second.write_parquet(raw / "b.parquet")
            destination = root / "urns.parquet"

            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                evm, EVM_RAW_PARQUETS=raw, EVM_OUTPUT_PARQUETS=destination,
            ):
                evm.EvmDataScript().process_data(getLogger(__name__))

            expected = pl.concat([first.lazy(), second.lazy()], how="diagonal_relaxed").select(
                pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                pl.col("NR_URNA_EFETIVADA").alias("numero_serie_urna"),
            ).unique().sort("id").collect()
            assert_frame_equal(pl.read_parquet(destination), expected)
            self.assertEqual(expected.height, 6)
