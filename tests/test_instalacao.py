import copy
import tempfile
import unittest
from pathlib import Path

from src.core import ROOT, read, write
from src.instalacao import configure
from src.verificacao import verificar
from src.busca import plano_busca


class InstalacaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def cadastro(self):
        data=read(ROOT/'exemplos/cadastro.json')
        data['perfil'].update(nome='Pessoa Exemplo',cidade='Cidade Teste',email='pessoa@example.org')
        data['preferencias'].update(cidades_presenciais=['Cidade Teste'],clt_acima_de=5200,max_dias_hibrido=2)
        data['entrega'].update(planilha_id='planilha_ficticia_exclusiva_de_testes',email='pessoa@example.org',
                               horario='08:30',sheet_id=10,sheet_id_graduacao=11,sheet_id_ingles=12,sheet_id_historico=13)
        write(self.root/'entrada/cadastro.json',data)
        return data

    def snapshot(self):
        return {p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_blank_setup_is_paused_unapproved_and_idempotent(self):
        result=configure(self.root)
        self.assertTrue(result['configuracao_pendente'])
        self.assertTrue(read(self.root/'config/preferencias.yaml')['pausado'])
        self.assertFalse(read(self.root/'config/entrega_diaria.json')['autorizado_email_diario'])
        self.assertEqual(read(self.root/'perfil/fatos_confirmados.json')['afirmacoes'],{})
        before=self.snapshot()
        configure(self.root)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.root/'data').exists())

    def test_complete_setup_uses_own_preferences_but_does_not_start_work(self):
        self.cadastro()
        result=configure(self.root,cadastro=self.root/'entrada/cadastro.json')
        self.assertFalse(result['configuracao_pendente'])
        prefs=read(self.root/'config/preferencias.yaml')
        delivery=read(self.root/'config/entrega_diaria.json')
        self.assertEqual(prefs['clt_acima_de'],5200)
        self.assertEqual(delivery['sheet_id_historico'],13)
        self.assertFalse(delivery['autorizado_email_diario'])
        check=verificar(self.root,at='2026-11-17T08:00:00-03:00')
        self.assertEqual([i['codigo'] for i in check['bloqueios']],['pausado'])
        self.assertFalse((self.root/'data').exists())
        self.assertTrue(any('Cidade Teste' in q['consulta'] for q in plano_busca(cidades=prefs['cidades_presenciais'])))

    def test_seed_can_be_completed_without_overwriting_later_installations(self):
        configure(self.root)
        self.cadastro()
        configure(self.root,cadastro=self.root/'entrada/cadastro.json')
        before=self.snapshot()
        result=configure(self.root,cadastro=self.root/'entrada/cadastro.json')
        self.assertTrue(result['instalacao_existente_preservada'])
        self.assertEqual(self.snapshot(),before)

    def test_existing_owner_or_partial_profile_is_never_overwritten(self):
        write(self.root/'config/preferencias.yaml',{'pausado':False,'cidades_presenciais':['Cidade Existente']})
        before=self.snapshot()
        result=configure(self.root)
        self.assertTrue(result['instalacao_existente_preservada'])
        self.assertEqual(self.snapshot(),before)
        with tempfile.TemporaryDirectory() as another:
            root=Path(another)
            write(root/'perfil/fatos_confirmados.json',{'nome':'Pessoa Existente'})
            self.cadastro()
            with self.assertRaisesRegex(ValueError,'Arquivo local alterado'):
                configure(root,cadastro=self.root/'entrada/cadastro.json')
            self.assertEqual(read(root/'perfil/fatos_confirmados.json')['nome'],'Pessoa Existente')
            self.assertFalse((root/'config').exists())

    def test_invalid_or_credential_fields_fail_before_creating_settings(self):
        data=self.cadastro()
        invalid=[dict(data,token='não deve ser aceito'),
                 dict(data,preferencias=dict(data['preferencias'],cidades_presenciais=[])),
                 dict(data,entrega=dict(data['entrega'],planilha_id=''))]
        for item in invalid:
            with self.subTest(item=list(item)):
                write(self.root/'entrada/cadastro.json',item)
                with self.assertRaises(ValueError):
                    configure(self.root,cadastro=self.root/'entrada/cadastro.json')
                self.assertFalse((self.root/'config').exists())

    def test_seed_with_progress_or_manual_changes_is_preserved(self):
        configure(self.root)
        self.cadastro()
        write(self.root/'data/progresso.json',{'atividade':True})
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'dados operacionais'):
            configure(self.root,cadastro=self.root/'entrada/cadastro.json')
        self.assertEqual(self.snapshot(),before)
