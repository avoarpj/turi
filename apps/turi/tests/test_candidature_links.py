import unittest

import polars as pl

from scripts.bricks.candidature_identity import candidature_id_expr, election_lookup
from scripts.bricks.candidature_identity import election_id_expr, election_round_id_expr
from scripts.operations.evm.evm_bulletin import _process_data as bulletins, _consolidate_bulletins
from scripts.bricks.evm_bulletin_vote_type_expr import tse_evm_bulletin_vote_type_expr
from avoar.core.opendata.evm.domain import TipoItemBoletim
from scripts.operations.candidatures.candidatures import _process_data as candidatures
from scripts.operations.evm.evm_bulletin_item import _process_data as bulletin_items


def candidate(election, locality, role, number, person, uf="SP", sequence="1"):
    return {
        "CD_ELEICAO": str(election), "SG_UE": locality, "CD_CARGO": str(role),
        "NR_CANDIDATO": str(number), "SG_UF": uf, "SQ_CANDIDATO": sequence,
        "NR_TITULO_ELEITORAL_CANDIDATO": person, "NR_CPF_CANDIDATO": person,
        "NM_CANDIDATO": person, "DT_NASCIMENTO": "01/01/1980",
        "SG_PARTIDO": "P", "NR_PARTIDO": "22",
    }


def vote(election, municipality, role, number, kind="1", uf="SP"):
    return {
        "CD_PLEITO": "1", "CD_ELEICAO": str(election), "SG_UF": uf,
        "CD_MUNICIPIO": municipality, "CD_CARGO_PERGUNTA": str(role),
        "CD_TIPO_VOTAVEL": kind, "NR_VOTAVEL": str(number),
        "NR_ZONA": "1", "NR_SECAO": "1", "NR_LOCAL_VOTACAO": "1",
        "NR_URNA_EFETIVADA": "1", "NR_TURNO": "1", "QT_VOTOS": "7",
        "CD_FLASHCARD_URNA_EFETIVADA": "a", "CD_CARGA_1_URNA_EFETIVADA": "b",
        "CD_CARGA_2_URNA_EFETIVADA": "c",
    }


