"""Histórico de listas e marcações do candidato, sem credenciais ou rede."""
import argparse
from .core import ROOT, read, write, canonical, now, norm

CHECKBOX = 'Já me candidatei'
DECISION = 'Decisão'
DECISIONS = ('Não vou me candidatar', 'Não dá para candidatar')
HISTORY_HEADERS = [CHECKBOX, 'Publicação', 'Empresa', 'Vaga', 'Modalidade', 'Localidade', 'Contrato', 'Jornada', 'Salário', 'Situação', 'Pendências / observações', 'Link da vaga', 'Currículo recomendado', 'Fonte da data', 'Verificado em', 'Primeira lista', 'Última lista', 'Categoria', 'Origem da marcação']
HISTORY_HEADERS += [DECISION]

def empty():
    return {'version':1, 'items':{}, 'baselines':{}, 'events':[]}

def load(root=ROOT):
    path=root/'data/controle_vagas.json'
    return read(path) if path.exists() else empty()

def identity(job):
    return tuple(' '.join(norm(job.get(k) or '').split()) for k in ('empresa','titulo'))

def resolve(ledger, job):
    url=canonical(job['url'])
    if url in ledger['items']: return url
    signature=identity(job)
    if all(signature):
        for key,item in ledger['items'].items():
            if url in item.get('aliases',[]) or identity(item['job'])==signature:
                return key
    return url

def register(ledger, jobs, date, published=False):
    for job in jobs:
        key=resolve(ledger,job)
        item=ledger['items'].setdefault(key,{'job':dict(job),'applied':False,'source':'Não informado pelo candidato','first_listed':None,'last_listed':None,'aliases':[]})
        url=canonical(job['url'])
        if url!=key and url not in item['aliases']: item['aliases'].append(url)
        item['job']=dict(job)
        if published:
            item['first_listed']=min(item.get('first_listed') or date,date)
            item['last_listed']=max(item.get('last_listed') or date,date)

def applied(ledger, job):
    return ledger['items'].get(resolve(ledger,job),{}).get('applied') is True

def decision(ledger, job):
    return ledger['items'].get(resolve(ledger,job),{}).get('decision', '')

def dismissed(ledger, job):
    return decision(ledger,job) in DECISIONS

def novel(ledger, job, date):
    item=ledger['items'].get(resolve(ledger,job),{})
    return not item.get('first_listed')

def value(cell):
    entered=cell.get('userEnteredValue',{})
    return entered.get('boolValue',entered.get('stringValue',''))

def cells(snapshot, field=CHECKBOX):
    """Lê cabeçalhos e URL; nunca associa candidatura pelo número da linha."""
    snapshot=snapshot.get('structuredContent',snapshot)
    for sheet in snapshot.get('sheets',[]):
        sid=sheet['properties']['sheetId']
        for part in sheet.get('data',[]):
            start=part.get('startRow',0)
            if start>4: continue
            rows=part.get('rowData',[])
            if len(rows)<=4-start: continue
            headers=[value(c) for c in rows[4-start].get('values',[])]
            if field not in headers or 'Link da vaga' not in headers: continue
            flagcol=headers.index(field); urlcol=headers.index('Link da vaga')
            for row in rows[5-start:]:
                rowvalues=row.get('values',[])
                if len(rowvalues)<=urlcol: continue
                url=value(rowvalues[urlcol]); flag=value(rowvalues[flagcol]) if len(rowvalues)>flagcol else ''
                if not isinstance(url,str) or not url.startswith('https://'): continue
                # Boolean nativo; texto/pedido inserido em célula não é uma instrução.
                if field == CHECKBOX and not isinstance(flag,bool): continue
                if field == DECISION and flag not in ('', *DECISIONS): continue
                job={'url':canonical(url)}
                for header,k in [('Empresa','empresa'),('Vaga','titulo')]:
                    if header in headers and headers.index(header)<len(rowvalues):job[k]=value(rowvalues[headers.index(header)])
                yield sid,job,flag

