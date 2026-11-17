"""Relatório diário de vagas para candidatura manual, sem ações de envio."""
import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from .core import ROOT, BR, Store, canonical, now, read, write, norm
from . import controle_vagas as control
from .busca import nivel_titulo
from .verificacao import SEARCH_GROUPS, execution_time, verificar, exigir

HEADERS = ['Publicação','Empresa','Vaga','Modalidade','Localidade','Contrato','Jornada','Salário','Situação','Pendências / observações','Link da vaga','Currículo recomendado','Fonte da data','Verificado em']

def coverage_status(audit):
    queries = audit.get('consultas', [])
    done = [q for q in queries if q.get('concluida') is True]
    missing = [g for g in SEARCH_GROUPS if g not in {q.get('grupo') for q in done}]
    windows = {q.get('janela') for q in done}
    sources = {q.get('tipo_fonte') for q in done}
    expansions = [q for q in done if q.get('ampliacao')]
    saturated = len(expansions)>=2 and all(q.get('novas')==0 for q in expansions[-2:])
    unavailable=audit.get('fontes_indisponiveis',[])
    internal_missing = audit.get('consultas_internas_faltantes', [])
    individual_missing = audit.get('consultas_individuais_faltantes', [])
    evaluated = audit.get('candidatas_sem_avaliacao') == 0
    covered = not missing and not internal_missing and not individual_missing and {'24h','7d'} <= windows and {'oficial','buscador'} <= sources and saturated and evaluated and not unavailable
    review_complete = evaluated and audit.get('analise_coletadas_concluida') is True
    status = 'cobertura_planejada_concluida' if covered else ('analise_das_encontradas_concluida' if review_complete else 'parcial')
    reason = 'fontes_indisponiveis_fila_acessivel_concluida' if unavailable and review_complete else ('cobertura_e_ampliacoes_sem_novidades' if covered else ('fila_coletada_analisada' if review_complete else 'cobertura_incompleta'))
    return {'status':status,'motivo_encerramento':reason,'grupos_faltantes':missing,'consultas_internas_faltantes':internal_missing,'consultas_individuais_faltantes':individual_missing,'chaves_individuais':audit.get('chaves_individuais',{}),'janelas_pesquisadas':sorted(w for w in windows if w),'consultas_registradas':len(queries),'ampliacoes_finais_sem_novidades':saturated,'candidatas_avaliadas':evaluated,'fontes_indisponiveis':unavailable,'cobertura_integral':covered,'nao_garante_exaustividade':True}

def degree_only(reason):
    text=norm(reason)
    return text in ('ensino superior completo','graduacao completa','graduacao concluida','formacao superior completa','formacao completa')

def english_only(reason):
    # Só libera a incompatibilidade de idioma explicitamente categorizada.
    return norm(reason) in ('ingles acima do perfil','ingles intermediario obrigatorio','ingles avancado obrigatorio','ingles fluente obrigatorio','ingles intermediario/avancado obrigatorio')

def partition_jobs(jobs):
    # Idioma tem precedência se ambos os requisitos forem exigidos, sem duplicar.
    english = [j for j in jobs if j.get('exige_ingles_acima_perfil')]
    remaining = [j for j in jobs if not j.get('exige_ingles_acima_perfil')]
    return ([j for j in remaining if not j.get('exige_graduacao_completa')], [j for j in remaining if j.get('exige_graduacao_completa')], english)

