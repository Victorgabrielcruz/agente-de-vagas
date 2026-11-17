import tempfile
import unittest
from pathlib import Path

from src import alertas
from src.core import read, write
from tests.fixtures_verificacao import prepare_root

STAMP='2026-11-16T07:00:00-03:00'


class AlertasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        prepare_root(self.root)

    def authorize(self):
        rule={'habilitado':True,'destinatario':'pessoa@example.org','gmail_link_id':'conexao_ficticia'}
        settings=read(self.root/'config/entrega_diaria.json')
        settings.update(gmail_link_id='conexao_ficticia',alertas_impedimentos=rule)
        write(self.root/'config/entrega_diaria.json',settings)
        policy=read(self.root/'config/politica_autorizacao.yaml')
        policy['alertas_impedimentos']=dict(rule,autorizado=True,
            texto_usuario='Autorizo alertas para minha conta configurada.',autorizado_em=STAMP)
        write(self.root/'config/politica_autorizacao.yaml',policy)

    def register(self):
        return alertas.registrar(self.root,'fonte_indisponivel','Portal',
            'Fonte indisponível <script>não executar</script>','Aguardar acesso',at=STAMP)

    def test_disabled_installation_does_not_inherit_authorization_or_create_queue(self):
        self.assertEqual(self.register(),{'habilitado':False})
        self.assertFalse((self.root/'data/alertas_impedimentos.sqlite').exists())

    def test_destination_or_connection_change_requires_new_authorization(self):
        self.authorize()
        settings=read(self.root/'config/entrega_diaria.json')
        settings['email']='outra@example.org'
        write(self.root/'config/entrega_diaria.json',settings)
        with self.assertRaisesRegex(ValueError,'autorização própria'):
            self.register()

    def test_duplicate_incident_survives_restart_and_does_not_resend(self):
        self.authorize()
        first=self.register()
        again=self.register()
        self.assertEqual(first['id'],again['id'])
        self.assertEqual(again['ocorrencias'],2)
        prepared=alertas.atualizar(self.root,'preparar',first['id'],at=STAMP)
        self.assertTrue(prepared['enviar'])
        self.assertEqual(prepared['gmail']['to'],'pessoa@example.org')
        body=prepared['gmail']['payload']['body']['content']
        self.assertIn('&lt;script&gt;',body)
        self.assertNotIn('<script>',body)
        after_restart=alertas.atualizar(self.root,'preparar',first['id'],at=STAMP)
        self.assertFalse(after_restart['enviar'])
        self.assertTrue(after_restart['requer_reconciliacao'])
        self.assertEqual(len(alertas.status(self.root)['reconciliar']),1)

    def test_confirmation_requires_real_sent_receipt_and_uncertain_send_stays_blocked(self):
        self.authorize();item=self.register()
        alertas.atualizar(self.root,'preparar',item['id'],at=STAMP)
        with self.assertRaisesRegex(ValueError,'SENT'):
            alertas.atualizar(self.root,'confirmar',item['id'],receipt={'id':'rascunho'},at=STAMP)
        alertas.atualizar(self.root,'incerto',item['id'],evidence='Resposta do envio não recebida',at=STAMP)
        self.assertFalse(alertas.atualizar(self.root,'preparar',item['id'],at=STAMP)['enviar'])
        alertas.atualizar(self.root,'confirmar',item['id'],
            receipt={'structuredContent':{'id':'mensagem_ficticia','label_ids':['SENT']}},at=STAMP)
        self.assertEqual(alertas.status(self.root)['enviados'],1)
        self.register()
        self.assertEqual(alertas.status(self.root)['pendentes'],[])

    def test_resolved_incident_allows_alert_for_a_new_occurrence(self):
        self.authorize();item=self.register()
        alertas.atualizar(self.root,'resolver',item['id'],evidence='Fonte voltou a responder',at=STAMP)
        next_item=self.register()
        self.assertNotEqual(item['id'],next_item['id'])
        self.assertEqual(next_item['estado'],'pendente')

    def test_cache_source_failure_creates_one_alert_for_multiple_affected_queries(self):
        from src import cache_busca
        self.authorize()
        plan=[dict(grupo='sem_nivel',consulta=q,fonte='Portal',tipo_fonte='oficial',janela='7d')
              for q in ('Java','Python')]
        state=cache_busca.start(self.root,plan,at=STAMP)
        for task in state['consultas_pendentes']:
            cache_busca.mutate(self.root,'isolar-fonte',task_id=task['id'],
                result={'motivo':'http403','evidencia':'Recusa observada; mesma falha afeta as consultas'},at=STAMP)
        pending=alertas.status(self.root)['pendentes']
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0]['ocorrencias'],2)


if __name__=='__main__':
    unittest.main()
