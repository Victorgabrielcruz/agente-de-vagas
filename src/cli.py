import argparse
import json
import sqlite3
from .core import ROOT, Orquestrador, Store, Acompanhamento, read, write, now

def main():
    p=argparse.ArgumentParser(description='Vagas: persistência local e fluxo assistido pelo Codex')
    sub=p.add_subparsers(dest='command',required=True)
    setup=sub.add_parser('configurar', help='Instalação independente, sem sobrescrever configurações existentes')
    setup.add_argument('--arquivo', help='Cadastro JSON local preenchido pelo candidato')
    run=sub.add_parser('run'); run.add_argument('--entrada',default='entrada/vagas.json'); run.add_argument('--preparar',action='store_true'); run.add_argument('--forcar',action='store_true')
    sub.add_parser('status'); sub.add_parser('pause'); sub.add_parser('resume')
    alerts=sub.add_parser('alertas',help='Fila de impedimentos para envio autorizado pelo conector Gmail')
    alerts.add_argument('acao',choices=['status','registrar','preparar','confirmar','incerto','resolver','liberar'])
    alerts.add_argument('--id'); alerts.add_argument('--codigo'); alerts.add_argument('--origem')
    alerts.add_argument('--detalhe'); alerts.add_argument('--proximo-passo'); alerts.add_argument('--evidencia')
    alerts.add_argument('--recibo'); alerts.add_argument('--retomada')
    planning=sub.add_parser('plano-busca', help='Gera plano, sem pesquisar ou registrar cobertura')
    planning.add_argument('--interno',action='store_true',help='Fila individual obrigatória dos portais configurados')
    planning.add_argument('--salvar',help='Grava o plano JSON e exibe somente as contagens')
    cache=sub.add_parser('cache-busca', help='Checkpoint persistente; não executa buscas ou agendamento sozinho')
    cache.add_argument('acao', choices=['status','iniciar','registrar','analisar','isolar-fonte','pausar','retomar','desbloquear','exportar','concluir','limpar'])
    cache.add_argument('--simular',action='store_true',help='Inspeciona a limpeza sem apagar ou compactar')
    cache.add_argument('--resumo',action='store_true',help='Mostra contagens e próximas dez tarefas; preserva a fila inteira no banco')
    cache.add_argument('--plano'); cache.add_argument('--tarefa'); cache.add_argument('--resultado')
    cache.add_argument('--retomada'); cache.add_argument('--evidencia')
    cache.add_argument('--url'); cache.add_argument('--motivo'); cache.add_argument('--nova-rodada',action='store_true')
    checking=sub.add_parser('verificar', help='Verificação local antes da pesquisa, sem alterar dados')
    checking.add_argument('--exigir-sincronizacao',action='store_true')
    checking.add_argument('--nova-rodada',action='store_true',help='Usar somente após pedido direto para nova rodada')
    listing=sub.add_parser('lista'); listing.add_argument('--entrada',default='entrada/curadoria.json'); listing.add_argument('--cobertura',required=True)
    listing.add_argument('--nova-rodada',action='store_true',help='Nova rodada solicitada diretamente; não autoriza e-mail por si só')
    preflight=sub.add_parser('preflight'); preflight.add_argument('--url',required=True)
    answer=sub.add_parser('responder'); answer.add_argument('--pergunta',required=True); answer.add_argument('--valor',required=True); answer.add_argument('--escopo',required=True); answer.add_argument('--fonte',required=True)
    args=p.parse_args()
    if args.command=='alertas':
        from .alertas import status as alert_status, registrar, atualizar
        try:
            if args.acao=='status':
                result=alert_status(ROOT)
            elif args.acao=='registrar':
                result=registrar(ROOT,args.codigo,args.origem,args.detalhe,args.proximo_passo,retomada=args.retomada)
            else:
                result=atualizar(ROOT,args.acao,args.id,
                    receipt=read(ROOT/args.recibo) if args.recibo else None,evidence=args.evidencia)
        except (OSError,ValueError,sqlite3.Error) as exc:
            result={'ok':False,'motivo':str(exc)}
    elif args.command=='configurar':
        from .instalacao import configure
        try:
            result=configure(ROOT,cadastro=ROOT/args.arquivo if args.arquivo else None)
        except (ValueError, OSError, TypeError) as exc:
            result={'ok':False,'motivo':str(exc)}
    elif args.command=='cache-busca':
        from .cache_busca import status, start, mutate, cleanup
        try:
            if args.simular and args.acao!='limpar':
                raise ValueError('--simular só é aceito com cache-busca limpar')
            if args.acao=='limpar':
                result=cleanup(ROOT,simulate=args.simular)
            elif args.acao=='status':
                result=status(ROOT)
            elif args.acao=='iniciar':
                if not args.plano: raise ValueError('Informar --plano com consultas planejadas')
                result=start(ROOT,read(ROOT/args.plano),nova_rodada=args.nova_rodada)
            else:
                result=mutate(ROOT,args.acao,task_id=args.tarefa,
                              result=read(ROOT/args.resultado) if args.resultado else None,
                              url=args.url,reason=args.motivo,retry_at=args.retomada,evidence=args.evidencia)
        except (ValueError, OSError, sqlite3.Error) as exc:
            result={'ok':False,'motivo':str(exc)}
    elif args.command=='verificar':
        from .verificacao import verificar
        result=verificar(ROOT, exigir_sincronizacao=args.exigir_sincronizacao,nova_rodada=args.nova_rodada)
    elif args.command=='plano-busca':
        from .busca import plano_busca, plano_interno
        prefs=read(ROOT/'config/preferencias.yaml')
        result = (plano_interno(prefs,read(ROOT/'config/fontes.yaml')) if args.interno else
                  plano_busca(prefs.get('cargos_adicionais', []),prefs.get('cidades_presenciais')))
        if args.salvar:
            write(ROOT/args.salvar,result)
            result={'arquivo':args.salvar,'consultas_planejadas':len(result),
                    'fontes':sorted({q.get('fonte','buscador') for q in result}),
                    'pesquisa_executada':False}
    elif args.command=='lista':
        from .verificacao import verificar
        result=verificar(ROOT, exigir_sincronizacao=True,nova_rodada=args.nova_rodada)
        if result['ok']:
            from .curadoria import build_daily
            result=build_daily(ROOT/args.entrada,args.cobertura,rebuild=args.nova_rodada)
    elif args.command=='run': result=Orquestrador().run(ROOT/args.entrada,args.preparar,args.forcar)
    elif args.command=='preflight':
        from .preflight import check_portal
        result=check_portal(args.url)
    elif args.command in ('pause','resume'):
        path=ROOT/'config/preferencias.yaml'; data=read(path); data['pausado']=args.command=='pause'; write(path,data); result={'pausado':data['pausado']}
    elif args.command=='responder':
        path=ROOT/'perfil/respostas_aprovadas.json'; data=read(path)
        data['respostas'].append({'pergunta':args.pergunta,'valor':args.valor,'escopo':args.escopo,'fonte':args.fonte,'data':now(),'validade':None,'sensibilidade':'avaliar_antes_de_reutilizar'})
        write(path,data); result={'registrado':True,'fila_exige_revalidacao':True}
    else:
        s=Store(ROOT/'data/candidaturas.sqlite'); result=[dict(r) for r in s.db.execute('SELECT id,state,score,updated FROM jobs')]
    if args.command!='alertas' and isinstance(result,dict) and result.get('ok') is False:
        from .alertas import registrar_sem_interromper
        blockers=result.get('bloqueios',[])
        codes=[i['codigo'] for i in blockers if i.get('codigo') not in ('entrega_ja_confirmada','pausado')]
        if codes or not blockers:
            result['alerta_impedimento']=registrar_sem_interromper(ROOT,
                codigo='verificacao_bloqueada_'+'_'.join(sorted(codes)) if codes else 'falha_comando',origem=args.command,
                detalhe='Verificação bloqueou a execução: '+', '.join(codes) if codes else 'Um comando não pôde concluir a operação.',
                acao='Conferir o diagnóstico local e resolver a causa; preservar o progresso.')
    if args.command=='cache-busca' and args.resumo and isinstance(result,dict):
        result=dict(result)
        for key in ('consultas_pendentes','consultas_adiadas','candidatas_pendentes'):
            if isinstance(result.get(key),list):
                result[key+'_total']=len(result[key])
                result[key]=result[key][:10]
        if isinstance(result.get('cobertura'),dict):
            result['cobertura']=dict(result['cobertura'])
            for key in ('consultas_internas_faltantes','consultas_individuais_faltantes','fontes_indisponiveis'):
                values=result['cobertura'].get(key)
                if isinstance(values,list):
                    result['cobertura'][key+'_total']=len(values)
                    result['cobertura'][key]=values[:10]
        result['exibicao_resumida']=True
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if isinstance(result,dict) and result.get('ok') is False:
        raise SystemExit(2)

if __name__=='__main__': main()
