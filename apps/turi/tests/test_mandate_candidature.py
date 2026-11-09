import unittest
import polars as pl

from scripts.bricks.mandate_candidature import link_mandate_candidatures


class MandateCandidatureTest(unittest.TestCase):
    def setUp(self):
        self.mandates = pl.DataFrame({
            'id': list(range(1, 10)),
            'pessoa_publica_id': [10, 20, 30, 40, 10, 50, 60, 10, 70],
            'orgao_id': ['cd', 'sf', 'al_sp', 'cm_12345', 'cd', 'cd', 'al_rj', 'cd', 'cm_12345'],
            'legislatura_id': [57, 57, 20, 10, 58, 57, 20, 57, 10],
        }).lazy()
        self.elections = pl.DataFrame({
            'id': [1, 2, 3, 4], 'ano': [2022, 2018, 2020, 2020], 'tipo': [0, 0, 0, 1],
        }).lazy()
        self.candidates = pl.DataFrame({
            'id': [101, 102, 103, 104, 105, 106, 107, 108, 109],
            'pessoa_publica_id': [10, 20, 30, 30, 40, 40, 50, 50, 70],
            'eleicao_id': [1, 2, 1, 1, 3, 3, 1, 1, 4],
            'codigo_cargo_tse': [6, 5, 7, 6, 13, 13, 6, 6, 13],
            'codigo_local': ['SP', 'SP', 'SP', 'SP', '12345', '67890', 'SP', 'RJ', '12345'],
        }).lazy()
        self.contexts = pl.DataFrame({
            'mandato_id': [1, 2, 3, 4, 5, 6, 8, 8, 9],
            'ano_eleicao': [2022, 2018, 2022, 2020, 2024, 2022, 2022, 2022, 2020],
            'codigo_cargo_tse': [6, 5, 7, 13, 6, 6, 6, 6, 13],
            'tipo_eleicao': [0, 0, 0, 0, 0, 0, 0, 0, 1],
            'codigo_local': [None, 'SP', 'SP', '12345', None, None, None, 'SP', '12345'],
        }).lazy()

    def test_multiple_houses_and_source_specific_years_and_elections(self):
        result = link_mandate_candidatures(self.mandates, self.candidates, self.elections, self.contexts).collect().sort('id')
        self.assertEqual(result.height, 9)
        self.assertEqual(result['candidatura_id'].to_list(), [101, 102, 103, 105, None, None, None, 101, 109])
        self.assertEqual(result['candidatura_id'].dtype, pl.UInt64)

    def test_duplicate_candidate_rows_do_not_create_false_ambiguity(self):
        result = link_mandate_candidatures(self.mandates, pl.concat([self.candidates, self.candidates]), self.elections, self.contexts).collect()
        self.assertEqual(result.filter(pl.col('id') == 1)['candidatura_id'].item(), 101)
        self.assertIsNone(result.filter(pl.col('id') == 6)['candidatura_id'].item())

    def test_missing_context_and_wrong_type_do_not_infer_links(self):
        contexts = self.contexts.with_columns(
            pl.when(pl.col('mandato_id') == 1).then(None).otherwise(pl.col('ano_eleicao')).alias('ano_eleicao'),
            pl.when(pl.col('mandato_id') == 2).then(1).otherwise(pl.col('tipo_eleicao')).alias('tipo_eleicao'),
        )
        result = link_mandate_candidatures(self.mandates, self.candidates, self.elections, contexts).collect()
        self.assertIsNone(result.filter(pl.col('id') == 1)['candidatura_id'].item())
        self.assertIsNone(result.filter(pl.col('id') == 2)['candidatura_id'].item())


if __name__ == '__main__':
    unittest.main()
