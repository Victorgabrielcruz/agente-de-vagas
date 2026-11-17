import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.busca import nivel_titulo, plano_busca, plano_interno
from src.curadoria import select_jobs
from src.core import Analista
from src.core import write


class BuscaTests(unittest.TestCase):
    def test_individual_plan_covers_every_key_company_portal_region_and_window(self):
        prefs={'mercado':'Brasil','cidades_presenciais':['Cidade A','Cidade B'],
               'cargos_adicionais':['Forward Deployed Engineer'],
               'empresas_preferidas':['Empresa A','Empresa B']}
        sources={'chaves_individuais':[{'termo':'Java','grupo':'java_spring'},
                   {'termo':'Python','grupo':'python_qa_automacao'},
                   {'termo':'Java','grupo':'java_spring'}],
                 'modificadores_nivel':['Jr'], 'pesquisar_cada_empresa':True,
                 'fontes':[{'busca_interna':{'habilitada':True,
                     'todas_chaves_obrigatorias':True,'identificador_cache':p,
                     'janelas':['24h','7d'],'grupos':[]}}
                     for p in ('LinkedIn interno','Gupy interno')]}
        plan=plano_interno(prefs,sources)
        expected_keys={'Java','Python','Forward Deployed Engineer','software Jr','Empresa A','Empresa B'}
        self.assertEqual(len(plan),6*2*3*2)
        for portal in ('LinkedIn interno','Gupy interno'):
            for region in ('Brasil','Cidade A','Cidade B'):
                for window in ('24h','7d'):
                    self.assertEqual({q['chave'] for q in plan if
                        (q['fonte'],q['localidade'],q['janela'])==(portal,region,window)},expected_keys)
        self.assertTrue(all(q['consulta']==q['chave'] and 'concluida' not in q for q in plan))
        self.assertEqual(plan,plano_interno(prefs,sources))
        windows=[q['janela'] for q in plan]
        self.assertEqual(windows,sorted(windows))

    def test_equivalentes_e_limites_de_palavra(self):
        for titulo in ('Analista de Sistemas I', 'Programador I', 'Software Engineer I',
                       'Software Developer I', 'Associate Software Engineer', 'Entry-level Developer'):
            with self.subTest(titulo=titulo):
                self.assertEqual(nivel_titulo(titulo), 'equivalente')
        for titulo in ('Software Engineer II', 'Software Developer III', 'Developer 2',
                       'Desenvolvedor Pleno', 'Programador Sênior', 'Tech Lead'):
            self.assertEqual(nivel_titulo(titulo), 'fora_escopo')
        self.assertEqual(nivel_titulo('Desenvolvedor Java 8 Júnior'), 'junior')
        self.assertEqual(nivel_titulo('Desenvolvedor Java'), 'nao_informado')

    def test_curadoria_preserva_potenciais_sem_declarar_elegibilidade(self):
        def job(n, titulo, **kw):
            return dict(empresa='Empresa', titulo=titulo, url=f'https://example.org/{n}',
                        criterios_confirmados=True, **kw)
        jobs = [job(1, 'Analista de Sistemas I'), job(2, 'Desenvolvedor Java'),
                job(3, 'Software Engineer II'), job(4, 'Estagiário Java'),
                job(5, 'Desenvolvedor Python', anos_profissionais_obrigatorios=4),
                job(6, 'Associate Developer', incompatibilidades=['Cidade incompatível'])]
        selected = select_jobs(jobs)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(j['situacao'] == 'Conferir condições' for j in selected))
        self.assertTrue(all(any('experiência exigida' in p for p in j['pendencias']) for j in selected))

    def test_analisador_nao_confunde_engineer_ii_nem_libera_equivalente(self):
        prefs = dict(clt_acima_de=4000, empresas_preferidas=[], limiar_auto=80,
                     pesos=dict(tecnica=35, junior=25, modalidade=20, empresa=10, atualidade=10))
        job = dict(empresa='Empresa', mercado='Brasil', modalidade='remoto', aceita_bh=True,
                   contrato='CLT', ativa=True, vinculo_oficial_verificado=True, requisitos=[])
        analyst = Analista(prefs, {'afirmacoes': {}})
        for titulo in ('Software Engineer I', 'Analista de Sistemas I', 'Desenvolvedor Java'):
            result = analyst.evaluate(dict(job, titulo=titulo))
            self.assertEqual(result['estado'], 'aguardando_dados')
            self.assertIn('Validar nível pelo trabalho real', result['pendencias'])
        self.assertEqual(analyst.evaluate(dict(job, titulo='Software Engineer II'))['estado'], 'descartada')

    def test_plano_nao_simula_pesquisa_realizada(self):
        queries = plano_busca(cidades=['Cidade Teste'])
        self.assertEqual({q['grupo'] for q in queries}, {'cargos_equivalentes', 'sem_nivel'})
        self.assertEqual({q['janela'] for q in queries}, {'24h', '7d'})
        self.assertTrue(all('concluida' not in q for q in queries))
        self.assertTrue(any('Cidade Teste' in q['consulta'] for q in queries))
        self.assertTrue(any('remoto' in q['consulta'] for q in queries))

    def test_cli_reads_configured_role_without_waiving_seniority(self):
        from src.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root/'config/preferencias.yaml', {'cargos_adicionais': ['Forward Deployed Engineer'], 'cidades_presenciais':['Cidade Teste']})
            with patch('src.cli.ROOT', root), patch('sys.argv', ['vagas', 'plano-busca']), patch('builtins.print') as output:
                main()
            queries = json.loads(output.call_args.args[0])
        extra = [q for q in queries if 'Forward Deployed Engineer' in q['consulta']]
        self.assertEqual(len(extra), 4)
        self.assertEqual({q['janela'] for q in extra}, {'24h', '7d'})
        self.assertTrue(all(q['grupo'] == 'sem_nivel' and 'concluida' not in q for q in extra))
        jobs = [dict(empresa='Empresa', titulo=title, url=f'https://example.org/{n}') for n, title in
                enumerate(['Forward Deployed Engineer', 'Senior Forward Deployed Engineer', 'Forward Deployed Engineer II'])]
        selected = select_jobs(jobs)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['situacao'], 'Conferir condições')


if __name__ == '__main__':
    unittest.main()
