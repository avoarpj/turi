import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from apps.turi.src.downloaders._sds.core.filetagger.filetag import FiletagMeta, write_filetag_meta
from apps.turi.src.downloaders._sds.infra.dataset_types.historico_deputados_federais.api_deputy import XML_DeputiesRoot
from apps.turi.src.downloaders._sds.infra.scripts import camaradosdeputados_deputados_federais as full
from apps.turi.src.downloaders._sds.infra.scripts import camaradosdeputados_deputados_federais_incremental as incremental


def deputy(deputy_id, first=57, last=57):
    return dict(
        uri=f'https://dadosabertos.camara.leg.br/api/v2/deputados/{deputy_id}',
        nome='Deputado', nomeCivil='Deputado', siglaSexo='M',
        idLegislaturaInicial=first, idLegislaturaFinal=last,
        urlRedeSocial=[], urlWebsite=[], dataNascimento='', dataFalecimento='',
        ufNascimento='', municipioNascimento='',
    )


def xml(deputy_id, legislatures=(57,)):
    return '<Deputados>' + ''.join(
        f'<Deputado><numLegislatura>{legislature}</numLegislatura>'
        f'<ideCadastro>{deputy_id}</ideCadastro>'
        '<nomeParlamentarAtual>Deputado</nomeParlamentarAtual>'
        '<nomeCivil>Deputado</nomeCivil><sexo>M</sexo>'
        '<partidoAtual><sigla>PL</sigla></partidoAtual>'
        '<gabinete><numero>1</numero></gabinete>'
        '<comissoes><comissao><siglaComissao>CCJC</siglaComissao></comissao></comissoes>'
        '<cargosComissoes/><periodosExercicio/><filiacoesPartidarias/><historicoLider/>'
        '</Deputado>'
        for legislature in legislatures
    ) + '</Deputados>'


class DeputyUpdatesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.dataset = SimpleNamespace(
            downloadIfNecessary=Mock(),
            getProcessFile=Mock(return_value=SimpleNamespace(path='cache/deputados.json')),
            output=SimpleNamespace(path=SimpleNamespace(jjson='output/deputados.json')),
        )
        base_dir = patch.object(full, 'BASE_DIR', self.root)
        base_dir.start()
        self.addCleanup(base_dir.stop)
        self.batches = []

        async def download(items, timeout):
            self.batches.append(items)
            for item in items:
                item.path.parent.mkdir(parents=True, exist_ok=True)
                item.path.write_text(xml(item.path.stem), encoding='utf-8')
                full._onDownload(item)

        self.downloader = SimpleNamespace(download_all=AsyncMock(side_effect=download))

    def write_list(self, deputies):
        (self.cache / 'deputados.json').write_text(json.dumps({'dados': deputies}))

    def cache_xml(self, deputy_id, *, age=0, legislatures=(57,)):
        folder = self.cache / str(deputy_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{deputy_id}.xml').write_text(xml(deputy_id, legislatures))
        write_filetag_meta(folder / 'ftag.json', FiletagMeta(
            createdAt=datetime.now() - timedelta(seconds=age),
        ))

    def output(self):
        return XML_DeputiesRoot.model_validate_json(
            (self.root / 'output/deputados.json').read_text(),
        ).Deputados

    async def run_incremental(self):
        with patch.object(incremental, '_get_last_legislature', AsyncMock(return_value=57)), \
                patch.object(incremental, '_downloader', self.downloader):
            await incremental.Callback(self.dataset)

    async def test_updates_current_and_previous_and_preserves_cached_history(self):
        self.write_list([
            deputy(1, 55, 55), deputy(2, 56, 56), deputy(3),
            deputy(4, 55, 55), deputy(5, 58, 58), deputy(6),
        ])
        self.cache_xml(1, legislatures=(54, 55))
        self.cache_xml(3, age=incremental.FTAG_MAX_AGE + 60)
        self.cache_xml(6)

        await self.run_incremental()

        self.assertEqual([item.path.stem for item in self.batches[0]], ['2', '3'])
        for item in self.batches[0]:
            self.assertEqual(item.url,
                'https://www.camara.leg.br/SitCamaraWS/Deputados.asmx/'
                f'ObterDetalhesDeputado?ideCadastro={item.path.stem}&numLegislatura=')
            self.assertEqual(item.path.suffix, '.xml')
        self.assertEqual(
            [(row.ideCadastro, row.numLegislatura) for row in self.output()],
            [(1, 54), (1, 55), (2, 57), (3, 57), (6, 57)],
        )
        self.assertEqual(self.output()[0].comissoes[0].siglaComissao, 'CCJC')
        self.assertEqual(self.output()[0].historicoLider, [])

    async def test_limit_of_256_and_resume_on_next_run(self):
        self.write_list([deputy(deputy_id) for deputy_id in range(1, 259)])

        await self.run_incremental()
        self.assertEqual(len(self.batches[0]), 256)
        self.assertEqual(len(self.output()), 256)

        await self.run_incremental()
        self.assertEqual([item.path.stem for item in self.batches[1]], ['257', '258'])
        self.assertEqual(len(self.output()), 258)

    async def test_refreshes_xml_with_missing_or_invalid_filetag(self):
        self.write_list([deputy(1), deputy(2)])
        self.cache_xml(1)
        self.cache_xml(2)
        (self.cache / '1/ftag.json').unlink()
        (self.cache / '2/ftag.json').write_text('invalid')

        await self.run_incremental()

        self.assertEqual([item.path.stem for item in self.batches[0]], ['1', '2'])

    async def test_full_download_resumes_when_folder_exists_without_xml(self):
        self.write_list([deputy(1, 55, 55), deputy(2)])
        (self.cache / '1').mkdir()
        self.cache_xml(2, age=incremental.FTAG_MAX_AGE + 60)

        with patch.object(full, '_downloader', self.downloader):
            await full.Callback(self.dataset)

        self.assertEqual([item.path.stem for item in self.batches[0]], ['1'])
        self.assertEqual(len(self.output()), 2)


if __name__ == '__main__':
    unittest.main()
