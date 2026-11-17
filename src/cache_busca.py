"""Checkpoints transacionais de pesquisa assistida; não executa buscas ou timers."""
import contextlib
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .core import canonical, read, write
from .verificacao import execution_time

DEFAULTS = {'intervalos_minutos': [5, 10, 20, 30, 60], 'validade_horas': 24,
            'limpeza_automatica': True, 'retencao_dias': 7}
TRANSIENT = {'timeout', 'conexao', 'limite_temporario', 'interrupcao'}
QUOTAS = {'limite_5h', 'limite_semanal'}


def quota_waiting(state, stamp):
    return bool(state and state.get('motivo') in QUOTAS and
                (not state.get('proxima_tentativa_em') or stamp < state['proxima_tentativa_em']))


def config(root):
    path = Path(root)/'config/cache_busca.json'
    value = dict(DEFAULTS, **read(path)) if path.exists() else dict(DEFAULTS)
    delays = value.get('intervalos_minutos')
    if not isinstance(delays, list) or not delays or any(type(n) is not int or n < 1 for n in delays):
        raise ValueError('Intervalos de retomada inválidos')
    if type(value.get('validade_horas')) is not int or value['validade_horas'] < 1:
        raise ValueError('Validade do cache inválida')
    if type(value['limpeza_automatica']) is not bool:
        raise ValueError('limpeza_automatica deve ser booleana')
    if type(value['retencao_dias']) is not int or value['retencao_dias'] < 1:
        raise ValueError('Retenção do cache deve ser um número inteiro positivo de dias')
    return value


def fingerprint(root):
    digest = hashlib.sha256()
    for name in ('config/preferencias.yaml', 'config/entrega_diaria.json',
                 'config/fontes.yaml', 'config/politica_autorizacao.yaml',
                 'perfil/fatos_confirmados.json', 'perfil/respostas_aprovadas.json'):
        path = Path(root)/name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b'<ausente>')
    return digest.hexdigest()


def dbpath(root):
    return Path(root)/'data/cache_busca.sqlite'


