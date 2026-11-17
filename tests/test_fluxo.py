import copy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from src.core import Analista, Store, Revisor, Executor, Pesquisador, canonical, identity, write

class FluxoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s=Store(Path(self.tmp.name)/'test.sqlite'); self.addCleanup(self.s.db.close)
        self.p={'cidades_presenciais':['São Paulo','Campinas'],'max_dias_hibrido':3,'horas_semanais':40,'clt_acima_de':4000,'piso_pj':None,'empresas_preferidas':['TOTVS'],'limiar_auto':80,'pesos':{'tecnica':35,'junior':25,'modalidade':20,'empresa':10,'atualidade':10}}
        self.f={'afirmacoes':{'java':{'texto':'Java em projeto pessoal'}}}
        self.j={'empresa':'TOTVS','titulo':'Desenvolvedor Java Júnior','requisicao':'1','url':'https://example.org/jobs/1?utm_source=google','mercado':'Brasil','modalidade':'remoto','aceita_bh':True,'horas_semanais':40,'contrato':'CLT','salario_base_mensal':4500,'ativa':True,'vinculo_oficial_verificado':True,'requisitos':[{'texto':'Java','atendido':True,'fatos':['java']} ]}
    def evaluate(self,**changes):
        return Analista(self.p,self.f).evaluate(dict(self.j,**changes))
    def test_clt_limite_estrito(self):
        for value in (3999,4000): self.assertEqual(self.evaluate(salario_base_mensal=value)['estado'],'descartada')
        self.assertEqual(self.evaluate(salario_base_mensal=4000.01)['estado'],'elegivel')
    def test_salario_desconhecido_autorizado(self):
        self.assertEqual(self.evaluate(salario_base_mensal=None)['estado'],'elegivel')
    def test_pj_nao_converte_clt(self):
        self.assertEqual(self.evaluate(contrato='PJ')['estado'],'aguardando_dados')
    def test_localidade(self):
        self.assertEqual(self.evaluate(modalidade='presencial',cidade='Recife')['estado'],'descartada')
        self.assertEqual(self.evaluate(modalidade='hibrido',cidade='Campinas',dias_presenciais=3)['estado'],'elegivel')
        self.assertEqual(self.evaluate(modalidade='hibrido',cidade='Campinas',dias_presenciais=4)['estado'],'descartada')
    def test_remoto_restrito(self): self.assertEqual(self.evaluate(aceita_bh=False)['estado'],'descartada')
    def test_jornada_e_viagem(self):
        self.assertEqual(self.evaluate(horas_semanais=44)['estado'],'aguardando_dados')
        self.assertEqual(self.evaluate(horas_semanais=None)['estado'],'aguardando_dados')
        self.assertEqual(self.evaluate(viagem_especifica=True)['estado'],'aguardando_dados')
    def test_jornada_sem_filtro_nao_bloqueia(self):
        self.p['horas_semanais']=None
        for hours in (36,40,44,None):
            self.assertEqual(self.evaluate(horas_semanais=hours)['estado'],'elegivel')
    def test_internacional_estagio_senior(self):
        for changes in ({'mercado':'Exterior'},{'titulo':'Estágio Java'},{'titulo':'Desenvolvedor Senior'}): self.assertEqual(self.evaluate(**changes)['estado'],'descartada')
    def test_obrigatorio_nao_compensado_por_nota(self):
        self.assertEqual(self.evaluate(requisitos=[{'texto':'C# profissional','atendido':False,'obrigatorio':True}])['estado'],'descartada')
        self.assertEqual(self.evaluate(requisitos=[{'texto':'Inglês conversação','atendido':None,'obrigatorio':True}])['estado'],'aguardando_dados')
    def test_diferencial_nao_elimina(self): self.assertNotEqual(self.evaluate(requisitos=[{'texto':'Kotlin','atendido':False,'obrigatorio':False}])['estado'],'descartada')
    def test_sem_fonte_pendente(self): self.assertEqual(self.evaluate(requisitos=[{'texto':'Java','atendido':True,'fatos':['inventado']}])['estado'],'aguardando_dados')
    def test_data_desconhecida_nao_e_recente(self): self.assertFalse(self.evaluate()['publicacao_24h'])
    def test_veracidade(self):
        self.assertTrue(Revisor().review([{'id':'java','texto':'Java em projeto pessoal'}],self.f)['aprovado'])
        with self.assertRaises(ValueError): Revisor().review([{'id':'java','texto':'Java profissional por 3 anos'}],self.f)
    def test_dedup_tracking_requisicao(self):
        key=self.s.ingest(self.j)
        other=dict(self.j,url='https://example.org/jobs/1?utm_source=linkedin')
        self.assertEqual(key,self.s.ingest(other))
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        self.assertEqual(identity(self.j),identity(dict(self.j,url='https://outro.org/vaga')))
    def test_concorrencia(self):
        s2=Store(Path(self.tmp.name)/'test.sqlite'); self.addCleanup(s2.db.close)
        with self.s.lock():
            with self.assertRaises(RuntimeError):
                with s2.lock(): pass
    def test_retomada_incerta_e_sem_reenvio(self):
        key=self.s.ingest(self.j); self.s.transition(key,'enviando','simulação isolada')
        self.s.reconcile()
        self.assertEqual(self.s.db.execute('SELECT state FROM jobs').fetchone()[0],'envio_incerto')
        with self.assertRaises(ValueError): self.s.transition(key,'pronta','repetir')
    def test_enviada_exige_evidencia(self):
        key=self.s.ingest(self.j)
        with self.assertRaises(ValueError): self.s.transition(key,'enviada','clique não basta')
        self.s.transition(key,'enviando','teste sem rede')
        with self.assertRaises(ValueError): self.s.transition(key,'enviada','timeout',{})
        Executor(self.s).confirm(key,{'confirmacao':'protocolo fictício somente teste','referencia':'arquivo de teste local'})
        self.assertEqual(self.s.db.execute('SELECT state FROM jobs').fetchone()[0],'enviada')
    def test_executor_bloqueia_gates_incompletos(self):
        key=self.s.ingest(self.j); self.s.transition(key,'pronta','teste')
        write(Path(self.tmp.name)/'config/politica_autorizacao.yaml',{'candidaturas_autorizadas':False})
        with patch('src.core.ROOT',Path(self.tmp.name)), self.assertRaises(ValueError):
            Executor(self.s).reserve(key,{'autorizacao':True},self.tmp.name)
    def test_url_insegura(self):
        with self.assertRaises(ValueError): canonical('http://example.com')
        with self.assertRaises(ValueError): canonical('https://secret:senha@example.com')
    def test_entrada_incompleta_nao_e_elegivel(self):
        with self.assertRaises(ValueError): Pesquisador().validate({'empresa':'Acme'})
        job=dict(self.j,consultado_em='2026-11-12',fonte='https://example.org',descricao_resumida='teste',requisitos=[])
        with self.assertRaises(ValueError): Pesquisador().validate(job)

if __name__=='__main__': unittest.main()
