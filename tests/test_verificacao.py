import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core import read, write, Orquestrador
from src.curadoria import build_daily
from src.verificacao import verificar
from tests.fixtures_verificacao import prepare_root

STAMP = '2026-11-16T07:00:00-03:00'


class VerificacaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = prepare_root(self.root)

    def check(self, **kwargs):
        return verificar(self.root, at=STAMP, **kwargs)

    def codes(self, result):
        return {x['codigo'] for x in result['bloqueios']}

    def update(self, path, **changes):
        write(self.root/path, dict(read(self.root/path), **changes))

    def test_current_configuration_passes_without_writes(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertTrue(self.check(exigir_sincronizacao=True)['ok'])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_pause_and_missing_config_fail_closed(self):
        self.update('config/preferencias.yaml', pausado=True)
        self.assertIn('pausado', self.codes(self.check()))
        (self.root/'config/preferencias.yaml').unlink()
        self.assertIn('arquivo_invalido', self.codes(self.check()))

    def test_groups_recency_budget_and_production_drift_block(self):
        changes = [('config/entrega_diaria.json', {'grupos_busca': ['engenharia_software']}),
                   ('config/entrega_diaria.json', {'publicacao_max_dias': 30}),
                   ('config/preferencias.yaml', {'orcamento_adicional_brl': 1}),
                   ('config/preferencias.yaml', {'curadoria_limite_segundos': 1800}),
                   ('config/politica_autorizacao.yaml', {'envio_producao_global': True})]
        for path, values in changes:
            with self.subTest(values=values):
                prepare_root(self.root)
                self.update(path, **values)
                self.assertFalse(self.check()['ok'])

    def test_sync_warns_before_search_and_blocks_generation(self):
        self.update('data/controle_vagas.json', synced_date='2026-11-15')
        self.assertTrue(self.check()['ok'])
        self.assertIn('sincronizacao_necessaria', self.codes(self.check(exigir_sincronizacao=True)))

    def test_completed_delivery_blocks_and_new_round_requires_new_sync(self):
        write(self.root/'data/entregas/2026-11-16.json',
              {'planilha_publicada': True, 'email_enviado': True,
               'entrega_confirmada_em': STAMP})
        self.assertIn('entrega_ja_confirmada', self.codes(self.check()))
        self.assertIn('sincronizacao_necessaria', self.codes(self.check(nova_rodada=True, exigir_sincronizacao=True)))
        self.update('data/controle_vagas.json', synced_at='2026-11-16T07:01:00-03:00')
        self.assertTrue(self.check(nova_rodada=True, exigir_sincronizacao=True)['ok'])

    def test_uncertain_or_partial_delivery_cannot_be_overridden(self):
        for state in ({}, {'inicio_envio': STAMP}, {'planilha_publicada': True, 'email_enviado': False},
                      {'planilha_publicada': False, 'email_enviado': True}):
            with self.subTest(state=state):
                write(self.root/'data/entregas/2026-11-16.json', state)
                self.assertIn('entrega_pendente_reconciliacao', self.codes(self.check(nova_rodada=True)))

    def test_utc_timestamp_uses_brasilia_delivery_day(self):
        result = verificar(self.root, at='2026-11-17T01:00:00Z')
        self.assertEqual(result['data'], '2026-11-16')

    def test_direct_build_cannot_bypass_pause_or_sync(self):
        for changes in ({'pausado': True}, {'publicacao_max_dias': 30}):
            with self.subTest(changes=changes):
                prepare_root(self.root)
                self.update('config/preferencias.yaml', **changes)
                with patch('src.curadoria.ROOT', self.root), self.assertRaisesRegex(ValueError, 'Verificação prévia'):
                    build_daily(self.root/'missing.json', 'não executado', at=STAMP)
                self.assertFalse((self.root/'relatorios').exists())
                self.assertFalse((self.root/'data/candidaturas.sqlite').exists())

    def test_legacy_run_is_blocked_before_database_mutation(self):
        with patch('src.core.ROOT', self.root), self.assertRaisesRegex(ValueError, 'legado'):
            Orquestrador().run(self.root/'missing.json', force=True)
        self.assertFalse((self.root/'data/candidaturas.sqlite').exists())

    def test_cli_verification_returns_nonzero_on_block(self):
        from src.cli import main
        self.update('config/preferencias.yaml', pausado=True)
        with patch('src.cli.ROOT', self.root), patch('sys.argv', ['vagas', 'verificar']), patch('builtins.print'), self.assertRaises(SystemExit) as raised:
            main()
        self.assertEqual(raised.exception.code, 2)

    def test_cli_list_blocks_before_build(self):
        from src.cli import main
        self.update('config/preferencias.yaml', pausado=True)
        with patch('src.cli.ROOT', self.root), patch('sys.argv', ['vagas', 'lista', '--cobertura', 'não executado']), patch('builtins.print'), patch('src.curadoria.build_daily') as build, self.assertRaises(SystemExit):
            main()
        build.assert_not_called()
