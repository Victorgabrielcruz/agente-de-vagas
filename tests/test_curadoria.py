import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from src.core import write
from src.curadoria import build_daily
from tests.fixtures_verificacao import prepare_root
from src.curadoria import select_jobs, partition_jobs, coverage_status, SEARCH_GROUPS, recent_publications

class CuradoriaTests(unittest.TestCase):
    def job(self,n,**kw):
        return dict(empresa='Empresa',titulo='Dev Júnior',url=f'https://empresa.com/vagas/{n}',**kw)

    def test_latest_publication_first_unknown_last(self):
        jobs=[self.job(1),self.job(2,publicada_em='2026-11-10'),self.job(3,publicada_em='2026-11-12')]
        self.assertEqual([j['url'].rsplit('/',1)[1] for j in select_jobs(jobs)],['3','2','1'])

    def test_exclude_closed_incompatible_already_applied_and_duplicate(self):
        jobs=[self.job(1),self.job(1),self.job(2,ativa=False),self.job(3,incompatibilidades=['Salário abaixo do piso']),self.job(4)]
        result=select_jobs(jobs,['https://empresa.com/vagas/4'])
        self.assertEqual(len(result),1)

    def test_unknown_conditions_are_not_called_compatible(self):
        self.assertEqual(select_jobs([self.job(1)])[0]['situacao'],'Conferir condições')
        self.assertEqual(select_jobs([self.job(1,criterios_confirmados=True)])[0]['situacao'],'Compatível')

    def test_application_on_another_portal_does_not_hide_other_roles(self):
        applied = [dict(empresa='Empresa', titulo='Dev Júnior', url='https://outro.com/123')]
        jobs = [self.job(1), dict(self.job(2), titulo='Analista QA Júnior')]
        result = select_jobs(jobs, sent_jobs=applied)
        self.assertEqual([j['titulo'] for j in result], ['Analista QA Júnior'])

    def test_completed_delivery_does_not_rebuild_or_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write(root/'data/entregas/2026-11-12.json',{'planilha_publicada':True,'email_enviado':True,'total':11})
            with patch('src.curadoria.ROOT',root):
                result=build_daily(root/'missing-input.json','not executed',settings={'modo':'curadoria_manual'},at='2026-11-12T14:00:00-03:00')
            self.assertTrue(result['duplicado'])
            self.assertFalse((root/'relatorios').exists())

    def test_degree_exception_does_not_waive_other_requirements(self):
        jobs=[self.job(1,exige_graduacao_completa=True,incompatibilidades=['Ensino superior completo']),self.job(2,exige_graduacao_completa=True,incompatibilidades=['Ensino superior completo','Cidade incompatível']),self.job(3)]
        main,degree,english=partition_jobs(select_jobs(jobs))
        self.assertEqual(len(main),1)
        self.assertEqual(len(degree),1)
        self.assertEqual(degree[0]['situacao'],'Graduação completa exigida')

    def test_english_exception_keeps_other_filters_and_does_not_duplicate_degree(self):
        jobs=[self.job(1,exige_ingles_acima_perfil=True,nivel_ingles_exigido='avançado',incompatibilidades=['Inglês avançado obrigatório']),
              self.job(2,exige_ingles_acima_perfil=True,incompatibilidades=['Inglês acima do perfil','Salário abaixo do piso']),
              self.job(3,exige_ingles_acima_perfil=True,exige_graduacao_completa=True,incompatibilidades=['Inglês acima do perfil','Graduação completa']),
              self.job(4,incompatibilidades=['Inglês acima do perfil'])]
        main,degree,english=partition_jobs(select_jobs(jobs))
        self.assertEqual((len(main),len(degree),len(english)),(0,0,2))
        self.assertEqual(english[0]['situacao'],'Inglês acima do nível atual')
        self.assertTrue(any('consultar perfil confirmado' in p for p in english[0]['pendencias']))
        self.assertTrue(any('formação ainda não confirmada' in p for p in english[1]['pendencias']))

    def test_limit_or_many_results_does_not_imply_sufficient_coverage(self):
        self.assertEqual(coverage_status({'segundos':None})['status'],'parcial')
        result=coverage_status({'segundos':1800,'consultas':[],'vagas_encontradas':100})
        self.assertEqual(result['status'],'parcial')
        self.assertEqual(result['motivo_encerramento'],'cobertura_incompleta')

    def test_no_query_cap_and_collected_review_is_distinct_from_search_coverage(self):
        queries=[{'concluida':True} for _ in range(45)]
        audit={'segundos':3600,'consultas':queries,'candidatas_sem_avaliacao':0,'analise_coletadas_concluida':True}
        result=coverage_status(audit)
        self.assertEqual(result['status'],'analise_das_encontradas_concluida')
        self.assertEqual(result['consultas_registradas'],45)
        audit['candidatas_sem_avaliacao']=1
        self.assertEqual(coverage_status(audit)['status'],'parcial')

    def test_coverage_requires_groups_windows_evaluation_and_saturation(self):
        queries=[{'grupo':g,'janela':'24h','tipo_fonte':'buscador','concluida':True} for g in SEARCH_GROUPS]
        audit={'consultas':queries,'candidatas_sem_avaliacao':0}
        self.assertEqual(coverage_status(audit)['status'],'parcial')
        queries.extend([{'janela':'7d','tipo_fonte':'oficial','ampliacao':True,'novas':0,'concluida':True} for _ in range(2)])
        self.assertEqual(coverage_status(audit)['status'],'cobertura_planejada_concluida')

    def test_old_groups_alone_do_not_complete_expanded_search(self):
        queries=[{'grupo':g,'janela':'24h','tipo_fonte':'buscador','concluida':True}
                 for g in SEARCH_GROUPS if g not in ('cargos_equivalentes','sem_nivel')]
        queries.extend([{'janela':'7d','tipo_fonte':'oficial','ampliacao':True,'novas':0,'concluida':True} for _ in range(2)])
        result=coverage_status({'consultas':queries,'candidatas_sem_avaliacao':0})
        self.assertEqual(result['status'],'parcial')
        self.assertEqual(result['grupos_faltantes'],['cargos_equivalentes','sem_nivel'])


    def test_seven_day_window_rejects_old_unknown_future_and_aggregator_dates(self):
        stamp='2026-11-16T07:00:00-03:00'
        def dated(n,date,kind='oficial',**extra):
            return self.job(n,publicada_em=date,tipo_data=kind,fonte_data='Fonte verificavel',**extra)
        jobs=[dated(1,'2026-11-16T06:00:00-03:00'),
              dated(2,'2026-11-09T07:00:00-03:00'),
              dated(3,'2026-11-09T06:59:59-03:00'),
              self.job(4),dated(5,'2026-11-17'),dated(6,'2026-11-15','agregador'),
              dated(7,'2026-11-16','republicacao'),
              dated(8,'2026-11-15T18:00:00Z'),
              dated(9,'2026-11-09')]
        kept,rejected=recent_publications(jobs,stamp)
        self.assertEqual([j['url'].rsplit('/',1)[1] for j in kept],['1','8','2'])
        self.assertEqual(len(rejected),6)

    def test_daily_build_enforces_recency_for_all_three_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            jobs=[self.job(1,publicada_em='2026-11-15',tipo_data='oficial',fonte_data='Fonte'),
                  self.job(2,publicada_em='2026-10-15',tipo_data='oficial',fonte_data='Fonte',exige_graduacao_completa=True),
                  self.job(3,exige_ingles_acima_perfil=True)]
            write(root/'inbox.json',jobs)
            settings=prepare_root(root)
            with patch('src.curadoria.ROOT',root):
                result=build_daily(root/'inbox.json','verificacao',settings=settings,sent_urls=[],at='2026-11-16T07:00:00-03:00')
            self.assertEqual((result['total_principal'],result['total_graduacao_completa'],result['total_ingles_acima_perfil']),(1,0,0))
            self.assertEqual(result['excluidas_por_recencia'],2)

if __name__=='__main__': unittest.main()
