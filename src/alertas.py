"""Fila local de impedimentos; o envio real é feito pelo conector Gmail do agente."""
import contextlib
import hashlib
import html
import json
import sqlite3
from pathlib import Path

from .core import read
from .verificacao import execution_time


def configuration(root):
    settings = read(Path(root)/'config/entrega_diaria.json')
    rule = settings.get('alertas_impedimentos', {})
    if rule.get('habilitado') is not True:
        return None
    authorization = read(Path(root)/'config/politica_autorizacao.yaml').get('alertas_impedimentos', {})
    if (authorization.get('autorizado') is not True or
            not authorization.get('texto_usuario') or not authorization.get('autorizado_em') or
            not rule.get('destinatario') or not rule.get('gmail_link_id') or
            rule.get('destinatario') != settings.get('email') or
            rule.get('gmail_link_id') != settings.get('gmail_link_id') or
            any(authorization.get(k) != rule.get(k) for k in ('destinatario','gmail_link_id'))):
        raise ValueError('Alertas exigem autorização própria para destinatário e conexão atuais')
    return rule


@contextlib.contextmanager
def transaction(root):
    path = Path(root)/'data/alertas_impedimentos.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS incidentes(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def save(db, item):
    db.execute('INSERT OR REPLACE INTO incidentes VALUES(?,?)',
               (item['id'], json.dumps(item, ensure_ascii=False)))


def registrar(root, codigo, origem, detalhe, acao, at=None, retomada=None):
    if configuration(root) is None:
        return {'habilitado':False}
    if not all(isinstance(v,str) and v.strip() for v in (codigo,origem,detalhe,acao)):
        raise ValueError('Impedimento exige código, origem, descrição e ação')
    stamp = execution_time(at)
    key = hashlib.sha256(json.dumps([stamp[:10],codigo.strip(),origem.strip().casefold()]).encode()).hexdigest()[:20]
    with transaction(root) as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM incidentes')]
        matches = [i for i in rows if i['chave']==key and i['estado']!='resolvido']
        if matches:
            item = matches[-1]
            item.update(ocorrencias=item['ocorrencias']+1, atualizado_em=stamp,
                        detalhe=detalhe, acao=acao, proxima_tentativa_em=retomada)
        else:
            sequence = sum(i['chave']==key for i in rows)+1
            item = dict(id=key+'-'+str(sequence),chave=key,codigo=codigo,origem=origem,
                        detalhe=detalhe,acao=acao,proxima_tentativa_em=retomada,
                        primeiro_em=stamp,atualizado_em=stamp,ocorrencias=1,estado='pendente')
        save(db,item)
    return {'habilitado':True,**item}


def status(root):
    enabled = configuration(root) is not None
    path = Path(root)/'data/alertas_impedimentos.sqlite'
    items = []
    if path.exists():
        db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            items = [json.loads(r[0]) for r in db.execute('SELECT payload FROM incidentes ORDER BY rowid')]
        finally:
            db.close()
    return {'habilitado':enabled,'pendentes':[i for i in items if i['estado']=='pendente'],
            'reconciliar':[i for i in items if i['estado'] in ('enviando','incerto')],
            'enviados':sum(i['estado']=='enviado' for i in items)}


def atualizar(root, action, incident_id, receipt=None, evidence=None, at=None):
    config = configuration(root)
    if config is None:
        raise ValueError('Alertas desabilitados; não enviar')
    stamp = execution_time(at)
    with transaction(root) as db:
        row = db.execute('SELECT payload FROM incidentes WHERE id=?',(incident_id,)).fetchone()
        if not row:
            raise ValueError('Impedimento não registrado')
        item = json.loads(row[0])
        result = {'id':incident_id,'enviar':False}
        if action == 'preparar':
            if item['estado']=='pendente':
                item.update(estado='enviando',inicio_envio=stamp)
                subject = 'Impedimento no agente de vagas [ALERTA-'+incident_id+']'
                item['assunto'] = subject
                e = lambda value: html.escape(str(value))
                body = ('<p>A automação encontrou um impedimento.</p>'
                        f'<p><strong>Etapa/fonte:</strong> {e(item["origem"])}<br>'
                        f'<strong>Motivo:</strong> {e(item["codigo"])}<br>'
                        f'<strong>Detectado em:</strong> {e(item["primeiro_em"])}</p>'
                        f'<p>{e(item["detalhe"])}</p><p><strong>Próximo passo:</strong> {e(item["acao"])}</p>'
                        f'<p><strong>Próxima tentativa:</strong> {e(item.get("proxima_tentativa_em") or "Depende da resolução; sem horário confirmado")}</p>'
                        '<p>O progresso permanece registrado. Este alerta não representa uma candidatura.</p>')
                result.update(enviar=True,gmail=dict(link_id=config['gmail_link_id'],
                    to=config['destinatario'],subject=subject,
                    payload={'mime_type':'text/html','charset':'UTF-8','body':{'content':body}},
                    response_fields=['id','thread_id','label_ids']))
        elif action=='confirmar':
            receipt = (receipt or {}).get('structuredContent',receipt or {})
            if item['estado'] not in ('enviando','incerto'):
                raise ValueError('Confirmação exige envio em andamento ou reconciliação')
            if not receipt.get('id') or 'SENT' not in receipt.get('label_ids',[]):
                raise ValueError('Exigir confirmação Gmail com ID e marcador SENT')
            item.update(estado='enviado',confirmado_em=stamp,message_id=receipt['id'],
                        thread_id=receipt.get('thread_id'))
        elif action in ('incerto','resolver','liberar'):
            if not isinstance(evidence,str) or not evidence.strip():
                raise ValueError('Informar evidência real da falha, resolução ou ausência de envio')
            if action=='liberar' and item['estado'] not in ('incerto','enviando'):
                raise ValueError('Liberação exige reconciliação de envio incerto')
            item.update(estado={'incerto':'incerto','resolver':'resolvido','liberar':'pendente'}[action],
                        evidencia_estado=evidence)
        else:
            raise ValueError('Ação de alerta inválida')
        item['atualizado_em']=stamp
        save(db,item)
    return {**result,'estado':item['estado'],
            'requer_reconciliacao':item['estado'] in ('enviando','incerto') and not result['enviar']}


def registrar_sem_interromper(root, **kwargs):
    try:
        return registrar(root, **kwargs)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {'ok':False,'motivo':str(exc),'acao':'Registrar/avisar impedimento pelo agente; não perder o checkpoint'}
