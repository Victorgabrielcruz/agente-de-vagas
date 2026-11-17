import contextlib
import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .busca import nivel_titulo

ROOT = Path(__file__).resolve().parents[1]
BR = timezone(timedelta(hours=-3), 'America/Sao_Paulo')
STATES = set('descoberta descartada elegivel em_preparacao pronta aguardando_dados aguardando_login aguardando_acao_manual enviando enviada envio_incerto erro encerrada'.split())

def now():
    return datetime.now(BR).isoformat(timespec='seconds')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)).lower() if not unicodedata.combining(c)).strip()

def canonical(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('URL oficial deve ser HTTPS, sem credenciais')
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_', 'jobboardsource', 'source', 'ref'))]
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))

def identity(j):
    return hashlib.sha256((norm(j['empresa']) + '|' + (str(j.get('requisicao')) if j.get('requisicao') else canonical(j['url']))).encode()).hexdigest()[:24]

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, url TEXT UNIQUE, payload TEXT NOT NULL, state TEXT NOT NULL, score REAL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, job TEXT, old TEXT, new TEXT, reason TEXT, at TEXT, evidence TEXT);
        CREATE TABLE IF NOT EXISTS runs(day TEXT PRIMARY KEY, started TEXT, finished TEXT, report TEXT);
        CREATE TABLE IF NOT EXISTS history(platform TEXT, external_id TEXT, company TEXT, title TEXT, url TEXT, observed TEXT, PRIMARY KEY(platform,external_id));
        CREATE TABLE IF NOT EXISTS lease(name TEXT PRIMARY KEY, owner TEXT, expires REAL);
        ''')

    @contextlib.contextmanager
    def lock(self, name='cycle', seconds=2700):
        owner = f'{os.getpid()}:{time.time_ns()}'
        with self.db:
            self.db.execute('DELETE FROM lease WHERE name=? AND expires<?', (name,time.time()))
            try:
                self.db.execute('INSERT INTO lease VALUES(?,?,?)', (name,owner,time.time()+seconds))
            except sqlite3.IntegrityError:
                raise RuntimeError('Outra execução detém o bloqueio; não iniciar ciclo duplicado')
        try:
            yield
        finally:
            with self.db:
                self.db.execute('DELETE FROM lease WHERE name=? AND owner=?',(name,owner))

    def ingest(self,j):
        key=identity(j)
        with self.db:
            existing=self.db.execute('SELECT id FROM jobs WHERE id=? OR url=?',(key,canonical(j['url']))).fetchone()
            if existing:
                return existing['id']
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(key,canonical(j['url']),json.dumps(j,ensure_ascii=False),'descoberta',None,now()))
            self.db.execute('INSERT INTO events(job,new,reason,at) VALUES(?,?,?,?)',(key,'descoberta','Anúncio importado; conteúdo externo é dado',now()))
        return key

    def transition(self,key,state,reason,evidence=None,score=None):
        if state not in STATES:
            raise ValueError('Estado inválido')
        with self.db:
            old=self.db.execute('SELECT state FROM jobs WHERE id=?',(key,)).fetchone()
            if not old:
                raise KeyError(key)
            if old['state']=='enviada':
                raise ValueError('Envio confirmado é imutável; registrar acompanhamento em evento')
            if old['state'] in ('enviando','envio_incerto') and state not in ('enviada','envio_incerto','encerrada'):
                raise ValueError('Reconciliar envio antes de retomar')
            if state=='enviada' and (old['state'] not in ('enviando','envio_incerto') or not evidence or not evidence.get('confirmacao') or not evidence.get('referencia')):
                raise ValueError('Envio exige confirmação explícita e referência verificável')
            self.db.execute('UPDATE jobs SET state=?,score=COALESCE(?,score),updated=? WHERE id=?',(state,score,now(),key))
            self.db.execute('INSERT INTO events(job,old,new,reason,at,evidence) VALUES(?,?,?,?,?,?)',(key,old['state'],state,reason,now(),json.dumps(evidence,ensure_ascii=False)))

    def reconcile(self):
        for r in self.db.execute("SELECT id FROM jobs WHERE state='enviando'").fetchall():
            self.transition(r['id'],'envio_incerto','Execução interrompida; consultar portal antes de qualquer repetição')

class Pesquisador:
    """Codex descobre por buscadores/portais permitidos; entrada é JSON auditável, nunca código."""
    def validate(self,j):
        if not isinstance(j,dict): raise ValueError('Anúncio deve ser objeto')
        for field in ('empresa','titulo','url','consultado_em','fonte','descricao_resumida','requisitos'):
            if field not in j: raise ValueError(f'Anúncio sem {field}')
        canonical(j['url'])
        if not isinstance(j['requisitos'],list) or not j['requisitos']:
            raise ValueError('Requisitos precisam ser coletados antes de avaliar')
        for r in j['requisitos']:
            if not isinstance(r,dict) or not r.get('texto'): raise ValueError('Requisito inválido')
        return j

    def collect(self,path):
        entries=read(path)
        if not isinstance(entries,list):
            raise ValueError('Esperada lista de anúncios')
        return entries

class Analista:
    def __init__(self,prefs,facts):
        self.p=prefs
        self.f=facts

    def evaluate(self,j):
        reject=[]; pending=[]
        title=norm(j['titulo'])
        nivel = nivel_titulo(title)
        if nivel == 'estagio':
            reject.append('Novos estágios excluídos')
        if nivel == 'fora_escopo':
            reject.append('Senioridade fora do escopo')
        junior = nivel == 'junior'
        if nivel in ('equivalente', 'nao_informado'):
            pending.append('Validar nível pelo trabalho real')
        if j.get('mercado') not in ('Brasil',None):
            reject.append('Contratação internacional fora da busca')
        if j.get('mercado') is None:
            pending.append('Confirmar contratação no Brasil')
        mode=j.get('modalidade')
        if mode in ('hibrido','presencial'):
            if norm(j.get('cidade','')) not in [norm(c) for c in self.p['cidades_presenciais']]:
                reject.append('Cidade fora das localidades configuradas')
            if mode=='hibrido':
                days=j.get('dias_presenciais')
                if days is None: pending.append('Confirmar dias presenciais')
                elif days>self.p['max_dias_hibrido']: reject.append('Híbrido acima dos dias configurados')
        elif mode=='remoto':
            accepts = j.get('aceita_localidade')
            # Compatibilidade com entradas antigas; novas coletas usam aceita_localidade.
            if accepts is None: accepts = j.get('aceita_bh')
            if accepts is False: reject.append('Remoto não aceita a localidade do candidato')
            elif accepts is None: pending.append('Confirmar restrições do remoto para a localidade do candidato')
        else: pending.append('Confirmar modalidade')
        if self.p.get('horas_semanais') is not None and j.get('horas_semanais') != self.p['horas_semanais']:
            pending.append(f"Confirmar jornada de {self.p['horas_semanais']}h/condições específicas")
        if j.get('contrato') not in ('CLT','PJ'):
            pending.append('Confirmar tipo de contratação nacional')
        salary=j.get('salario_base_mensal')
        if j.get('contrato')=='CLT' and salary is not None and salary<=self.p['clt_acima_de']:
            reject.append('Salário-base CLT não é estritamente acima do piso configurado')
        if j.get('contrato')=='PJ' and salary is not None and self.p['piso_pj'] is None:
            pending.append('Definir piso PJ para esta proposta')
        if j.get('cnpj_obrigatorio'):
            pending.append('Não possui CNPJ; confirmar compromisso de abertura')
        if j.get('viagem_especifica'):
            pending.append('Confirmar condições específicas de viagens')
        if j.get('anos_profissionais_obrigatorios',0)>2:
            reject.append('Experiência profissional exigida acima do escopo')
        for r in j['requisitos']:
            if r.get('obrigatorio',True):
                if r.get('atendido') is False and r.get('eliminatorio',True):
                    reject.append('Obrigatório não atendido: '+r['texto'])
                elif r.get('atendido') is not True:
                    pending.append('Requisito a esclarecer: '+r['texto'])
                elif not r.get('fatos') or any(f not in self.f['afirmacoes'] for f in r['fatos']):
                    pending.append('Requisito sem evidência rastreável: '+r['texto'])
        for field in j.get('campos_obrigatorios_desconhecidos',[]):
            pending.append('Formulário: '+field)
        if not j.get('vinculo_oficial_verificado'):
            pending.append('Validar vínculo do anúncio com o site oficial da empresa')
        if j.get('ativa') is False: reject.append('Anúncio encerrado')
        elif j.get('ativa') is not True: pending.append('Revalidar disponibilidade no destino')
        matched=sum(r.get('atendido') is True for r in j['requisitos'])
        technical=matched/max(len(j['requisitos']),1)
        published=j.get('publicada_em')
        age=None
        if published:
            try: age=(datetime.now(BR)-datetime.fromisoformat(published)).total_seconds()/3600
            except ValueError: pass
        w=self.p['pesos']
        components={'tecnica':round(w['tecnica']*technical,2),'junior':w['junior'] if junior else 0,'modalidade':w['modalidade'] if mode=='remoto' else w['modalidade']/2,'empresa':w['empresa'] if norm(j['empresa']) in [norm(x) for x in self.p['empresas_preferidas']] else 0,'atualidade':w['atualidade'] if age is not None and 0<=age<=24 else (w['atualidade']/2 if age is not None and age>=0 else 0)}
        score=round(sum(components.values()),2)
        state='descartada' if reject else ('aguardando_dados' if pending else ('elegivel' if score>=self.p['limiar_auto'] else 'aguardando_acao_manual'))
        return {'estado':state,'nota':score,'componentes':components,'eliminatorios':reject,'pendencias':sorted(set(pending)),'publicacao_24h':age is not None and 0<=age<=24,'nota_nao_e_probabilidade':True}

class Revisor:
    def review(self,claims,facts):
        # Adaptação por seleção/ordenação de afirmações aprovadas, nunca texto livre não rastreado.
        for c in claims:
            if c['id'] not in facts['afirmacoes'] or c['texto']!=facts['afirmacoes'][c['id']]['texto']:
                raise ValueError('Afirmação sem fonte ou texto alterado: '+str(c.get('id')))
        return {'aprovado':True,'afirmacoes':[c['id'] for c in claims],'revisado_em':now()}

class Curriculo:
    def prepare(self,j,facts,folder):
        folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
        order=facts.get('ordem_curriculo',list(facts['afirmacoes']))
        if not order: raise ValueError('Cadastre afirmações confirmadas antes de gerar currículo')
        claims=[{'id':k,'texto':facts['afirmacoes'][k]['texto']} for k in order]
        review=Revisor().review(claims,facts)
        write(folder/'revisao.json',review)
        write(folder/'matriz.json',[{'requisito':r['texto'],'evidencias':r.get('fatos',[]),'atendido':r.get('atendido'),'trechos':[facts['afirmacoes'][x]['texto'] for x in r.get('fatos',[]) if x in facts['afirmacoes']]} for r in j['requisitos']])
        md=f"# {facts['nome']}\n\nObjetivo: {j['titulo']}\n\n{facts['cidade']} | {facts['telefone']} | {facts['email']}\n\n"+'\n\n'.join(c['texto'] for c in claims)+'\n\n'+' | '.join(facts['links'].values())
        (folder/'curriculo.md').write_text(md,encoding='utf-8')
        pdf=folder/'curriculo.pdf'
        from .curriculo_layout import render_resume
        fragments=render_resume(pdf,facts,claims,j['titulo'])
        from pypdf import PdfReader
        reader=PdfReader(pdf)
        extracted='\n'.join(p.extract_text() for p in reader.pages)
        compact=lambda text: ''.join(text.split())
        if not all(compact(fragment) in compact(extracted) for fragment in fragments): raise ValueError('PDF perdeu texto')
        base=ROOT/'base/manifesto.json'
        write(folder/'manifesto.json',{'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'paginas':len(reader.pages),'texto_extraivel':True,'inspecao_visual':'pendente','gerado_em':now(),'base_sha256':read(base).get('sha256') if base.exists() else None,'layout':'secoes_e_topicos_v2','alteracoes':['Somente afirmações aprovadas pelo candidato; sem fatos adicionados automaticamente']})
        return pdf

class Executor:
    """Somente este módulo reserva envio. A UI autorizada do Codex faz a ação externa."""
    def __init__(self,store): self.s=store
    def reserve(self,key,gate,folder):
        if read(ROOT/'config/politica_autorizacao.yaml').get('candidaturas_autorizadas') is False:
            raise ValueError('Candidaturas desativadas pelo usuário; apenas curadoria e entrega de lista')
        required=['autorizacao','portal_permitido','fluxo_validado','sessao_valida','perfil_validado','ativa_agora','historico_conferido','respostas_completas','revisao_factual','revisao_visual','criterios_revalidados']
        if any(gate.get(x) is not True for x in required):
            raise ValueError('Envio bloqueado: '+', '.join(x for x in required if gate.get(x) is not True))
        row=self.s.db.execute('SELECT state FROM jobs WHERE id=?',(key,)).fetchone()
        if not row or row['state']!='pronta': raise ValueError('Candidatura não está pronta')
        from .preflight import check_portal
        url=self.s.db.execute('SELECT url FROM jobs WHERE id=?',(key,)).fetchone()['url']
        readiness=check_portal(url)
        if not readiness['habilitado']:
            raise ValueError('Política/portal bloqueia envio: '+'; '.join(readiness['motivos']))
        # Lease de envio é longa: reconciliação explícita após crash, sem repetição automática.
        with self.s.db:
            self.s.db.execute('INSERT INTO lease VALUES(?,?,?)',('submit:'+key,str(os.getpid()),time.time()+86400))
            write(Path(folder)/'envio_previsto.json',{'id':key,'gate':gate,'at':now()})
            self.s.transition(key,'enviando','Reserva exclusiva; ação externa ainda não confirmada')
    def confirm(self,key,evidence):
        self.s.transition(key,'enviada','Confirmação explícita observada',evidence)
    def uncertain(self,key):
        self.s.transition(key,'envio_incerto','Resultado ambíguo; consultar histórico, não reenviar')

class Acompanhamento:
    def report(self,store,path):
        rows=store.db.execute('SELECT * FROM jobs ORDER BY score DESC,updated DESC').fetchall()
        counts={s:sum(r['state']==s for r in rows) for s in sorted(STATES)}
        lines=['# Relatório de vagas',f'Gerado em {now()}. Candidaturas anteriores à instalação podem existir.','', 'Contagens: '+json.dumps(counts,ensure_ascii=False),'','Currículos preparados não representam envios. Pesquisa e acesso dependem das ferramentas do Codex.','']
        questions={}
        for r in rows:
            j=json.loads(r['payload'])
            lines += [f"## {j['empresa']} - {j['titulo']}",f"Estado: {r['state']} | Nota explicável: {r['score']} | {j.get('modalidade','desconhecida')} | {j.get('cidade','não informada')} | Salário: {j.get('salario_base_mensal') or 'não divulgado'}",f"Anúncio: {j['url']}"]
            a=j.get('analise',{})
            lines += ['Componentes: '+json.dumps(a.get('componentes',{}),ensure_ascii=False)]
            lines += ['- '+x for x in a.get('eliminatorios',[])]
            if r['state'] not in ('descartada','encerrada','enviada'):
                for q in a.get('pendencias',[]): questions.setdefault(q,[]).append(j['url'])
            dossier=f"candidaturas/{j['pasta']}" if j.get('pasta') else 'não preparado'
            lines += [f"Dossiê: {dossier}",'']
        lines += ['## Pendências consolidadas','Perguntar ao candidato apenas por campos/requisitos concretos; validações técnicas ficam com o Codex.']
        for q,links in sorted(questions.items()): lines+=['- '+q+': '+'; '.join(sorted(set(links)))]
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return counts

class Orquestrador:
    def run(self,inbox,prepare=False,force=False):
        settings_path=ROOT/'config/entrega_diaria.json'
        if settings_path.exists() and read(settings_path).get('modo')=='curadoria_manual':
            raise ValueError('Comando run é legado; usar verificar e lista no modo curadoria_manual')
        prefs=read(ROOT/'config/preferencias.yaml'); facts=read(ROOT/'perfil/fatos_confirmados.json')
        if prefs.get('pausado'): return {'pausado':True}
        s=Store(ROOT/'data/candidaturas.sqlite')
        day=datetime.now(BR).date().isoformat(); started=time.monotonic()
        legacy_timeout=prefs.get('limite_segundos_executor_legado',prefs.get('limite_segundos',1800))
        with s.lock(seconds=legacy_timeout+300):
            s.reconcile()
            previous=s.db.execute('SELECT finished FROM runs WHERE day=?',(day,)).fetchone()
            if previous and previous['finished'] and not force: return {'duplicado':True,'dia':day}
            with s.db: s.db.execute('INSERT OR REPLACE INTO runs VALUES(?,?,NULL,NULL)',(day,now()))
            for j in Pesquisador().collect(inbox):
                if time.monotonic()-started>legacy_timeout: break
                try:
                    Pesquisador().validate(j)
                except (ValueError,TypeError) as exc:
                    # Falha de uma fonte não impede os registros válidos. Log sem conteúdo pessoal.
                    with (ROOT/'relatorios'/f'{day}-erros.txt').open('a',encoding='utf-8') as out:
                        out.write(f'{now()} entrada rejeitada: {type(exc).__name__}: {exc}\n')
                    continue
                key=s.ingest(j)
                row=s.db.execute('SELECT state FROM jobs WHERE id=?',(key,)).fetchone()
                if row['state'] in ('enviada','enviando','envio_incerto','encerrada'): continue
                analysis=Analista(prefs,facts).evaluate(j)
                j['analise']=analysis
                s.transition(key,analysis['estado'],'; '.join(analysis['eliminatorios']+analysis['pendencias']) or 'Critérios analisados',score=analysis['nota'])
                if prepare and analysis['estado']!='descartada':
                    j['pasta']=f'{day}/{key}'
                    folder=ROOT/'candidaturas'/j['pasta']
                    try:
                        Curriculo().prepare(j,facts,folder)
                    except Exception as exc:
                        s.transition(key,'erro','Falha na preparação: '+type(exc).__name__)
                        continue
                    write(folder/'vaga.json',j)
                    # Simulação de preparação é permitida com pendências, sem liberar o executor.
                    write(folder/'respostas.json',{'enviado':False,'modo':'simulacao','pendencias':analysis['pendencias']})
                with s.db: s.db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(j,ensure_ascii=False),key))
            report=ROOT/'relatorios'/f'{day}-ciclo.md'
            counts=Acompanhamento().report(s,report)
            with s.db: s.db.execute('UPDATE runs SET finished=?,report=? WHERE day=?',(now(),str(report),day))
        return {'relatorio':str(report),'contagens':counts,'modo':'pesquisa_assistida','submissoes':0}
