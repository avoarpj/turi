from datetime import date
from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl

from config.projectsettings.settings import NUMERIC_HASH_SEED
from scripts.operations.organs import organs
from scripts.operations.mandates import camaradosdeputados as mandates
from scripts.operations.public_people import camaradosdeputados as people


class PublicPeopleCoverageTest(unittest.TestCase):
    def test_camara_mandates_ignore_tse_identifiers_with_the_same_number(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            identifiers = root / 'identifiers.parquet'
            pl.DataFrame({
                'pessoa_publica_id': [1, 2],
                'identificador': ['99', '99'],
                'fonte': ['camaradosdeputados', 'tse'],
            }).write_parquet(identifiers)

            history = root / 'history.parquet'
            pl.DataFrame({'dados': [[{
                'id': 99, 'idLegislatura': 56,
                'descricaoStatus': 'Entrada em exercício',
                'dataHora': '2019-02-01T12:00:00',
            }]]}).write_parquet(history)

            legislatures = root / 'legislatures.parquet'
            pl.DataFrame({
                'id': [56], 'orgao_id': ['cd'], 'data_inicio': [date(2019, 2, 1)],
            }).write_parquet(legislatures)

            candidates = root / 'candidates.parquet'
            pl.DataFrame({
                'id': [10], 'pessoa_publica_id': [1], 'eleicao_id': [100],
                'codigo_cargo_tse': [6], 'codigo_local': ['SP'],
            }).write_parquet(candidates)

            elections = root / 'elections.parquet'
            pl.DataFrame({'id': [100], 'ano': [2018], 'tipo': [0]}).write_parquet(elections)
            output = root / 'mandates.parquet'

            with patch.multiple(
                mandates,
                dependencies=[identifiers, legislatures, candidates, elections],
                PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS=identifiers,
                CD_MANDATES_RAW_PARQUETS=history,
                CD_LEGISLATURES_OUTPUT_PARQUETS=legislatures,
                CANDIDATURES_OUTPUT_PARQUETS=candidates,
                ELECTIONS_OUTPUT_PARQUETS=elections,
                CD_MANDATES_OUTPUT_PARQUETS=output,
            ):
                mandates.script_instance.process_data(getLogger(__name__))

            actual = pl.read_parquet(output)
            self.assertEqual(actual['pessoa_publica_id'].to_list(), [1])
            self.assertEqual(actual['orgao_id'].to_list(), ['cd'])
            self.assertEqual(actual['candidatura_id'].to_list(), [10])

    def test_all_offices_results_and_elections_without_expanding_camara_matching(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = root / 'candidates'
            candidates.mkdir()

            rows = []
            for identifier, year, office, name in [
                ('1', '2018', '6', 'MARIA EXEMPLO'),
                ('2', '2020', '11', 'MARIA EXEMPLO'),
                ('3', '2020', '13', 'VEREADORA EXEMPLO'),
                ('4', '2022', '1', 'PRESIDENTE EXEMPLO'),
                ('5', '2022', '3', 'GOVERNADORA EXEMPLO'),
                ('6', '2022', '5', 'SENADORA EXEMPLO'),
                ('7', '2022', '7', 'DEPUTADA ESTADUAL EXEMPLO'),
                ('8', '2022', '6', 'MARIA EXEMPLO'),
                ('9', '2018', '6', 'MARIA EXEMPLO'),
                ('10', '2018', '6', 'MARIA EXEMPLO'),
            ]:
                rows.append({
                    'NR_TITULO_ELEITORAL_CANDIDATO': identifier,
                    'NR_CPF_CANDIDATO': '#NULO#',
                    'NM_CANDIDATO': name,
                    'NM_URNA_CANDIDATO': name,
                    'DT_NASCIMENTO': '01/01/1981' if identifier == '8' else '01/01/1980',
                    'SG_UF': 'SP',
                    'SG_UF_NASCIMENTO': 'SP',
                    'CD_GENERO': '4',
                    'CD_CARGO': office,
                    'CD_TIPO_ELEICAO': '1' if identifier == '10' else '2',
                    'CD_SIT_TOT_TURNO': '4' if identifier == '9' else '1',
                    'ANO_ELEICAO': year,
                    'NR_CANDIDATO': identifier,
                })

            pl.DataFrame(rows).write_parquet(candidates / 'candidates.parquet')
            legislatures = root / 'legislatures.parquet'
            pl.DataFrame({
                'id': [56], 'orgao_id': ['cd'], 'data_inicio': [date(2019, 2, 1)],
            }).write_parquet(legislatures)

            deputies = root / 'deputies.parquet'
            pl.DataFrame({'dados': [[
                {
                    'id': 99, 'uri': '/deputados/99', 'nomeCivil': 'MARIA EXEMPLO',
                    'dataNascimento': '1980-01-01',
                },
                {
                    'id': 98, 'uri': '/deputados/98', 'nomeCivil': 'MARIA EXEMPLO',
                    'dataNascimento': '1900-01-01',
                },
            ]]}).write_parquet(deputies)

            history = root / 'history.parquet'
            pl.DataFrame({'dados': [[
                {
                    'uri': f'/deputados/{identifier}',
                    'descricaoStatus': 'Nome no início da legislatura / Partido no início da legislatura',
                }
                for identifier in (98, 99)
            ]]}).write_parquet(history)

            output = root / 'people.parquet'
            identifiers = root / 'identifiers.parquet'
            with patch.multiple(
                people,
                dependencies=[legislatures],
                PUBLIC_PEOPLE_RAW_PARQUETS=candidates,
                PUBLIC_PEOPLE_OUTPUT_PARQUETS=output,
                PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS=identifiers,
                CD_LEGISLATURES_OUTPUT_PARQUETS=legislatures,
                CD_DEPUTIES_RAW_PARQUETS=deputies,
                CD_DEPUTIES_HISTORY_RAW_PARQUETS=history,
            ):
                people.script_instance.process_data(getLogger(__name__))

            expected = pl.Series([str(i) for i in range(1, 11)]).hash(seed=NUMERIC_HASH_SEED)
            actual = pl.read_parquet(output)
            self.assertEqual(set(actual['id']), set(expected))
            self.assertEqual(actual['id'].n_unique(), 10)

            external = pl.read_parquet(identifiers).filter(pl.col('fonte') == 'camaradosdeputados')
            self.assertEqual(external['pessoa_publica_id'].to_list(), [expected[0]])
            self.assertEqual(external['identificador'].to_list(), ['99'])

    def test_static_organs_include_federal_government(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / 'static.parquet'
            with patch.object(organs, 'ORGANS_OUTPUT_PARQUETS', output):
                organs.script_instance.process_data(getLogger(__name__))

            actual = pl.read_parquet(output)
            self.assertEqual(actual['id'].to_list(), ['cd', 'gov', 'sf'])
            self.assertEqual(
                actual.filter(pl.col('id') == 'gov')['nome'].to_list(),
                ['Governo Federal'],
            )
