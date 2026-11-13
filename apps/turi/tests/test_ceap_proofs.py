import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal

from scripts.operations.ceap_reimbursements import camaradosdeputados as operation


class CeapProofsTest(unittest.TestCase):
    def test_all_nonempty_urls_produce_linked_proofs(self):
        # Even and odd URL lengths must both survive the filter. The old
        # expression performed a bitwise AND on the length before comparing it.
        urls = ['https://example.test/a', 'https://example.test/ab', '', None]
        records = [dict(
            idDeputado='123', codigoLegislatura=57, numeroSubCota=1,
            numeroEspecificacaoSubCota=0, cnpjCPF='12345678901', fornecedor='Teste',
            descricaoEspecificacao=str(i), valorGlosa=0.0, valorDocumento=10.0,
            valorLiquido=10.0, dataEmissao='2024-01-01', urlDocumento=url,
        ) for i, url in enumerate(urls)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'raw' / 'input.parquet'
            raw.parent.mkdir()
            pl.DataFrame({'dados': [records]}).write_parquet(raw)
            identifiers = root / 'identifiers.parquet'
            pl.DataFrame({
                'identificador': ['123', '123'],
                'pessoa_publica_id': [100, 200],
                'fonte': ['camaradosdeputados', 'tse'],
            }).write_parquet(identifiers)
            mandates = root / 'mandates.parquet'
            pl.DataFrame({'id': [10], 'legislatura_id': [57], 'pessoa_publica_id': [100]}).write_parquet(mandates)
            reimbursements = root / 'reimbursements.parquet'
            proofs = root / 'proofs.parquet'
            with patch.multiple(operation,
                CD_CEAPS_RAW_PARQUETS=raw,
                PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS=identifiers,
                CD_MANDATES_OUTPUT_PARQUETS=mandates,
                CD_CEAPS_OUTPUT_PARQUETS=reimbursements,
                CD_CEAPS_PROOF_OUTPUT_PARQUETS=proofs,
            ):
                operation.script_instance.process_data(logging.getLogger('test-ceap'))
            expenses = pl.read_parquet(reimbursements)
            result = pl.read_parquet(proofs)
            self.assertEqual(expenses.height, 4)
            self.assertEqual(result.height, 2)
            expected_ids = expenses.filter(pl.col('descricao_especificacao').is_in(['0', '1']))['id'].to_list()
            self.assertEqual(set(result['ceap_id']), set(expected_ids))
            self.assertEqual(result['id'].n_unique(), 2)
            linked = result.join(expenses, left_on='ceap_id', right_on='id')
            self.assertEqual(
                dict(zip(linked['descricao_especificacao'], linked['fonte'])),
                {'0': urls[0], '1': urls[1]},
            )

            # Compare every expense/proof field, including hashes of all joined
            # columns, with the direct nested reader used before staging.
            direct_reimbursements = root / 'direct_reimbursements.parquet'
            direct_proofs = root / 'direct_proofs.parquet'
            with patch.multiple(operation,
                CD_CEAPS_RAW_PARQUETS=raw,
                PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS=identifiers,
                CD_MANDATES_OUTPUT_PARQUETS=mandates,
                CD_CEAPS_OUTPUT_PARQUETS=direct_reimbursements,
                CD_CEAPS_PROOF_OUTPUT_PARQUETS=direct_proofs,
            ):
                direct = pl.scan_parquet(raw).select(pl.col('dados').list.explode()).unnest('dados')
                operation.script_instance._process_data(direct, logging.getLogger('test-ceap'))

            assert_frame_equal(expenses.sort('id'), pl.read_parquet(direct_reimbursements).sort('id'))
            assert_frame_equal(result.sort('id'), pl.read_parquet(direct_proofs).sort('id'))


if __name__ == '__main__':
    unittest.main()
