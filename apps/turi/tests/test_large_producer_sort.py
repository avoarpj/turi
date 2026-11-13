from decimal import Decimal
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal

from config.projectsettings.settings import NUMERIC_HASH_SEED
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS
from scripts.operations.address import address
from scripts.operations.business import business, establishments, partners, partnerships


class LargeProducerSortTests(unittest.TestCase):
    def test_partners_keep_global_uniqueness_and_partnerships_keep_cross_file_duplicates(self):
        row = {
            "cnpj_basico": "00000001", "identificador_de_socio": "2", "nome_do_socio": "Árvore",
            "cnpjcpf_socio": "***000123**", "faixa_etaria_socio": "5", "representante_legal": None,
            "nome_representante_legal": None, "qualificacao_representante_legal": None,
            "qualificacao_socio": "49", "data_de_entrada_sociedade": "20200101",
        }
        foreign = dict(row, identificador_de_socio="3", nome_do_socio="Externo", cnpjcpf_socio="AB-001")
        legal = dict(row, identificador_de_socio="1", nome_do_socio="Empresa", cnpjcpf_socio="00000002000199")
        schema = dict.fromkeys(row, pl.String)
        first = pl.DataFrame([row, row, foreign, legal], schema=schema)
        second = pl.DataFrame([dict(row, cnpj_basico="00000003"), foreign], schema=schema)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            first.write_parquet(raw / "a.parquet")
            second.write_parquet(raw / "b.parquet")
            logger = getLogger(__name__)

            for module, prefix, key in [
                (partners, "RECEITAFEDERAL_PARTNERS", "opendata_partner"),
                (partnerships, "RECEITAFEDERAL_PARTNERSHIP", "opendata_partnerhip"),
            ]:
                destination = root / f"{key}.parquet"
                with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                    module,
                    **{f"{prefix}_RAW_PARQUETS": raw / "*.parquet", f"{prefix}_OUTPUT_PARQUETS": destination},
                ):
                    module.script_instance.process_data(logger)

                expected = pl.concat([
                    module.script_instance._process_lf(frame.lazy(), logger) for frame in [first, second]
                ], how="diagonal_relaxed")
                if module is partners:
                    expected = expected.unique(subset="id").select("id", "nome", "documento", "faixa_etaria")
                expected = expected.sort(FINAL_PARQUET_SORT_KEYS[key]).collect()
                actual = pl.read_parquet(destination)
                assert_frame_equal(actual, expected)

                if module is partners:
                    self.assertEqual(actual.height, 1)
                    self.assertEqual(actual["documento"].to_list(), ["000123"])
                else:
                    self.assertEqual(actual.height, 5)
                    self.assertEqual(actual.filter(pl.col("socio_id").is_null()).height, 2)

                self.assertEqual(list((root / "work").iterdir()), [])

    def test_establishments_keep_lists_dates_ids_and_municipality_join_multiplicity(self):
        row = dict.fromkeys([
            "municipio", "cnpj_basico", "cnpj_ordem", "cnpj_dv", "situacao_cadastral",
            "data_situacao_cadastral", "data_de_inicio_atividade", "cnae_fiscal_principal",
            "cnae_fiscal_secundaria", "ddd_1", "telefone_1", "ddd_2", "telefone_2", "ddd_fax",
            "fax", "data_situacao_especial", "cep", "numero", "indicador_matriz_ou_filial",
            "nome_fantasia", "motivo_situacao_cadastral", "nome_da_cidade_no_exterior", "pais",
            "tipo_de_logradouro", "logradouro", "complemento", "bairro", "correio_eletronico",
            "uf", "situacao_especial",
        ], "")
        row.update({
            "municipio": "1001", "cnpj_basico": "00000001", "cnpj_ordem": "0001", "cnpj_dv": "09",
            "situacao_cadastral": "02", "data_situacao_cadastral": "20240101",
            "data_de_inicio_atividade": "20000101", "data_situacao_especial": None,
            "cnae_fiscal_principal": "0123456", "cnae_fiscal_secundaria": "7654321,0123456",
            "ddd_1": "11", "telefone_1": "123", "cep": "00012345", "numero": "01",
            "indicador_matriz_ou_filial": "1", "nome_fantasia": "Teste", "uf": "AC",
        })
        schema = dict.fromkeys(row, pl.String)
        first = pl.DataFrame([row, row], schema=schema)
        second = pl.DataFrame([dict(row, cnpj_ordem="0002", cnpj_dv="10")], schema=schema)
        municipalities = pl.DataFrame({
            "codigo_ibge": ["1200138", "1200179"], "codigo_siafi": ["1001", "1001"],
        })

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            first.write_parquet(raw / "a.parquet")
            second.write_parquet(raw / "b.parquet")
            mapping = root / "municipalities.parquet"
            municipalities.write_parquet(mapping)
            destination = root / "output" / "establishments.parquet"
            logger = getLogger(__name__)

            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                establishments,
                RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_RAW_PARQUETS=raw / "*.parquet",
                GOV_MUNICIPALITIES_RAW_PARQUETS=mapping,
                RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_OUTPUT_PARQUETS=destination,
            ):
                establishments.script_instance.process_data(logger)

            expected = pl.concat([
                establishments.script_instance._process_lf(frame.lazy(), municipalities.lazy(), logger)
                for frame in [first, second]
            ], how="diagonal_relaxed").collect()
            actual = pl.read_parquet(destination)
            assert_frame_equal(actual.sort("id", "endereco_municipio"), expected.sort("id", "endereco_municipio"))
            self.assertEqual(actual.height, 6)
            self.assertEqual(actual["cnaes"].to_list(), [["0123456", "7654321"]] * 6)
            self.assertEqual(list((root / "work").iterdir()), [])

    def test_business_preserves_decimals_leading_zeros_ids_and_duplicate_rows(self):
        row = {
            "cnpj_basico": "00000001", "razao_social": "Empresa A", "natureza_juridica": "2062",
            "qualificacao_do_responsavel": "49", "capital_social": "1,25", "porte": "01",
            "ente_federativo_responsavel": "",
        }
        rows = [row, dict(row, cnpj_basico="00000002", razao_social="Empresa B", capital_social="0,00"), row]

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            pl.DataFrame(rows[:2]).write_parquet(raw / "a.parquet")
            pl.DataFrame(rows[2:]).write_parquet(raw / "b.parquet")
            destination = root / "output" / "business.parquet"

            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                business,
                RECEITAFEDERAL_BUSINESS_RAW_PARQUETS=raw / "*.parquet",
                RECEITAFEDERAL_BUSINESS_OUTPUT_PARQUETS=destination,
            ):
                business.script_instance.process_data(getLogger(__name__))

            actual = pl.read_parquet(destination)
            ids = pl.Series([row["cnpj_basico"] for row in rows]).hash(seed=NUMERIC_HASH_SEED).to_list()
            expected = pl.DataFrame({
                "id": pl.Series(ids, dtype=pl.UInt64),
                "base_cnpj": [row["cnpj_basico"] for row in rows],
                "razao_social": [row["razao_social"] for row in rows],
                "natureza_juridica": ["2062"] * 3,
                "qualificacao_responsavel": ["49"] * 3,
                "capital_social": pl.Series([Decimal("1.25"), Decimal("0.00"), Decimal("1.25")], dtype=pl.Decimal(18, 2)),
                "porte": ["01"] * 3,
                "ente_federativo": pl.Series([None] * 3, dtype=pl.String),
            }).sort("id")
            assert_frame_equal(actual, expected)
            self.assertEqual(list((root / "work").iterdir()), [])

    def test_addresses_keep_all_fields_and_complement_multiplicity_across_sources(self):
        row = dict.fromkeys([
            "COD_UNICO_ENDERECO", "COD_MUNICIPIO", "COD_DISTRITO", "COD_SUBDISTRITO",
            "COD_SETOR", "NUM_QUADRA", "NUM_FACE", "CEP", "DSC_LOCALIDADE", "NOM_TIPO_SEGLOGR",
            "NOM_TITULO_SEGLOGR", "NOM_SEGLOGR", "NUM_ENDERECO", "DSC_MODIFICADOR", "LATITUDE",
            "LONGITUDE", "NV_GEO_COORD", "COD_ESPECIE", "DSC_ESTABELECIMENTO",
            "COD_INDICADOR_ESTAB_ENDERECO", "COD_INDICADOR_CONST_ENDERECO", "COD_TIPO_ESPECI",
            "COD_INDICADOR_FINALIDADE_CONST",
        ], "")
        row.update({
            "COD_UNICO_ENDERECO": "a", "COD_MUNICIPIO": "1200138", "CEP": "00012345",
            "NUM_ENDERECO": "01", "LATITUDE": "1,25", "LONGITUDE": "-2,5",
            "NV_GEO_COORD": "1", "COD_ESPECIE": "1", "COD_TIPO_ESPECI": "101",
        })

        for index in range(1, 6):
            row[f"NOM_COMP_ELEM{index}"] = "APTO" if index <= 2 else ""
            row[f"VAL_COMP_ELEM{index}"] = "2" if index <= 2 else ""

        first = pl.DataFrame([row, row])
        second_row = dict(row, COD_UNICO_ENDERECO="b", CEP="", NUM_ENDERECO="2")
        for index in range(1, 6):
            second_row[f"NOM_COMP_ELEM{index}"] = ""
            second_row[f"VAL_COMP_ELEM{index}"] = ""
        second = pl.DataFrame([second_row])

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            first.write_parquet(raw / "a.parquet")
            second.write_parquet(raw / "b.parquet")
            destination = root / "output" / "addresses.parquet"
            complements = root / "output" / "complements.parquet"
            logger = getLogger(__name__)

            with patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(root / "work")}), patch.multiple(
                address,
                IBGE_ADDRESSES_RAW_PARQUETS=raw / "*.parquet",
                IBGE_ADDRESSES_OUTPUT_PARQUETS=destination,
                IBGE_ADDRESSES_COMPLEMENTS_OUTPUT_PARQUETS=complements,
            ):
                address.script_instance.process_data(logger)

            transformed = [address.script_instance._process_lf(frame.lazy(), logger) for frame in [first, second]]
            for index, path, key in [
                (0, destination, "opendata_address"),
                (1, complements, "opendata_address_complement"),
            ]:
                expected = pl.concat([pair[index] for pair in transformed], how="diagonal_relaxed")
                expected = expected.sort(FINAL_PARQUET_SORT_KEYS[key]).collect()
                assert_frame_equal(pl.read_parquet(path), expected)

            self.assertEqual(pl.read_parquet(destination).height, 3)
            self.assertEqual(pl.read_parquet(complements).height, 4)
            self.assertEqual(list((root / "work").iterdir()), [])