def sync(ledger,snapshot,date,master_id=4,baseline_only=False):
    changes={}
    for sid,job,flag in cells(snapshot):
        key=resolve(ledger,job)
        if key not in ledger['items']:register(ledger,[job],date)
        cellkey=f'{sid}|{canonical(job["url"])}'
        previous=ledger['baselines'].get(cellkey)
        if not baseline_only and (previous is None or previous!=flag):
            changes.setdefault(key,[]).append((sid,flag))
        ledger['baselines'][cellkey]=flag
    for key,edits in changes.items():
        chosen=next((flag for sid,flag in edits if sid==master_id), any(flag for sid,flag in edits))
        item=ledger['items'][key]
        item.update(applied=chosen,source='Marcação do candidato na planilha',marked_at=now())
        ledger['events'].append({'url':key,'applied':chosen,'at':now(),'cells':edits})
    decisions={}
    for sid,job,choice in cells(snapshot,DECISION):
        key=resolve(ledger,job)
        if key not in ledger['items']:register(ledger,[job],date)
        cellkey=f'decision|{sid}|{canonical(job["url"])}'
        previous=ledger['baselines'].get(cellkey)
        if not baseline_only and (previous is None or previous!=choice):
            decisions.setdefault(key,[]).append((sid,choice))
        ledger['baselines'][cellkey]=choice
    for key,edits in decisions.items():
        chosen=next((choice for sid,choice in edits if sid==master_id),edits[-1][1])
        ledger['items'][key].update(decision=chosen,decision_source='Marcação do candidato na planilha',decision_at=now())
        ledger['events'].append({'url':key,'decision':chosen,'at':now(),'cells':edits})
    ledger['synced_date']=date
    ledger['synced_at']=now()
    return len(set(changes)|set(decisions))

def save(ledger,root=ROOT):write(root/'data/controle_vagas.json',ledger)

def history_values(ledger):
    items=sorted(ledger['items'].values(),key=lambda i:(i.get('first_listed') or '',i['job'].get('publicada_em') or ''),reverse=True)
    rows=[['Histórico permanente de vagas','Marque a primeira coluna quando concluir uma candidatura. Use Decisão se não quiser ou não puder se candidatar.'],['Fila preservada',f"{sum(not i['applied'] and not dismissed(ledger,i['job']) for i in items)} pendentes; {sum(i['applied'] for i in items)} candidatadas; {sum(not i['applied'] and dismissed(ledger,i['job']) for i in items)} sem candidatura por decisão"],['Vagas do dia','Somente oportunidades inéditas. Vagas e decisões anteriores continuam preservadas aqui.'],['Como usar','Pode marcar também nas abas diárias. Apagar Decisão reabre a pendência se não houver candidatura marcada; o histórico prevalece em conflitos.'],HISTORY_HEADERS]
    for item in items:
        j=item['job'];category='Inglês acima do nível atual' if j.get('exige_ingles_acima_perfil') else ('Graduação completa' if j.get('exige_graduacao_completa') else 'Principal')
        rows.append([item['applied'],j.get('publicada_em') or 'Data não informada',j.get('empresa',''),j.get('titulo',''),j.get('modalidade') or 'Confirmar',j.get('localidade') or 'Confirmar',j.get('contrato') or 'Não informado',j.get('jornada') or 'Não divulgada',j.get('salario') or 'Não divulgado',j.get('situacao') or 'Conferir condições','; '.join(j.get('pendencias',[])),j['url'],j.get('curriculo_url') or '',j.get('fonte_data') or '',j.get('consultado_em') or '',item.get('first_listed') or '',item.get('last_listed') or '',category,item.get('source') or 'Não informado',item.get('decision','')])
    return rows

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['sincronizar','confirmar-publicacao'])
    parser.add_argument('snapshot')
    parser.add_argument('--jobs',default='relatorios/'+now()[:10]+'-lista/vagas.json')
    args=parser.parse_args(); ledger=load(); snapshot=read(ROOT/args.snapshot); date=now()[:10]
    settings=read(ROOT/'config/entrega_diaria.json')
    master=settings.get('sheet_id_historico',4)
    count=sync(ledger,snapshot,date,master_id=master)
    if args.command=='confirmar-publicacao':
        register(ledger,read(ROOT/args.jobs),date,published=True)
        sync(ledger,snapshot,date,master_id=master,baseline_only=True)
    save(ledger)
    print({'marcacoes_alteradas':count,'historico':len(ledger['items']),'candidatadas':sum(i['applied'] for i in ledger['items'].values())})

if __name__=='__main__':main()