class CandidatureLinksTest(unittest.TestCase):
    def setUp(self):
        self.municipalities = pl.LazyFrame({
            "CD_MUNICIPIO_TSE": ["01007", "01015"],
            "CD_MUNICIPIO_IBGE": ["1200138", "1200179"],
        })
        self.elections = pl.DataFrame({
            "codigo_tse": [100, 101, 200, 200, 300, 300],
            "codigo_local": ["BR", "BR", "SP", "RJ", "1200138", "1200179"],
            "eleicao_id": [2**63 + 1, 2**63 + 2, 3, 4, 5, 6],
        }, schema_overrides={"codigo_tse": pl.Int32, "eleicao_id": pl.UInt64}).lazy()
        rows = [
            candidate(100, "BR", 1, 22, "A"),
            candidate(100, "BR", 1, 22, "A", sequence="999"),
            candidate(101, "BR", 1, 22, "A", sequence="777"),
            candidate(100, "BR", 2, 22, "B"),
            candidate(200, "SP", 3, 22, "C"),
            candidate(200, "SP", 6, 22, "D"),
            candidate(200, "RJ", 3, 22, "E", uf="RJ"),
            candidate(300, "01007", 11, 22, "F"),
            candidate(300, "1015", 11, 22, "G"),
            candidate(200, "SP", 6, 1111, "H"),
            candidate(200, "SP", 6, 1111, "I"),
        ]
        self.raw = pl.LazyFrame(rows)
        self.candidates = candidatures(self.raw, self.municipalities, self.elections).collect()

    def test_identity_ignores_sequence_and_separates_locality_role_and_election(self):
        self.assertEqual(self.candidates.height, 10)
        self.assertEqual(self.candidates["id"].n_unique(), 10)
        changed_sequence = self.raw.with_columns(pl.lit("unreliable").alias("SQ_CANDIDATO"))
        regenerated = candidatures(changed_sequence, self.municipalities, self.elections).collect()
        self.assertEqual(set(self.candidates["id"]), set(regenerated["id"]))
        unique = self.candidates.filter(pl.col("numero_candidato") == 22)
        self.assertEqual(unique["id"].to_list(), unique.select(candidature_id_expr()).to_series().to_list())

    def test_votes_link_only_to_unique_nominal_candidates(self):
        rows = [
            vote(100, "99999", 1, 22, uf="ZZ"),  # National vote without a municipality match.
            vote(101, "1007", 1, 22),
            vote(200, "1007", 3, 22), vote(200, "1007", 6, 22),
            vote(200, "1007", 3, 22, uf="RJ"),
            vote(300, "1007", 11, 22), vote(300, "01015", 11, 22),
            vote(200, "1007", 6, 1111),  # Two distinct people: no attribution.
            vote(200, "1007", 6, 99999),  # Absent candidature.
            vote(200, "1007", 6, 22, kind="4"),  # Party vote.
            *[vote(200, "1007", 6, n) for n in [95, 96, 97, 98]],
            vote(300, "99999", 11, 22),  # Unmapped municipal election.
            vote(999, "1007", 6, 22),  # Absent election.
        ]
        result = bulletin_items(pl.LazyFrame(rows), self.municipalities, self.elections, self.candidates.lazy()).collect()
        self.assertEqual(result.height, len(rows))
        self.assertEqual(result["quantidade"].sum(), 7 * len(rows))
        linked = result.filter(pl.col("candidatura_id").is_not_null())
        self.assertEqual(linked.height, 7)
        self.assertEqual(linked["candidatura_id"].n_unique(), 7)
        self.assertTrue(set(linked["candidatura_id"]).issubset(set(self.candidates["id"])))
        for row in linked.iter_rows(named=True):
            target = self.candidates.filter(pl.col("id") == row["candidatura_id"]).row(0, named=True)
            for field in ["eleicao_id", "codigo_local", "codigo_cargo_tse"]:
                self.assertEqual(row[field], target[field])
            self.assertEqual(int(row["valor"]), target["numero_candidato"])

    def test_election_lookup_keeps_every_locality_and_deduplicates_rounds(self):
        elections = self.elections.select(pl.col("eleicao_id").alias("id"), "codigo_local")
        rounds = self.elections.select("codigo_tse", "eleicao_id")
        result = election_lookup(pl.concat([rounds, rounds]), elections).collect()
        self.assertEqual(result.height, 6)
        self.assertEqual(result.filter(pl.col("codigo_tse") == 200).height, 2)

    def test_round_identity_is_shared_and_preserves_existing_election_ids(self):
        frame = pl.DataFrame({"ano_eleicao": ["2022-01-01"], "codigo_local": ["SP"], "codigo_tse": [200]})
        frame = frame.with_columns(pl.col("ano_eleicao").str.to_date(), pl.col("codigo_tse").cast(pl.Int32))
        from config.projectsettings.settings import NUMERIC_HASH_SEED
        old = frame.select(pl.struct("ano_eleicao", "codigo_local", "codigo_tse").hash(seed=NUMERIC_HASH_SEED)).item()
        self.assertEqual(frame.select(election_id_expr()).item(), old)
        result = bulletin_items(
            pl.LazyFrame([vote(200, "99999", 6, 22), vote(100, "99999", 1, 22)]),
            self.municipalities, self.elections, self.candidates.lazy(),
        ).collect()
        expected = self.elections.with_columns(pl.lit(1).alias("numero_turno")).select(
            "eleicao_id", election_round_id_expr().alias("expected")
        ).collect()
        joined = result.join(expected, on="eleicao_id")
        self.assertEqual(joined["turno_eleicao_id"].to_list(), joined["expected"].to_list())
        self.assertEqual(result["boletim_id"].n_unique(), 1)
        self.assertEqual(result["turno_eleicao_id"].n_unique(), 2)

    def test_bulletin_is_independent_of_election_and_municipality_mapping(self):
        rows = [vote(200, "99999", 6, 22), vote(100, "99999", 1, 22)]
        for row in rows:
            row.update({key: None for key in ["DT_ABERTURA", "DT_ENCERRAMENTO", "DT_EMISSAO_BU", "DT_BU_RECEBIDO"]})
            row.update(QT_APTOS="10", QT_COMPARECIMENTO="8", QT_ABSTENCOES="2")
        raw = pl.LazyFrame(rows)
        result = bulletins(raw).collect()
        self.assertNotIn("turno_eleicao_id", result.columns)
        self.assertEqual(result["id"].n_unique(), 1)
        items = bulletin_items(raw, self.municipalities, self.elections, self.candidates.lazy()).collect()
        self.assertEqual(set(items["boletim_id"]), set(result["id"]))
        located = bulletins(raw, self.municipalities).collect()
        self.assertEqual(set(located["id"]), set(result["id"]))
        # An unmapped polling municipality stays null, even for state/national elections.
        self.assertTrue(located["codigo_municipio_ibge"].is_null().all())
        mapped_raw = raw.with_columns(pl.lit("1007").alias("CD_MUNICIPIO"))
        mapped = bulletins(mapped_raw, self.municipalities).collect()
        self.assertEqual(set(mapped["codigo_municipio_ibge"]), {"1200138"})
        self.assertEqual(set(mapped["id"]), set(result["id"]))
        contradictory = mapped_raw.with_columns(pl.lit("1015").alias("CD_MUNICIPIO"))
        mixed = pl.concat([
            bulletins(mapped_raw, self.municipalities),
            bulletins(contradictory, self.municipalities),
        ])
        consolidated = _consolidate_bulletins(mixed).collect()
        self.assertEqual(consolidated.height, 1)
        self.assertIsNone(consolidated["codigo_municipio_ibge"].item())


    def test_district_councillor_and_vote_enum(self):
        elections = pl.LazyFrame({"codigo_tse": [400], "codigo_local": ["1200138"], "eleicao_id": [7]}, schema_overrides={"codigo_tse": pl.Int32, "eleicao_id": pl.UInt64})
        candidates = candidatures(pl.LazyFrame([candidate(400, "01007", 25, 123, "J")]), self.municipalities, elections)
        result = bulletin_items(pl.LazyFrame([vote(400, "1007", 25, 123)]), self.municipalities, elections, candidates).collect()
        self.assertIsNotNone(result["candidatura_id"].item())
        self.assertIsNotNone(result["turno_eleicao_id"].item())
        self.assertEqual(result["tipo"].item(), TipoItemBoletim.NOMINAL.value)
        cases = pl.DataFrame({"number": ["22", "22", "95", "96", "97", "98"], "type": ["1", "4", "2", "3", "1", "1"]})
        self.assertEqual(cases.select(tse_evm_bulletin_vote_type_expr("number", "type")).to_series().to_list(), [1, 2, 3, 4, 6, 5])


if __name__ == "__main__":
    unittest.main()
