"""Validação de prontidão por domínio. Não habilita nem envia por conta própria."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from .core import ROOT, BR, read

def check_portal(url, policy=None, registry=None, at=None):
    policy=read(ROOT/'config/politica_autorizacao.yaml') if policy is None else policy
    registry=read(ROOT/'config/validacao_portais.json') if registry is None else registry
    at=at or datetime.now(BR)
    host=urlsplit(url).hostname or ''
    portal=registry.get('portais',{}).get(host)
    reasons=[]
    if policy.get('envio_producao_global') is not True:
        reasons.append('Produção de envios desabilitada na política persistente')
    if not portal:
        return {'habilitado':False,'dominio':host,'motivos':reasons+['Domínio sem validação registrada']}
    for field,label in [('regras_permitidas','Regras do portal não liberadas'),('fluxo_validado','Fluxo completo não validado'),('perfil_validado','Perfil global ainda contém pendências'),('sessao_validada','Sessão não validada'),('envio_habilitado','Envio não habilitado para este domínio')]:
        if portal.get(field) is not True: reasons.append(label)
    if not portal.get('evidencia_fluxo'): reasons.append('Sem evidência verificável da validação do fluxo')
    try:
        checked=datetime.fromisoformat(portal['verificado_em'])
        age=at-checked
        if checked.tzinfo is None or age<timedelta(0) or age>timedelta(hours=registry.get('validade_horas',24)):
            reasons.append('Validação expirada ou data inválida; revalidar sessão e perfil')
    except (KeyError,ValueError,TypeError): reasons.append('Data de validação ausente ou inválida')
    reasons.extend(portal.get('bloqueios',[]))
    return {'habilitado':not reasons,'dominio':host,'motivos':reasons}
