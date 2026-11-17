import unittest
from datetime import datetime,timedelta
from src.core import BR
from src.preflight import check_portal

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,11,12,12,tzinfo=BR)
        self.policy={'envio_producao_global':True}
        self.record={'regras_permitidas':True,'fluxo_validado':True,'perfil_validado':True,'sessao_validada':True,'envio_habilitado':True,'evidencia_fluxo':'evidência de teste local, sem rede','verificado_em':self.at.isoformat(),'bloqueios':[]}
    def check(self,record=None,policy=None,url='https://example.org/jobs/1'):
        return check_portal(url,policy or self.policy,{'validade_horas':24,'portais':{'example.org':record or self.record}},self.at)
    def test_completo(self): self.assertTrue(self.check()['habilitado'])
    def test_global_desabilitado_prevalece(self): self.assertFalse(self.check(policy={'envio_producao_global':False})['habilitado'])
    def test_sem_fluxo_ou_evidencia(self):
        for update in ({'fluxo_validado':False},{'evidencia_fluxo':None},{'perfil_validado':False}):
            self.assertFalse(self.check(record=dict(self.record,**update))['habilitado'])
    def test_expirado(self): self.assertFalse(self.check(record=dict(self.record,verificado_em=(self.at-timedelta(hours=25)).isoformat()))['habilitado'])
    def test_dominio_diferente_nao_herda(self): self.assertFalse(self.check(url='https://outro.example.org/jobs/1')['habilitado'])

if __name__=='__main__': unittest.main()
