import unittest
import polars as pl
from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
from scripts.bricks.candidature_identity import with_electoral_locality


class HistoricalBulletinTest(unittest.TestCase):
    def test_historical_headers_and_election_types(self):
        raw = pl.LazyFrame({
            'SG_ UF': ['SP'] * 4,
            'CD_FLASCARD_URNA_EFETIVADA': ['hash'] * 4,
            'DS_ELEICAO': ['Eleições Gerais Estaduais 2018', 'Eleição Geral Federal 2018',
                          'Eleição Suplementar Senador - MT', 'Plebiscito de Augusto Severo'],
            'CD_CARGO_PERGUNTA': ['6', '1', '5', '53'],
            'CD_MUNICIPIO': ['1007'] * 4,
        })
        normalized = normalize_tse_bulletin(raw)
        result = normalized.collect()
        self.assertEqual(result['tipo_eleicao_normalizado'].to_list(), ['0', '0', '1', '2'])
        self.assertEqual(result['CD_FLASHCARD_URNA_EFETIVADA'].to_list(), ['hash'] * 4)
        municipalities = pl.LazyFrame({'CD_MUNICIPIO_TSE': ['01007'], 'CD_MUNICIPIO_IBGE': ['1200138']})
        located = with_electoral_locality(normalized, municipalities, 'CD_CARGO_PERGUNTA', 'CD_MUNICIPIO').collect()
        self.assertEqual(located['codigo_local'].to_list(), ['SP', 'BR', 'SP', None])

    def test_existing_numeric_types_and_canonical_columns_are_preserved(self):
        raw = pl.LazyFrame({'SG_UF': ['RJ'], 'CD_FLASHCARD_URNA_EFETIVADA': ['canonical'],
                           'SG_ UF': ['SP'], 'CD_FLASCARD_URNA_EFETIVADA': ['old'],
                           'CD_TIPO_ELEICAO': [1], 'DS_ELEICAO': ['Eleição Geral Federal 2022']})
        result = normalize_tse_bulletin(raw).collect()
        self.assertEqual(result['SG_UF'].item(), 'RJ')
        self.assertEqual(result['CD_FLASHCARD_URNA_EFETIVADA'].item(), 'canonical')
        self.assertEqual(result['tipo_eleicao_normalizado'].item(), '1')

    def test_unknown_type_is_not_assumed_ordinary(self):
        result = normalize_tse_bulletin(pl.LazyFrame({'DS_ELEICAO': ['Desconhecida']})).collect()
        self.assertIsNone(result['tipo_eleicao_normalizado'].item())