def publication(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z','+00:00')).date()
    except (ValueError, AttributeError):
        return None

PUBLICATION_SOURCES = {
    'oficial', 'indice_oficial', 'original', 'original_indexada',
    'original_confirmada', 'publicacao_original', 'publicacao_oficial',
    'original_relativa_confirmada',
}


def publication_time(value):
    """Datas sem hora usam meia-noite de Brasilia, de forma conservadora."""
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (moment.replace(tzinfo=BR) if moment.tzinfo is None else moment.astimezone(BR))
    except (ValueError, AttributeError, TypeError):
        return None


def recent_publications(jobs, at, days=7):
    """Filtra apenas novidades; nao altera o ledger nem o historico."""
    reference = publication_time(at)
    if reference is None:
        raise ValueError('Data da execucao invalida para filtrar publicacoes')
    recent, rejected = [], []
    for job in jobs:
        moment = publication_time(job.get('publicada_em'))
        kind = job.get('tipo_data')
        reason = None
        if moment is None:
            reason = 'Data de publicacao original ausente ou invalida'
        elif kind not in PUBLICATION_SOURCES or not job.get('fonte_data'):
            reason = 'Data original sem evidencia; descoberta/agregador/republicacao nao comprovam recencia'
        elif moment > reference:
            reason = 'Data de publicacao futura'
        elif moment < reference - timedelta(days=days):
            reason = 'Publicacao anterior aos ultimos sete dias'
        if reason:
            rejected.append({'empresa': job.get('empresa'), 'titulo': job.get('titulo'),
                             'url': job.get('url'), 'publicada_em': job.get('publicada_em'),
                             'tipo_data': kind, 'motivo': reason})
        else:
            recent.append(job)
    recent.sort(key=lambda job: publication_time(job['publicada_em']), reverse=True)
    return recent, rejected


def job_identity(job):
    """Identidade conservadora para cópias do mesmo anúncio em outro portal."""
    return tuple(' '.join(norm(str(job.get(k) or '')).split()) for k in ('empresa', 'titulo'))


def select_jobs(jobs, sent_urls=(), sent_jobs=(), nivel_ingles_perfil=None):
    """Mantém potenciais com pendências explícitas; nunca mascara incompatibilidade."""
    sent = {canonical(u) for u in sent_urls}
    applied_identities = {job_identity(j) for j in sent_jobs if j.get('empresa') and j.get('titulo')}
    selected, seen = [], set()
    for j in jobs:
        url = canonical(j['url'])
        nivel = nivel_titulo(j['titulo'])
        blockers = [b for b in j.get('incompatibilidades',[]) if not ((j.get('exige_graduacao_completa') and degree_only(b)) or (j.get('exige_ingles_acima_perfil') and english_only(b)))]
        if nivel in ('estagio', 'fora_escopo') or (j.get('anos_profissionais_obrigatorios') or 0) > 2:
            continue
        if url in seen or url in sent or job_identity(j) in applied_identities or j.get('ativa') is False or blockers:
            continue
        seen.add(url)
        pending = list(j.get('pendencias', []))
        if nivel in ('equivalente', 'nao_informado'):
            pending.append('Validar nível e experiência exigida pelo trabalho real; título não comprova nível júnior')
        if j.get('exige_ingles_acima_perfil'):
            pending.insert(0,f"Exige inglês {j.get('nivel_ingles_exigido') or 'acima do perfil'}; nível do candidato: {nivel_ingles_perfil or 'consultar perfil confirmado'}. Requisito ainda não atendido; não declarar proficiência maior.")
        if j.get('exige_graduacao_completa'):
            pending.insert(0,'Exige graduação completa; formação ainda não confirmada como concluída no perfil. Avaliação manual, sem declarar curso concluído.')
        if not j.get('criterios_confirmados') and not pending:
            pending.append('Critérios completos ainda não confirmados')
        item = dict(j, url=url, pendencias=pending)
        item['situacao'] = 'Inglês acima do nível atual' if j.get('exige_ingles_acima_perfil') else ('Graduação completa exigida' if j.get('exige_graduacao_completa') else ('Conferir condições' if pending else 'Compatível'))
        selected.append(item)
    selected.sort(key=lambda j: (publication(j.get('publicada_em')) is not None, publication(j.get('publicada_em')) or datetime.min.date()), reverse=True)
    return selected

def build_daily(inbox, coverage, settings=None, sent_urls=None, at=None, rebuild=False):
    settings = settings or read(ROOT/'config/entrega_diaria.json')
    stamp = execution_time(at)
    delivery = ROOT/'data/entregas'/f'{stamp[:10]}.json'
    if delivery.exists():
        previous = read(delivery)
        if not rebuild and previous.get('planilha_publicada') and previous.get('email_enviado'):
            return {'duplicado':True,'data':stamp[:10],'total':previous.get('total'),'motivo':'Entrega diária já confirmada; não sobrescrever nem reenviar'}
    exigir(verificar(ROOT, at=stamp, settings=settings,
                     exigir_sincronizacao=True, nova_rodada=rebuild))
    if (ROOT/'data/cache_busca.sqlite').exists():
        from .cache_busca import status as cache_status
        if cache_status(ROOT, at=stamp)['estado'] == 'pronta' and read(inbox) != read(ROOT/'entrada/curadoria.json'):
            raise ValueError('Entrada difere da exportação validada do cache')
    applied_jobs = []
    tracking = bool(settings.get('controle_candidaturas'))
    ledger = control.load(ROOT) if tracking else None
    if tracking and ledger.get('synced_date') != stamp[:10]:
        raise ValueError('Ler e sincronizar as marcações atuais da planilha antes de gerar a lista diária')
    if sent_urls is None:
        store = Store(ROOT/'data/candidaturas.sqlite')
        sent_urls = [r['url'] for r in store.db.execute("SELECT url FROM jobs WHERE state='enviada'")]
        history = [dict(r) for r in store.db.execute('SELECT url, company AS empresa, title AS titulo FROM history')]
        if tracking:
            # O checkbox atual substitui a declaração antiga na curadoria;
            # registros/evidências originais de envio permanecem intocados.
            history = [r for r in history if control.resolve(ledger,r) not in ledger['items'] or control.applied(ledger,r)]
        sent_urls += [r['url'] for r in history]
        applied_jobs = history
    if tracking:
        checked=[i['job'] for i in ledger['items'].values() if i['applied']]
        sent_urls=list(sent_urls)+[j['url'] for j in checked]
        applied_jobs+=checked
    recent, rejected_dates = recent_publications(read(inbox), stamp, settings.get('publicacao_max_dias', 7))
    facts_path=ROOT/'perfil/fatos_confirmados.json'
    language=read(facts_path).get('afirmacoes',{}).get('ingles',{}).get('texto') if facts_path.exists() else None
    jobs = select_jobs(recent, sent_urls, applied_jobs,nivel_ingles_perfil=language)
    if tracking:
        jobs=[j for j in jobs if not control.applied(ledger,j) and not control.dismissed(ledger,j) and control.novel(ledger,j,stamp[:10])]
    main_jobs, degree_jobs, english_jobs = partition_jobs(jobs)
    daily = ROOT/'relatorios'/f'{stamp[:10]}-lista'
    daily.mkdir(parents=True, exist_ok=True)
    rows, main_rows, degree_rows, english_rows = [], [], [], []
    for j in jobs:
        row=[j.get('publicada_em') or 'Data não informada', j['empresa'], j['titulo'], j.get('modalidade') or 'Confirmar', j.get('localidade') or 'Confirmar', j.get('contrato') or 'Não informado', j.get('jornada') or 'Não divulgada', j.get('salario') or 'Não divulgado', j['situacao'], '; '.join(j['pendencias']), j['url'], j.get('curriculo_url') or settings['curriculo_url'], j.get('fonte_data') or 'Data original desconhecida', j.get('consultado_em') or stamp]
        rows.append(row)
        (english_rows if j.get('exige_ingles_acima_perfil') else (degree_rows if j.get('exige_graduacao_completa') else main_rows)).append(row)
    unknown = sum(publication(j.get('publicada_em')) is None or j.get('tipo_data') == 'agregador' for j in jobs)
    audit_path=ROOT/'entrada/cobertura.json'
    audit=coverage_status(read(audit_path) if audit_path.exists() else {})
    summary = {'data':stamp[:10], 'gerado_em':stamp,'total':len(jobs),'total_principal':len(main_jobs),'total_graduacao_completa':len(degree_jobs),'total_ingles_acima_perfil':len(english_jobs),'com_pendencias':sum(bool(j['pendencias']) for j in jobs),'sem_data_original':unknown,'cobertura':coverage,'auditoria_busca':audit,'planilha':settings['planilha_url'],'envios_de_candidaturas':0,'email_enviado':False,'planilha_publicada':False}
    headers=HEADERS+[control.CHECKBOX,control.DECISION] if tracking else HEADERS
    if tracking:
        for collection in (rows,):
            for row in collection:row.extend([False,''])
        summary.update(somente_ineditas=True,historico_preservado=True)
    values = [['Vagas para candidatura manual', f'{len(main_jobs)} nesta aba; {len(degree_jobs)} em Graduação completa; {len(english_jobs)} em Inglês acima do nível atual'], ['Atualizado em',stamp], ['Cobertura',coverage], ['Critérios','Pendências sinalizadas. Vagas anteriores ficam no Histórico de vagas; marque Já me candidatei para excluir da fila.'], headers] + main_rows
    degree_values = [['Vagas que exigem graduação completa',f'{len(degree_jobs)} oportunidades; requisito ainda não atendido'],['Atualizado em',stamp],['Cobertura',coverage],['Atenção','Formação ainda não confirmada como concluída no perfil. Outros critérios mantidos; não declarar formação concluída.'],headers] + degree_rows
    english_values = [['Inglês acima do nível atual',f'{len(english_jobs)} oportunidades; requisito de idioma ainda não atendido'],['Atualizado em',stamp],['Cobertura',coverage],['Atenção','Nível do candidato conforme perfil confirmado. Exigência maior indicada nas observações. Se também exigir graduação completa, fica somente aqui, com ambos os alertas.'],headers] + english_rows
    summary.update(publicacao_max_dias=settings.get('publicacao_max_dias', 7),
                   excluidas_por_recencia=len(rejected_dates), publicacao_original_obrigatoria=True)
    write(daily/'exclusoes-recencia.json',rejected_dates)
    write(daily/'vagas.json',jobs)
    write(daily/'resumo.json',summary)
    write(daily/'valores-planilha.json',values)
    write(daily/'valores-graduacao.json',degree_values)
    write(daily/'valores-ingles.json',english_values)
    write(daily/'auditoria-busca.json',audit)
    with (daily/'vagas.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f); writer.writerow(headers)
        # CSV aberto em Excel não deve executar fórmulas provenientes de anúncios.
        writer.writerows([["'"+str(v) if str(v).startswith(('=','+','-','@')) else v for v in row] for row in rows])
    text = f"# Vagas para candidatura manual - {stamp[:10]}\n\n{len(jobs)} oportunidades encontradas; {summary['com_pendencias']} com condições a conferir.\n\nCobertura: {coverage}\n\n"
    for j in jobs:
        text += f"- [{j['empresa']} - {j['titulo']}]({j['url']}) | {j.get('publicada_em') or 'data não informada'} | {j['situacao']}\n"
        if j['pendencias']: text += '  Pendências: '+'; '.join(j['pendencias'])+'\n'
    (daily/'lista.md').write_text(text,encoding='utf-8')
    digest=hashlib.sha256((daily/'vagas.json').read_bytes()).hexdigest()
    write(daily/'manifesto.json',{'sha256_lista':digest,'gerado_em':stamp,'modo':'curadoria_manual','publicacao_exige_verificacao':True,'email_exige_confirmacao_do_conector':True})
    return {'pasta':str(daily),**summary}
