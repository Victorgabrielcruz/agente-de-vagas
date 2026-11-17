import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.core import write, read
from src.curadoria import build_daily
from tests.fixtures_verificacao import prepare_root
from src import controle_vagas as c

class TrackingTests(unittest.TestCase):
    def job(self,n=1,**extra):return dict(url=f'https://example.com/{n}',empresa='Empresa',titulo=f'Dev {n}',**extra)
    def snapshot(self,flag,sid=4,job=None):
        j=job or self.job()
        def row(values):return {'values':[{'userEnteredValue':{'boolValue':x} if isinstance(x,bool) else {'stringValue':x}} for x in values]}
        return {'sheets':[{'properties':{'sheetId':sid},'data':[{'rowData':[row([])]*4+[row([c.CHECKBOX,'Empresa','Vaga','Link da vaga']),row([flag,j['empresa'],j['titulo'],j['url']])]}]}]}
    def test_unchecked_previously_listed_stays_in_history_but_is_not_daily_novel(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12',published=True)
        self.assertFalse(c.applied(ledger,j));self.assertFalse(c.novel(ledger,j,'2026-11-13'))
        self.assertFalse(c.novel(ledger,j,'2026-11-12'))  # rodada adicional não repete a entrega do mesmo dia
        self.assertEqual(len(ledger['items']),1)
    def test_checkbox_can_check_and_uncheck_without_destroying_history(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12',published=True)
        c.sync(ledger,self.snapshot(False),'2026-11-13',baseline_only=True)
        c.sync(ledger,self.snapshot(True),'2026-11-13');self.assertTrue(c.applied(ledger,j))
        c.sync(ledger,self.snapshot(False),'2026-11-14');self.assertFalse(c.applied(ledger,j))
        self.assertEqual(ledger['items'][j['url']]['first_listed'],'2026-11-12')
    def test_rows_are_keyed_by_url_and_stale_daily_does_not_reapply_master_uncheck(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12',published=True)
        c.sync(ledger,self.snapshot(True),'2026-11-12',baseline_only=True)
        c.sync(ledger,self.snapshot(True,sid=0),'2026-11-12',baseline_only=True)
        ledger['items'][j['url']]['applied']=True
        c.sync(ledger,self.snapshot(False),'2026-11-13')
        c.sync(ledger,self.snapshot(True,sid=0),'2026-11-13')
        self.assertFalse(c.applied(ledger,j))
    def test_failed_unpublished_build_does_not_hide_a_job(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12')
        self.assertTrue(c.novel(ledger,j,'2026-11-13'))
    def test_same_role_alternate_url_is_not_new_other_role_is_new(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12',published=True)
        copy=dict(j,url='https://other.com/abc')
        self.assertFalse(c.novel(ledger,copy,'2026-11-13'))
        self.assertTrue(c.novel(ledger,self.job(2),'2026-11-13'))

    def test_daily_build_keeps_backlog_and_emits_only_new_unchecked_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=prepare_root(root,'2026-11-13');ledger=c.empty()
            old=self.job(1);new=self.job(2,publicada_em='2026-11-12',tipo_data='oficial',fonte_data='Pagina oficial');sent=self.job(3)
            c.register(ledger,[old,sent],'2026-11-12',published=True)
            ledger['items'][sent['url']]['applied']=True
            ledger['synced_date']='2026-11-13'
            write(root/'data/controle_vagas.json',ledger)
            write(root/'inbox.json',[old,new,sent])
            with patch('src.curadoria.ROOT',root):
                result=build_daily(root/'inbox.json','consulta real',settings=settings,sent_urls=[],at='2026-11-13T07:00:00-03:00')
            self.assertEqual(result['total'],1)
            rows=read(root/'relatorios/2026-11-13-lista/valores-planilha.json')
            self.assertEqual(rows[4][-2:],[c.CHECKBOX,c.DECISION])
            self.assertEqual(rows[5][-2:],[False,''])
            self.assertIn(old['url'],read(root/'data/controle_vagas.json')['items'])

    def decision_snapshot(self,choice,sid=4):
        snap=self.snapshot(False,sid)
        rows=snap['sheets'][0]['data'][0]['rowData']
        rows[4]['values'].append({'userEnteredValue':{'stringValue':c.DECISION}})
        rows[5]['values'].append({'userEnteredValue':{'stringValue':choice}} if choice else {})
        return snap

    def test_decision_sync_clear_and_master_precedence(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12',published=True)
        for sid in (0,4):c.sync(ledger,self.decision_snapshot('',sid),'2026-11-13',baseline_only=True)
        c.sync(ledger,self.decision_snapshot(c.DECISIONS[0],0),'2026-11-13')
        self.assertTrue(c.dismissed(ledger,j));self.assertFalse(c.applied(ledger,j))
        c.sync(ledger,self.decision_snapshot(c.DECISIONS[0],4),'2026-11-13',baseline_only=True)
        snap=self.decision_snapshot('',4)
        snap['sheets']+=self.decision_snapshot(c.DECISIONS[1],0)['sheets']
        c.sync(ledger,snap,'2026-11-13')
        self.assertEqual(c.decision(ledger,j),'')
        self.assertFalse(c.novel(ledger,j,'2026-11-13'))

    def test_missing_decision_column_preserves_saved_choice(self):
        ledger=c.empty();j=self.job();c.register(ledger,[j],'2026-11-12')
        c.sync(ledger,self.decision_snapshot(c.DECISIONS[1]),'2026-11-13')
        c.sync(ledger,self.snapshot(False),'2026-11-13')
        self.assertEqual(c.decision(ledger,j),c.DECISIONS[1])
        values=c.history_values(ledger)
        self.assertEqual(values[4][-1],c.DECISION)
        self.assertEqual(values[5][-1],c.DECISIONS[1])

if __name__=='__main__':unittest.main()
