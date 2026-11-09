import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from apps.turi.src.downloaders._sds.infra.scripts import camaradosdeputados_deputados_federais_incremental as deputies
from apps.turi.src.downloaders._sds.infra.scripts import historico_deputados_federais_incremental as history


class LegislatureHeadersTests(unittest.IsolatedAsyncioTestCase):
    async def test_legislature_requests_explicitly_accept_json(self):
        for module in (history, deputies):
            with self.subTest(module=module.__name__):
                response = MagicMock()
                response.json = AsyncMock(return_value={'dados': [{'id': 57}]})
                session = MagicMock()
                session.get.return_value.__aenter__.return_value = response
                client = MagicMock()
                client.return_value.__aenter__.return_value = session
                with patch.object(module.aiohttp, 'ClientSession', client):
                    self.assertEqual(await module._get_last_legislature(), 57)

                headers = session.get.call_args.kwargs['headers']
                self.assertEqual(headers['Accept'], 'application/json')
                self.assertIn('Avoar SDS', headers['User-Agent'])
                response.raise_for_status.assert_called_once()

    async def test_http_errors_are_reported_before_parsing_json(self):
        for module in (history, deputies):
            with self.subTest(module=module.__name__):
                response = MagicMock()
                response.json = AsyncMock()
                response.raise_for_status.side_effect = aiohttp.ClientResponseError(
                    request_info=MagicMock(), history=(), status=403,
                )
                session = MagicMock()
                session.get.return_value.__aenter__.return_value = response
                client = MagicMock()
                client.return_value.__aenter__.return_value = session
                with patch.object(module.aiohttp, 'ClientSession', client):
                    with self.assertRaises(aiohttp.ClientResponseError):
                        await module._get_legislatures()

                response.json.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
