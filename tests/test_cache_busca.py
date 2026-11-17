import tempfile
import sqlite3
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src import cache_busca as cache
from src.core import read, write
from src.curadoria import build_daily
from src.verificacao import verificar, SEARCH_GROUPS
from tests.fixtures_verificacao import prepare_root

STAMP = '2026-11-16T07:00:00-03:00'


def query(group='engenharia_software', text='software junior', **extra):
    return dict(grupo=group, consulta=text, fonte='buscador externo',
                tipo_fonte='buscador', janela='24h', **extra)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        prepare_root(self.root)

    def start(self, plan=None):
        return cache.start(self.root, plan or [query()], at=STAMP)

    def change(self, action, at=STAMP, **kw):
        return cache.mutate(self.root, action, at=at, **kw)

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def result(self, jobs=None):
        return {'evidencia': 'Consulta efetivamente realizada na fonte', 'novas': len(jobs or []), 'candidatas': jobs or []}

    def test_quota_waits_until_observed_reset_and_preserves_progress(self):
        state = self.start([query(), query(text='outra consulta')])
        task = state['consultas_pendentes'][0]['id']
        self.change('registrar', task_id=task, result=self.result())
        deadline = '2026-11-16T15:00:00Z'
        paused = self.change('pausar', reason='limite_5h', retry_at=deadline,
                             evidence='Ferramenta informou limite e reset às 12h Brasília')
        self.assertEqual(paused['proxima_tentativa_em'], '2026-11-16T12:00:00-03:00')
        self.assertEqual(len(paused['consultas_pendentes']), 1)
        self.assertEqual(self.change('retomar', at='2026-11-16T11:59:00-03:00')['estado'], 'aguardando_retentativa')
        with self.assertRaisesRegex(ValueError, 'Limite da assinatura'):
            self.start()
        resumed = self.change('retomar', at='2026-11-16T12:00:00-03:00')
        self.assertEqual(resumed['estado'], 'pesquisando')
        self.assertEqual(len(resumed['consultas_pendentes']), 1)

    def test_weekly_limit_survives_day_change_and_requires_revalidation(self):
        self.start()
        self.change('pausar', reason='limite_semanal',
                    retry_at='2026-11-23T07:00:00-03:00', evidence='Reset semanal informado')
        with self.assertRaisesRegex(ValueError, 'Limite da assinatura'):
            cache.start(self.root, [query()], at='2026-11-17T07:00:00-03:00')
        with self.assertRaisesRegex(ValueError, 'revalidação'):
            self.change('retomar', at='2026-11-23T07:00:00-03:00')
        fresh = cache.start(self.root, [query()], at='2026-11-23T07:00:00-03:00')
        self.assertEqual(fresh['estado'], 'pesquisando')
        db = sqlite3.connect(cache.dbpath(self.root))
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM checkpoints').fetchone()[0], 2)
        finally:
            db.close()

    def test_quota_unknown_reset_blocks_and_rejects_invented_or_shorter_deadlines(self):
        self.start()
        for deadline in ('2026-11-16T12:00:00', '2026-11-16T06:00:00-03:00'):
            with self.assertRaises(ValueError):
                self.change('pausar', reason='limite_5h', retry_at=deadline, evidence='Limite observado')
        with self.assertRaisesRegex(ValueError, 'evidência'):
            self.change('pausar', reason='limite_semanal')
        self.change('pausar', reason='limite_semanal',
                    retry_at='2026-11-23T07:00:00-03:00', evidence='Limite semanal observado')
        kept = self.change('pausar', reason='limite_5h',
                           retry_at='2026-11-16T12:00:00-03:00', evidence='Ambos esgotados')
        self.assertEqual(kept['proxima_tentativa_em'], '2026-11-23T07:00:00-03:00')
        blocked = self.change('pausar', reason='limite_semanal', evidence='Prazo indisponível')
        self.assertEqual(blocked['estado'], 'bloqueada')
        with self.assertRaises(ValueError):
            self.change('retomar')
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.change('desbloquear', at='2026-11-24T07:00:00-03:00', reason='Liberação confirmada na ferramenta')['estado'], 'pesquisando')

    def test_empty_status_does_not_create_database(self):
        self.assertEqual(cache.status(self.root, at=STAMP)['estado'], 'sem_cache')
        self.assertFalse(cache.dbpath(self.root).exists())

    def test_internal_sources_require_real_portal_tasks_and_disclose_isolation(self):
        write(self.root/'config/fontes.yaml', {'fontes': [
            {'nome': name, 'busca_interna': {'habilitada': True,
             'identificador_cache': name+' interno',
             'grupos': ['engenharia_software'], 'janelas': ['24h']}}
            for name in ('LinkedIn', 'Gupy')]})
        plan = [query(text='site:linkedin.com site:gupy.io software'),
                dict(query(text='software LinkedIn'), fonte='LinkedIn interno'),
                dict(query(text='software Gupy'), fonte='Gupy interno')]
        state = self.start(plan)
        ids = {q['fonte']: q['id'] for q in state['consultas_pendentes']}
        state = self.change('registrar', task_id=ids['buscador externo'], result=self.result())
        self.assertEqual(len(state['cobertura']['consultas_internas_faltantes']), 2)
        state = self.change('registrar', task_id=ids['LinkedIn interno'], result=self.result())
        self.assertEqual(len(state['cobertura']['consultas_internas_faltantes']), 1)
        state = self.change('isolar-fonte', task_id=ids['Gupy interno'], result={
            'motivo': 'fonte_indisponivel', 'evidencia': 'Portal indisponível observado'})
        self.assertEqual(state['cobertura']['consultas_internas_faltantes'], [])
        self.assertFalse(state['cobertura']['cobertura_integral'])
        self.assertEqual(len(state['cobertura']['fontes_indisponiveis']), 1)

    def test_internal_coverage_configuration_is_validated_before_cache_creation(self):
        write(self.root/'config/fontes.yaml', {'fontes': [{'busca_interna': {
            'habilitada': True, 'identificador_cache': 'Gupy interno',
            'grupos': ['grupo_inexistente'], 'janelas': ['7d']}}]})
        with self.assertRaisesRegex(ValueError, 'cobertura interna'):
            self.start()

    def test_individual_keys_are_auto_added_and_one_key_cannot_cover_the_other(self):
        prefs=read(self.root/'config/preferencias.yaml')
        prefs.update(cidades_presenciais=['Cidade Teste'],cargos_adicionais=[])
        write(self.root/'config/preferencias.yaml',prefs)
        write(self.root/'config/fontes.yaml',{'chaves_individuais':[
            {'termo':'Java','grupo':'engenharia_software'},
            {'termo':'Python','grupo':'engenharia_software'}], 'fontes':[
                {'busca_interna':{'habilitada':True,'todas_chaves_obrigatorias':True,
                 'identificador_cache':'LinkedIn interno',
                 'grupos':['engenharia_software'],'janelas':['24h']}}]})
        # Mesmo um plano manual omitindo todas as chaves recebe a fila obrigatória.
        plan=[query(group=g,text=g) for g in SEARCH_GROUPS]
        plan += [dict(query(text='ampliacao 1'),ampliacao=True,janela='7d',tipo_fonte='oficial'),
                 dict(query(text='ampliacao 2'),ampliacao=True)]
        state=self.start(plan)
        individual=[q for q in state['consultas_pendentes'] if q.get('chave') and q['modalidade']=='remoto']
        self.assertEqual(len(individual),2)
        for task in state['consultas_pendentes']:
            if not task.get('chave'):
                self.change('registrar',task_id=task['id'],result=self.result())
            elif task['modalidade']!='remoto':
                self.change('registrar',task_id=task['id'],result=dict(self.result(),
                    termo_pesquisado=task['chave'],url_busca='https://www.linkedin.com/jobs/search/',
                    filtros_observados={'localidade':'Cidade Teste'},limitacoes_filtros=[]))
        with self.assertRaisesRegex(ValueError,'incompleta'):
            self.change('exportar')
        result=dict(self.result(),termo_pesquisado=individual[0]['chave'],
                    url_busca='https://www.linkedin.com/jobs/search/',
                    filtros_observados={'localidade':'Brasil','data':'24h'},limitacoes_filtros=[])
        with self.assertRaisesRegex(ValueError,'termo exato'):
            self.change('registrar',task_id=individual[1]['id'],result=result)
        with self.assertRaisesRegex(ValueError,'URL do portal'):
            self.change('registrar',task_id=individual[0]['id'],result=dict(result,url_busca='https://google.com'))
        self.change('registrar',task_id=individual[0]['id'],result=result)
        resumed=cache.start(self.root,plan,at=STAMP)
        self.assertEqual(resumed['cobertura']['chaves_individuais']['concluidas'],3)
        self.assertEqual(resumed['cobertura']['chaves_individuais']['pendentes'],1)
        with self.assertRaisesRegex(ValueError,'incompleta'):
            self.change('exportar')
        self.change('isolar-fonte',task_id=individual[1]['id'],result={
            'motivo':'http403','evidencia':'Recusa observada; não contornar.'})
        ready=self.change('exportar')
        self.assertEqual(ready['estado'],'pronta')
        self.assertEqual(ready['cobertura']['chaves_individuais'],
                         {'total':4,'concluidas':3,'indisponiveis':1,'pendentes':0})
        self.assertFalse(ready['cobertura']['cobertura_integral'])

    def test_restart_preserves_done_queries_and_pending_analysis(self):
        state = self.start([query(), query(text='java junior')])
        task = state['consultas_pendentes'][0]['id']
        job = dict(empresa='Empresa', titulo='Dev Júnior', url='https://example.org/1')
        self.change('registrar', task_id=task, result=self.result([job]))
        self.change('pausar', reason='conexao')
        # Nova leitura simula outro processo/sessão; iniciar novamente não apaga o checkpoint.
        resumed = cache.start(self.root, [query(), query(text='java junior')], at=STAMP)
        self.assertEqual(len(resumed['consultas_pendentes']), 1)
        self.assertEqual(len(resumed['candidatas_pendentes']), 1)
        self.assertEqual(resumed['estado'], 'aguardando_retentativa')

    def test_retry_delay_backoff_and_no_work_before_due(self):
        task = self.start()['consultas_pendentes'][0]['id']
        first = self.change('pausar', reason='timeout')
        self.assertEqual(first['proxima_tentativa_em'], '2026-11-16T07:05:00-03:00')
        early = self.change('retomar', at='2026-11-16T07:04:59-03:00')
        self.assertEqual(early['estado'], 'aguardando_retentativa')
        with self.assertRaises(ValueError):
            self.change('registrar', task_id=task, result=self.result())
        self.change('retomar', at='2026-11-16T07:05:00-03:00')
        second = self.change('pausar', at='2026-11-16T07:06:00-03:00', reason='timeout')
        self.assertEqual(second['proxima_tentativa_em'], '2026-11-16T07:16:00-03:00')
        # Notificação repetida da mesma pausa não adia nem aumenta a tentativa.
        repeat = self.change('pausar', at='2026-11-16T07:07:00-03:00', reason='timeout')
        self.assertEqual(repeat['falhas_consecutivas'], 2)
        self.assertEqual(repeat['proxima_tentativa_em'], second['proxima_tentativa_em'])

    def test_non_transient_block_has_no_timer_and_requires_explicit_resolution(self):
        self.start()
        blocked = self.change('pausar', reason='captcha')
        self.assertEqual(blocked['estado'], 'bloqueada')
        self.assertIsNone(blocked['proxima_tentativa_em'])
        with self.assertRaises(ValueError):
            self.change('retomar')
        self.assertEqual(self.change('desbloquear', reason='Usuário resolveu no portal')['estado'], 'pesquisando')

    def test_isolated_source_keeps_failure_pending_and_allows_other_tasks(self):
        state=self.start([query(text='fonte recusada'),query(text='fonte acessível')])
        first,second=state['consultas_pendentes']
        info=self.change('isolar-fonte',task_id=first['id'],result={'motivo':'http403','evidencia':'Leitura pública retornou HTTP 403'})
        self.assertEqual(info['estado'],'pesquisando')
        self.assertEqual([q['id'] for q in info['consultas_pendentes']],[second['id']])
        self.assertEqual(len(info['consultas_adiadas']),1)
        self.assertEqual(info['cobertura']['consultas_registradas'],0)
        with cache.transaction(self.root) as db:
            _,saved=cache.latest(db)
            self.assertFalse(saved['tarefas'][first['id']]['concluida'])
            self.assertIsNone(saved['tarefas'][first['id']]['resultado'])
        with self.assertRaisesRegex(ValueError,'não deve ser repetida'):
            self.change('registrar',task_id=first['id'],result=self.result())
        self.assertEqual(self.change('registrar',task_id=second['id'],result=self.result())['cobertura']['consultas_registradas'],1)

    def test_legacy_global_source_block_can_be_scoped_without_clearing_other_blocks(self):
        task=self.start()['consultas_pendentes'][0]['id']
        with cache.transaction(self.root) as db:
            sid,saved=cache.latest(db)
            saved.update(estado='bloqueada',motivo='fonte_oficial_http403')
            cache.save(db,sid,saved)
        resumed=self.change('isolar-fonte',task_id=task,result={'motivo':'http403','evidencia':'HTTP 403 registrado antes da correção'})
        self.assertEqual(resumed['estado'],'pesquisando')
        self.change('pausar',reason='captcha')
        with self.assertRaisesRegex(ValueError,'Bloqueio global'):
            self.change('isolar-fonte',task_id=task,result={'motivo':'http403','evidencia':'Outro bloqueio'})

    def test_export_with_unavailable_source_discloses_partial_coverage(self):
        plan=[query(group=g,text=g) for g in SEARCH_GROUPS]
        plan += [dict(query(text='ampliar primeira'),ampliacao=True,janela='7d',tipo_fonte='oficial'),
                 dict(query(text='ampliar segunda'),ampliacao=True),query(text='fonte bloqueada')]
        state=self.start(plan)
        for task in state['consultas_pendentes'][:-1]:
            self.change('registrar',task_id=task['id'],result=self.result())
        blocked=state['consultas_pendentes'][-1]
        self.change('isolar-fonte',task_id=blocked['id'],result={'motivo':'http403','evidencia':'HTTP 403, não insistir'})
        info=self.change('exportar')
        self.assertEqual(info['estado'],'pronta')
        self.assertFalse(info['cobertura']['cobertura_integral'])
        self.assertNotEqual(info['cobertura']['status'],'cobertura_planejada_concluida')
        exported=read(self.root/'entrada/cobertura.json')
        self.assertEqual(len(exported['fontes_indisponiveis']),1)
        self.assertEqual(len(exported['consultas']),len(plan)-1)

    def test_config_change_and_new_day_preserve_old_cache_but_require_revalidation(self):
        self.start()
        prefs = read(self.root/'config/preferencias.yaml')
        write(self.root/'config/preferencias.yaml', dict(prefs, empresas_preferidas=['Outra']))
        with self.assertRaisesRegex(ValueError, 'revalidação'):
            self.change('retomar')
        new = self.start()
        self.assertEqual(len(new['consultas_pendentes']), 1)
        self.assertEqual(cache.status(self.root, at='2026-11-17T07:00:00-03:00')['cache_invalido'], 'dia_alterado')
        db = sqlite3.connect(cache.dbpath(self.root))
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM checkpoints').fetchone()[0], 2)
        finally:
            db.close()

    def test_pause_and_confirmed_delivery_block_resume_without_touching_cache(self):
        self.start()
        prefs = read(self.root/'config/preferencias.yaml')
        write(self.root/'config/preferencias.yaml', dict(prefs, pausado=True))
        before = cache.dbpath(self.root).read_bytes()
        with self.assertRaises(ValueError):
            self.change('retomar')
        self.assertEqual(cache.dbpath(self.root).read_bytes(), before)
        write(self.root/'config/preferencias.yaml', prefs)
        write(self.root/'data/entregas/2026-11-16.json', {'planilha_publicada': True, 'email_enviado': True})
        with self.assertRaisesRegex(ValueError, 'entrega_ja_confirmada'):
            self.change('retomar')

    def test_incomplete_cache_prevents_direct_generation(self):
        self.start()
        before = self.snapshot()
        with patch('src.curadoria.ROOT', self.root), self.assertRaisesRegex(ValueError, 'pesquisa_em_cache_pendente'):
            build_daily(self.root/'absent.json', 'não executado', at=STAMP)
        self.assertEqual(self.snapshot(), before)

    def test_record_failure_rolls_back_all_candidates_and_idempotent_success(self):
        task = self.start()['consultas_pendentes'][0]['id']
        job = dict(empresa='Empresa', titulo='Dev', url='https://example.org/1')
        with self.assertRaises(ValueError):
            self.change('registrar', task_id=task, result=self.result([job, dict(job, url='http://bad')]))
        self.assertEqual(len(cache.status(self.root, at=STAMP)['consultas_pendentes']), 1)
        self.assertFalse(cache.status(self.root, at=STAMP)['candidatas_pendentes'])
        self.change('registrar', task_id=task, result=self.result([job]))
        again = self.change('registrar', task_id=task, result=self.result([job]))
        self.assertEqual(len(again['candidatas_pendentes']), 1)

    def test_export_only_after_full_coverage_and_reexport_repairs_inputs(self):
        plan = [query(group=g, text=g) for g in SEARCH_GROUPS]
        plan += [dict(query(text='ampliacao 1'), ampliacao=True, janela='7d', tipo_fonte='oficial'),
                 dict(query(text='ampliacao 2'), ampliacao=True)]
        state = self.start(plan)
        with self.assertRaisesRegex(ValueError, 'incompleta'):
            self.change('exportar')
        for task in state['consultas_pendentes']:
            self.change('registrar', task_id=task['id'], result=self.result())
        ready = self.change('exportar')
        self.assertEqual(ready['estado'], 'pronta')
        self.assertTrue(ready['exportacao_coerente'])
        self.assertTrue(verificar(self.root, at=STAMP, exigir_sincronizacao=True)['ok'])
        write(self.root/'outro.json', [{'url': 'https://example.org/injetado'}])
        with patch('src.curadoria.ROOT', self.root), self.assertRaisesRegex(ValueError, 'difere'):
            build_daily(self.root/'outro.json', 'não executado', at=STAMP)
        write(self.root/'entrada/curadoria.json', [{'url': 'https://example.org/injetado'}])
        self.assertFalse(verificar(self.root, at=STAMP, exigir_sincronizacao=True)['ok'])
        self.assertTrue(self.change('exportar')['exportacao_coerente'])
        with self.assertRaises(FileNotFoundError):
            self.change('concluir')
        write(self.root/'data/entregas/2026-11-16.json', {'planilha_publicada': True, 'email_enviado': True})
        closed = self.change('concluir')
        self.assertEqual(closed['estado'], 'concluida')
        self.assertIn('limpeza', closed)

    def test_analysis_persists_through_restart_and_reopens_for_changed_source(self):
        task = self.start()['consultas_pendentes'][0]['id']
        job = dict(empresa='Empresa', titulo='Dev Júnior', url='https://example.org/1')
        self.change('registrar', task_id=task, result=self.result([job]))
        with self.assertRaises(ValueError):
            self.change('analisar', url=job['url'], result=job)
        self.change('analisar', url=job['url'], result=dict(job, evidencia_analise='Anúncio oficial lido', pendencias=['Salário não divulgado']))
        self.assertFalse(cache.status(self.root, at=STAMP)['candidatas_pendentes'])
        state = cache.start(self.root, [query(text='consulta complementar')], at=STAMP)
        self.assertFalse(state['candidatas_pendentes'])
        task = state['consultas_pendentes'][0]['id']
        self.change('registrar', task_id=task, result=self.result([dict(job, salario='R$ 5.000')]))
        self.assertEqual(len(cache.status(self.root, at=STAMP)['candidatas_pendentes']), 1)

    def test_expiry_and_corrupt_database_block_generation(self):
        write(self.root/'config/cache_busca.json', {'intervalos_minutos': [5], 'validade_horas': 1})
        self.start()
        with self.assertRaisesRegex(ValueError, 'cache_expirado'):
            self.change('retomar', at='2026-11-16T08:00:00-03:00')
        cache.dbpath(self.root).write_bytes(b'corrompido')
        result = verificar(self.root, at=STAMP, exigir_sincronizacao=True)
        self.assertIn('cache_invalido', {item['codigo'] for item in result['bloqueios']})

    def seed_cleanup(self, records):
        self.start()
        with cache.transaction(self.root) as db:
            _, prototype = cache.latest(db)
            db.execute('DELETE FROM checkpoints')
            for changes in records:
                state = dict(copy.deepcopy(prototype), tarefas={}, candidatas={}, **changes)
                cache.save(db, None, state)

    def test_cleanup_only_old_terminal_records_and_preserves_latest(self):
        self.seed_cleanup([
            {'estado': 'concluida', 'atualizado_em': '2026-11-08T06:00:00-03:00'},
            {'estado': 'invalidada', 'atualizado_em': '2026-11-08T06:00:00-03:00'},
            {'estado': 'concluida', 'atualizado_em': '2026-11-09T07:00:00-03:00'},  # exatamente sete dias
            {'estado': 'invalidada', 'atualizado_em': '2026-11-15T07:00:00-03:00'},
            {'estado': 'concluida', 'atualizado_em': '2026-11-08T06:00:00-03:00'},  # mais recente por id
        ])
        result = cache.cleanup(self.root, at=STAMP)
        self.assertEqual((result['removidos'], result['preservados']), (2, 3))
        self.assertEqual(cache.status(self.root, at=STAMP)['estado'], 'concluida')
        self.assertEqual(cache.cleanup(self.root, at=STAMP)['removidos'], 0)

    def test_cleanup_preserves_all_pending_and_unknown_or_malformed_records(self):
        old = '2026-10-01T07:00:00-03:00'
        rows = [{'estado': state, 'atualizado_em': old}
                for state in ('pesquisando', 'aguardando_retentativa', 'pronta', 'bloqueada', 'desconhecida')]
        self.seed_cleanup(rows + [{'estado': 'concluida', 'atualizado_em': STAMP}])
        with cache.transaction(self.root) as db:
            _, prototype = cache.latest(db)
            pending_query = dict(prototype, estado='invalidada', atualizado_em=old,
                                 tarefas={'q': {'concluida': False}})
            pending_analysis = dict(prototype, estado='invalidada', atualizado_em=old,
                                    candidatas={'url': {'revisada': False}})
            cache.save(db, None, pending_query)
            cache.save(db, None, pending_analysis)
            db.execute('INSERT INTO checkpoints(payload) VALUES(?)', ('não é JSON',))
        result = cache.cleanup(self.root, at=STAMP)
        self.assertEqual(result['removidos'], 0)
        self.assertEqual(result['invalidos_preservados'], 1)

    def test_cleanup_simulation_is_readonly_and_does_not_create_missing_database(self):
        self.assertEqual(cache.cleanup(self.root, at=STAMP)['removidos'], 0)
        self.assertFalse(cache.dbpath(self.root).exists())
        self.seed_cleanup([
            {'estado': 'concluida', 'atualizado_em': '2026-11-01T00:00:00-03:00'},
            {'estado': 'pesquisando', 'atualizado_em': STAMP}])
        before = self.snapshot()
        result = cache.cleanup(self.root, at=STAMP, simulate=True)
        self.assertEqual(result['elegiveis'], 1)
        self.assertEqual(result['removidos'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_cleanup_does_not_touch_history_deliveries_or_other_files_and_reclaims_space(self):
        self.seed_cleanup([
            {'estado': 'concluida', 'atualizado_em': '2026-11-01T00:00:00-03:00', 'dados_extra': 'x'*600000},
            {'estado': 'pesquisando', 'atualizado_em': STAMP}])
        write(self.root/'data/entregas/2026-11-01.json', {'email_enviado': True})
        (self.root/'data/candidaturas.sqlite').write_bytes(b'evidencia a preservar')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*')
                  if p.is_file() and p != cache.dbpath(self.root)}
        size = cache.dbpath(self.root).stat().st_size
        result = cache.cleanup(self.root, at=STAMP)
        self.assertEqual(result['removidos'], 1)
        self.assertTrue(result['compactado'])
        self.assertLess(cache.dbpath(self.root).stat().st_size, size)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*')
                 if p.is_file() and p != cache.dbpath(self.root)}
        self.assertEqual(before, after)

    def test_start_runs_cleanup_and_retention_can_be_configured_or_disabled(self):
        self.seed_cleanup([
            {'estado': 'concluida', 'atualizado_em': '2026-11-01T00:00:00-03:00'},
            {'estado': 'pesquisando', 'atualizado_em': STAMP}])
        write(self.root/'config/cache_busca.json', dict(cache.DEFAULTS, limpeza_automatica=False))
        self.assertEqual(self.start()['limpeza'], {'habilitada': False})
        write(self.root/'config/cache_busca.json', dict(cache.DEFAULTS, retencao_dias=30))
        self.assertEqual(self.start()['limpeza']['removidos'], 0)
        write(self.root/'config/cache_busca.json', cache.DEFAULTS)
        self.assertEqual(self.start()['limpeza']['removidos'], 1)
        write(self.root/'config/cache_busca.json', dict(cache.DEFAULTS, retencao_dias=0))
        with self.assertRaises(ValueError):
            cache.cleanup(self.root, at=STAMP)

    def test_invalidation_starts_retention_clock_when_session_is_superseded(self):
        self.start()
        with cache.transaction(self.root) as db:
            sid, state = cache.latest(db)
            state.update(criado_em='2026-10-01T07:00:00-03:00', atualizado_em='2026-10-01T07:00:00-03:00')
            state['tarefas'] = {}
            cache.save(db, sid, state)
        self.start()
        with cache.transaction(self.root) as db:
            first = json.loads(db.execute('SELECT payload FROM checkpoints ORDER BY id LIMIT 1').fetchone()[0])
        self.assertEqual(first['estado'], 'invalidada')
        self.assertEqual(first['invalidada_em'], STAMP)
        self.assertEqual(cache.cleanup(self.root, at=STAMP)['removidos'], 0)