@contextlib.contextmanager
def transaction(root):
    path = dbpath(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS checkpoints(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def latest(db):
    row = db.execute('SELECT id,payload FROM checkpoints ORDER BY id DESC LIMIT 1').fetchone()
    return (row[0], json.loads(row[1])) if row else (None, None)


def save(db, sid, state):
    payload = json.dumps(state, ensure_ascii=False)
    if sid is None:
        return db.execute('INSERT INTO checkpoints(payload) VALUES(?)', (payload,)).lastrowid
    db.execute('UPDATE checkpoints SET payload=? WHERE id=?', (payload, sid))
    return sid


def cleanup(root, at=None, simulate=False):
    """Remove somente checkpoints terminais antigos, nunca o mais recente ou pendências."""
    stamp = execution_time(at)
    cutoff = datetime.fromisoformat(stamp) - timedelta(days=config(root)['retencao_dias'])
    result = {'ok': True, 'simulacao': simulate, 'retencao_dias': config(root)['retencao_dias'],
              'elegiveis': 0, 'removidos': 0, 'preservados': 0, 'invalidos_preservados': 0,
              'compactado': False, 'compactacao_pendente': False}
    path = dbpath(root)
    if not path.exists():
        return result
    # Modo rw não cria outro banco se o arquivo desaparecer entre inspeção e abertura.
    db = sqlite3.connect(path.resolve().as_uri()+('?mode=ro' if simulate else '?mode=rw'), uri=True, timeout=10)
    try:
        db.execute('BEGIN' if simulate else 'BEGIN IMMEDIATE')
        latest_id = db.execute('SELECT max(id) FROM checkpoints').fetchone()[0]
        eligible = []
        for sid, payload in db.execute('SELECT id,payload FROM checkpoints'):
            try:
                state = json.loads(payload)
                updated = datetime.fromisoformat(state['atualizado_em'])
                if updated.tzinfo is None:
                    raise ValueError('Data de checkpoint sem fuso')
                tasks, candidates = state['tarefas'], state['candidatas']
                if not isinstance(tasks, dict) or not isinstance(candidates, dict):
                    raise ValueError('Checkpoint inválido')
                pending = (any(t.get('concluida') is not True for t in tasks.values()) or
                           any(c.get('revisada') is not True for c in candidates.values()))
                if sid != latest_id and state['estado'] in ('concluida', 'invalidada') and updated < cutoff and not pending:
                    eligible.append(sid)
                else:
                    result['preservados'] += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                result['invalidos_preservados'] += 1
                result['preservados'] += 1
        result['elegiveis'] = len(eligible)
        if not simulate:
            db.executemany('DELETE FROM checkpoints WHERE id=?', [(sid,) for sid in eligible])
            result['removidos'] = len(eligible)
        db.commit()
        if not simulate and db.execute('PRAGMA freelist_count').fetchone()[0]:
            # Recolhe páginas livres sem apagar o arquivo do cache ou os outros bancos.
            db.execute('PRAGMA busy_timeout=1000')
            try:
                db.execute('VACUUM')
                result['compactado'] = True
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                    raise
                result['compactacao_pendente'] = True
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def auto_cleanup(root, stamp):
    if not config(root)['limpeza_automatica']:
        return {'habilitada': False}
    return cleanup(root, at=stamp)


def audit(state):
    tasks = sorted((t for t in state['tarefas'].values() if t['concluida']), key=lambda t: t['ordem'])
    done = [dict(task['plano'], concluida=True, novas=task['resultado']['novas']) for task in tasks]
    pending = sum(not item['revisada'] for item in state['candidatas'].values())
    unavailable = [dict(id=key, **task['plano'], **task['adiada'])
                   for key,task in state['tarefas'].items() if task.get('adiada')]
    def origin(q):
        return (q.get('fonte'), q.get('grupo'), q.get('janela'))
    observed = {origin(q) for q in done + unavailable}
    internal_missing = [q for q in state.get('cobertura_interna_exigida', [])
                        if origin(q) not in observed]
    required = state.get('consultas_individuais_exigidas', {})
    individual_missing = [dict(id=key, **plan) for key, plan in required.items()
                          if not (state['tarefas'].get(key, {}).get('concluida') or
                                  state['tarefas'].get(key, {}).get('adiada'))]
    individual_done = sum(state['tarefas'].get(k, {}).get('concluida') is True for k in required)
    individual_unavailable = sum(bool(state['tarefas'].get(k, {}).get('adiada')) for k in required)
    return {'consultas': done, 'fontes_indisponiveis': unavailable, 'candidatas_sem_avaliacao': pending,
            'analise_coletadas_concluida': pending == 0,
            'consultas_internas_faltantes': internal_missing,
            'consultas_individuais_faltantes': individual_missing,
            'chaves_individuais': {'total':len(required), 'concluidas':individual_done,
                'indisponiveis':individual_unavailable, 'pendentes':len(individual_missing)}}


def required_internal_sources(root):
    """Exige evidência por portal/grupo/janela, sem executar ou simular consultas."""
    from .verificacao import SEARCH_GROUPS
    path = Path(root)/'config/fontes.yaml'
    data = read(path) if path.exists() else {}
    required = []
    for source in data.get('fontes', []):
        rule = source.get('busca_interna', {})
        if rule.get('habilitada') is not True:
            continue
        label = rule.get('identificador_cache')
        groups = rule.get('grupos', SEARCH_GROUPS)
        windows = rule.get('janelas', ['24h', '7d'])
        if (not isinstance(label, str) or not label.strip() or
                not isinstance(groups, list) or not groups or
                any(g not in SEARCH_GROUPS for g in groups) or
                not isinstance(windows, list) or not windows or
                any(w not in ('24h', '7d') for w in windows)):
            raise ValueError('Configuração de cobertura interna inválida')
        required.extend(dict(fonte=label, grupo=g, janela=w) for g in groups for w in windows)
    return required


def freshness(root, state, stamp):
    if state['data'] != stamp[:10]:
        return 'dia_alterado'
    if state['criterios_sha256'] != fingerprint(root):
        return 'criterios_alterados'
    if datetime.fromisoformat(stamp) >= datetime.fromisoformat(state['criado_em']) + timedelta(hours=config(root)['validade_horas']):
        return 'cache_expirado'
    return None


def view(root, state, stamp):
    if state is None:
        return {'ok': True, 'estado': 'sem_cache', 'acao': 'iniciar_somente_na_execucao_autorizada'}
    from .curadoria import coverage_status
    stale = freshness(root, state, stamp)
    pending = [dict(id=key, **task['plano']) for key, task in state['tarefas'].items()
               if not task['concluida'] and not task.get('adiada')]
    candidates = [dict(url=url, candidata=item['original']) for url, item in state['candidatas'].items() if not item['revisada']]
    coherent = False
    if state['estado'] == 'pronta':
        try:
            coherent = (read(Path(root)/'entrada/curadoria.json') == [item['analise'] for item in state['candidatas'].values()] and
                        read(Path(root)/'entrada/cobertura.json') == audit(state))
        except (OSError, ValueError):
            pass
    return {'ok': True, 'estado': state['estado'], 'data': state['data'],
            'cache_invalido': stale, 'consultas_pendentes': pending,
            'consultas_adiadas': audit(state)['fontes_indisponiveis'],
            'exportacao_coerente': coherent,
            'candidatas_pendentes': candidates, 'cobertura': coverage_status(audit(state)),
            'proxima_tentativa_em': state.get('proxima_tentativa_em'),
            'falhas_consecutivas': state['falhas_consecutivas'],
            'motivo': state.get('motivo'), 'nova_rodada': state['nova_rodada'],
            'retomada_devida': state['estado'] == 'aguardando_retentativa' and
                bool(state.get('proxima_tentativa_em')) and stamp >= state['proxima_tentativa_em']}


def status(root, at=None):
    path = dbpath(root)
    if not path.exists():
        return view(root, None, execution_time(at))
    # A inspeção não cria DB nem altera estado, mesmo com geração bloqueada.
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        _, state = latest(db)
        return view(root, state, execution_time(at))
    finally:
        db.close()


def validate_plan(plan):
    from .verificacao import SEARCH_GROUPS
    if not isinstance(plan, list) or not plan:
        raise ValueError('Plano deve ser lista não vazia de consultas')
    tasks = {}
    for raw in plan:
        if not isinstance(raw, dict):
            raise ValueError('Consulta inválida')
        item = {key: raw.get(key) for key in ('grupo', 'consulta', 'fonte', 'tipo_fonte', 'janela')}
        item['ampliacao'] = raw.get('ampliacao') is True
        if 'chave' in raw:
            for field in ('chave','chave_tipo','localidade','modalidade','superficie'):
                if not isinstance(raw.get(field), str) or not raw[field].strip():
                    raise ValueError('Consulta individual exige chave, tipo, localidade, modalidade e superfície')
                item[field] = raw[field]
            if item['consulta'] != item['chave']:
                raise ValueError('Consulta individual deve pesquisar uma única chave literal')
        if (item['grupo'] not in SEARCH_GROUPS or item['janela'] not in ('24h', '7d') or
                item['tipo_fonte'] not in ('oficial', 'buscador') or
                not all(isinstance(item[key], str) and item[key].strip() for key in ('consulta', 'fonte'))):
            raise ValueError('Plano exige grupo, consulta, fonte, tipo_fonte e janela válidos')
        key = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        tasks[key] = {'plano': item, 'concluida': False, 'resultado': None}
    return tasks


def start(root, plan, at=None, nova_rodada=False):
    from .verificacao import verificar, exigir
    stamp = execution_time(at)
    config(root)
    exigir(verificar(root, at=stamp, nova_rodada=nova_rodada))
    planned = validate_plan(plan)
    from .busca import plano_interno
    sources_path = Path(root)/'config/fontes.yaml'
    internal = plano_interno(read(Path(root)/'config/preferencias.yaml'),
                             read(sources_path) if sources_path.exists() else {})
    mandatory = validate_plan(internal) if internal else {}
    planned.update(mandatory)
    with transaction(root) as db:
        sid, state = latest(db)
        if quota_waiting(state, stamp):
            raise ValueError('Limite da assinatura: aguardar prazo informado ou confirmação real de liberação')
        if state and state['estado'] != 'concluida' and not freshness(root, state, stamp):
            if state['nova_rodada'] != nova_rodada:
                raise ValueError('Não trocar a autorização de uma pesquisa em andamento')
            additions = [key for key in planned if key not in state['tarefas']]
            for key in additions:
                state['tarefas'][key] = planned[key]
            if additions and state['estado'] == 'pronta':
                state['estado'] = 'pesquisando'
        else:
            if state and state['estado'] != 'concluida':
                state.update(estado='invalidada', invalidada_em=stamp, atualizado_em=stamp)
                save(db, sid, state)
            sid = None
            state = {'data': stamp[:10], 'criado_em': stamp, 'atualizado_em': stamp,
                     'criterios_sha256': fingerprint(root), 'estado': 'pesquisando',
                     'tarefas': planned, 'candidatas': {}, 'falhas_consecutivas': 0,
                     'nova_rodada': nova_rodada, 'proxima_tentativa_em': None}
            state['cobertura_interna_exigida'] = required_internal_sources(root)
        state['consultas_individuais_exigidas'] = {k:v['plano'] for k,v in mandatory.items()}
        state['atualizado_em'] = stamp
        save(db, sid, state)
        result = view(root, state, stamp)
    result['limpeza'] = auto_cleanup(root, stamp)
    return result


def mutate(root, action, at=None, task_id=None, result=None, url=None, reason=None,
           retry_at=None, evidence=None):
    stamp = execution_time(at)
    with transaction(root) as db:
        sid, state = latest(db)
        if state is None:
            raise ValueError('Nenhuma pesquisa em cache')
        if freshness(root, state, stamp) and not (action == 'desbloquear' and state.get('motivo') in QUOTAS):
            raise ValueError('Cache requer novo plano e revalidação: '+freshness(root, state, stamp))
        if state['estado'] == 'concluida':
            raise ValueError('Pesquisa já concluída; não reabrir automaticamente')
        from .verificacao import verificar, exigir
        if action != 'concluir':
            exigir(verificar(root, at=stamp, nova_rodada=state['nova_rodada']))
        if action == 'isolar-fonte':
            if state['estado'] not in ('pesquisando','bloqueada'):
                raise ValueError('Retomar antes de isolar uma fonte')
            if state['estado']=='bloqueada' and state.get('motivo')!='fonte_oficial_http403':
                raise ValueError('Bloqueio global não é uma falha isolada de fonte; resolver a causa')
            task=state['tarefas'].get(task_id)
            if task is None or task['concluida']:
                raise ValueError('Isolamento exige consulta pendente do plano')
            if not isinstance(result,dict) or result.get('motivo') not in ('http403','http429','fonte_indisponivel','dependencia_bloqueada') or not isinstance(result.get('evidencia'),str) or not result['evidencia'].strip():
                raise ValueError('Informar motivo de fonte e evidência observada; não concluir com zero')
            task['adiada']={'motivo':result['motivo'],'evidencia':result['evidencia'],'registrado_em':stamp}
            if state['estado']=='bloqueada':
                state.setdefault('eventos',[]).append({'em':stamp,'acao':'bloqueio_global_convertido_em_pendencia_de_fonte','motivo_anterior':state.get('motivo')})
            state.update(estado='pesquisando',proxima_tentativa_em=None,motivo='fontes_isoladas_continuar_restantes')
        elif action == 'pausar':
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError('Informar motivo da interrupção')
            if reason in QUOTAS:
                if not isinstance(evidence, str) or not evidence.strip():
                    raise ValueError('Limite da assinatura exige evidência observada')
                deadline = None
                if retry_at:
                    parsed = datetime.fromisoformat(retry_at.replace('Z', '+00:00'))
                    if parsed.tzinfo is None:
                        raise ValueError('Prazo de recuperação exige fuso horário')
                    deadline = execution_time(retry_at)
                    if deadline <= stamp:
                        raise ValueError('Prazo de recuperação deve ser futuro')
                if quota_waiting(state, stamp):
                    previous = state.get('proxima_tentativa_em')
                    if previous is None or (deadline and previous > deadline):
                        deadline = previous
                state.update(motivo=reason, evidencia_limite=evidence,
                             estado='aguardando_retentativa' if deadline else 'bloqueada',
                             proxima_tentativa_em=deadline)
            elif quota_waiting(state, stamp):
                raise ValueError('Limite da assinatura ainda impede a retomada')
            else:
                if state['estado'] == 'aguardando_retentativa':
                    return view(root, state, stamp)
                state['motivo'] = reason
                state['estado'] = 'aguardando_retentativa' if reason in TRANSIENT else 'bloqueada'
                if reason in TRANSIENT:
                    state['falhas_consecutivas'] += 1
                    delays = config(root)['intervalos_minutos']
                    minutes = delays[min(state['falhas_consecutivas']-1, len(delays)-1)]
                    state['proxima_tentativa_em'] = (datetime.fromisoformat(stamp)+timedelta(minutes=minutes)).isoformat(timespec='seconds')
                else:
                    state['proxima_tentativa_em'] = None
        elif action == 'desbloquear':
            if quota_waiting(state, stamp) and state.get('proxima_tentativa_em'):
                raise ValueError('Aguardar o prazo do limite da assinatura')
            if state['estado'] != 'bloqueada' or not reason:
                raise ValueError('Desbloqueio exige causa resolvida e motivo explícito')
            state.update(estado='pesquisando', proxima_tentativa_em=None, motivo=reason)
        elif action == 'retomar':
            if state['estado'] == 'bloqueada':
                raise ValueError('Bloqueio não transitório: resolver a causa e iniciar plano revalidado')
            if state.get('proxima_tentativa_em') and stamp < state['proxima_tentativa_em']:
                return view(root, state, stamp)
            if state['estado'] != 'pronta':
                state.update(estado='pesquisando', proxima_tentativa_em=None)
        elif action in ('registrar', 'analisar'):
            if state['estado'] != 'pesquisando':
                raise ValueError('Retomar a pesquisa antes de registrar progresso')
            if not isinstance(result, dict):
                raise ValueError('Resultado deve ser objeto JSON')
            if action == 'registrar':
                task = state['tarefas'].get(task_id)
                if task is None:
                    raise ValueError('Consulta não pertence ao plano')
                if task.get('adiada'):
                    raise ValueError('Fonte isolada não deve ser repetida automaticamente; usar outra fonte independente')
                if task['concluida']:
                    if task['resultado'] != result:
                        raise ValueError('Consulta já registrada; não sobrescrever evidência')
                    return view(root, state, stamp)
                if (not isinstance(result.get('evidencia'), str) or not result['evidencia'].strip() or
                        type(result.get('novas')) is not int or result['novas'] < 0 or
                        not isinstance(result.get('candidatas'), list)):
                    raise ValueError('Resultado exige evidencia, novas e candidatas de consulta real')
                if task['plano'].get('chave'):
                    from urllib.parse import urlparse
                    url_info = urlparse(result.get('url_busca', ''))
                    host = (url_info.hostname or '').lower()
                    allowed = ('linkedin.com' if task['plano']['fonte'] == 'LinkedIn interno'
                               else 'gupy.io' if task['plano']['fonte'] == 'Gupy interno' else None)
                    if (result.get('termo_pesquisado') != task['plano']['chave'] or
                            url_info.scheme != 'https' or not allowed or
                            not (host == allowed or host.endswith('.'+allowed)) or
                            not isinstance(result.get('filtros_observados'), dict) or
                            not isinstance(result.get('limitacoes_filtros'), list)):
                        raise ValueError('Consulta individual exige termo exato, URL do portal, filtros observados e limitações')
                for job in result['candidatas']:
                    if not isinstance(job, dict) or not job.get('empresa') or not job.get('titulo'):
                        raise ValueError('Candidata exige empresa, titulo e URL HTTPS')
                    key = canonical(job['url'])
                    item = state['candidatas'].get(key)
                    if item is None or item['original'] != job:
                        state['candidatas'][key] = {'original': job, 'revisada': False, 'analise': None}
                task.update(concluida=True, resultado=result, concluida_em=stamp,
                            ordem=sum(t['concluida'] for t in state['tarefas'].values()))
            else:
                key = canonical(url)
                item = state['candidatas'].get(key)
                if item is None or canonical(result.get('url', '')) != key:
                    raise ValueError('Análise deve corresponder à candidata coletada')
                if not result.get('empresa') or not result.get('titulo') or not result.get('evidencia_analise'):
                    raise ValueError('Análise exige dados completos e evidencia_analise')
                item.update(revisada=True, analise=result, revisada_em=stamp)
            state['falhas_consecutivas'] = 0
        elif action == 'exportar':
            info = view(root, state, stamp)
            from .curadoria import coverage_status
            current_audit=audit(state)
            accessible_audit=dict(current_audit,fontes_indisponiveis=[])
            accessible_complete=coverage_status(accessible_audit)['status']=='cobertura_planejada_concluida'
            if info['consultas_pendentes'] or info['candidatas_pendentes'] or not accessible_complete:
                raise ValueError('Pesquisa incompleta: concluir consultas, análises e ampliações antes de exportar')
            expansions = [q for q in audit(state)['consultas'] if q.get('ampliacao')][-2:]
            if len({(q['consulta'].strip().casefold(), q['fonte'].strip().casefold()) for q in expansions}) != 2:
                raise ValueError('Ampliações finais precisam de fontes/termos distintos')
            # Snapshot único autoritativo; arquivos de entrada podem ser reexportados após falha.
            state['estado'] = 'pronta'
        elif action == 'concluir':
            delivery = read(Path(root)/f'data/entregas/{stamp[:10]}.json')
            if state['estado'] != 'pronta' or not (delivery.get('planilha_publicada') is True and delivery.get('email_enviado') is True):
                raise ValueError('Concluir exige pesquisa pronta e entrega confirmada')
            state['estado'] = 'concluida'
        else:
            raise ValueError('Ação de cache desconhecida')
        state['atualizado_em'] = stamp
        save(db, sid, state)
    if action == 'exportar':
        write(Path(root)/'entrada/curadoria.json', [item['analise'] for item in state['candidatas'].values()])
        write(Path(root)/'entrada/cobertura.json', audit(state))
    result = view(root, state, stamp)
    if action in ('isolar-fonte','pausar'):
        from .alertas import registrar_sem_interromper
        origin = state['tarefas'][task_id]['plano']['fonte'] if action=='isolar-fonte' else 'execução da busca'
        result['alerta_impedimento'] = registrar_sem_interromper(root,
            codigo='fonte_indisponivel' if action=='isolar-fonte' else 'busca_'+reason,
            origem=origin,detalhe='Uma fonte foi isolada; as demais continuam.' if action=='isolar-fonte' else 'A busca foi interrompida: '+reason,
            acao='Continuar fontes independentes; verificar acesso à fonte.' if action=='isolar-fonte' else 'Respeitar o checkpoint e o prazo de retomada; resolver a causa quando não transitória.',
            retomada=state.get('proxima_tentativa_em'),at=stamp)
    if action == 'concluir':
        result['limpeza'] = auto_cleanup(root, stamp)
    return result
