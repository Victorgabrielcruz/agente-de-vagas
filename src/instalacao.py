"""Configuração independente, sem rede, credenciais ou sobrescrita de instalações ativas."""
import re
from pathlib import Path
from .core import ROOT, read, write, canonical

TEMPLATES = (
    'config/preferencias.yaml', 'config/entrega_diaria.json',
    'config/politica_autorizacao.yaml', 'config/fontes.yaml', 'config/cache_busca.json',
    'config/validacao_portais.json', 'config/agendamento.json',
    'perfil/fatos_confirmados.json', 'perfil/respostas_aprovadas.json',
    'perfil/observacoes_nao_confirmadas.json',
)
PREFERENCES = {'cidades_presenciais', 'clt_acima_de', 'max_dias_hibrido',
               'prioridade_stack', 'empresas_preferidas', 'cargos_adicionais'}
DELIVERY = {'planilha_id', 'email', 'drive_pasta_id', 'gmail_link_id', 'curriculo_url',
            'horario', 'sheet_id', 'sheet_id_graduacao', 'sheet_id_ingles',
            'sheet_id_historico', 'autorizado_email_diario'}


def validate(data):
    if not isinstance(data, dict) or set(data) - {'perfil', 'preferencias', 'entrega'}:
        raise ValueError('Cadastro aceita apenas perfil, preferencias e entrega; não inclua senhas ou tokens')
    profile, prefs, delivery = (data.get(key, {}) for key in ('perfil', 'preferencias', 'entrega'))
    if not all(isinstance(value, dict) for value in (profile, prefs, delivery)):
        raise ValueError('Seções do cadastro devem ser objetos JSON')
    if set(profile) - {'nome','cidade','telefone','email','links','afirmacoes','pendentes','cnpj','disponibilidade','subtitulo_curriculo','ordem_curriculo'}:
        raise ValueError('Campo de perfil desconhecido')
    if set(prefs) - PREFERENCES or set(delivery) - DELIVERY:
        raise ValueError('Parâmetro de configuração desconhecido')
    if not all(isinstance(profile.get(k), str) and profile[k].strip() for k in ('nome', 'cidade')):
        raise ValueError('Preencha nome e cidade com seus dados')
    for address in (profile.get('email'), delivery.get('email')):
        if not isinstance(address, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', address):
            raise ValueError('Preencha os e-mails de perfil e entrega')
    cities = prefs.get('cidades_presenciais')
    if not isinstance(cities, list) or not cities or any(not isinstance(c, str) or not c.strip() or c == 'Cidade Exemplo' for c in cities):
        raise ValueError('Informe suas cidades presenciais')
    if type(prefs.get('clt_acima_de')) not in (int, float) or prefs['clt_acima_de'] < 0:
        raise ValueError('Informe um piso CLT não negativo')
    for key in ('prioridade_stack', 'empresas_preferidas', 'cargos_adicionais'):
        if key in prefs and (not isinstance(prefs[key], list) or any(not isinstance(v, str) or not v.strip() for v in prefs[key])):
            raise ValueError('Preferências de busca devem ser listas de texto')
    if type(prefs.get('max_dias_hibrido', 3)) is not int or not 0 <= prefs.get('max_dias_hibrido', 3) <= 7:
        raise ValueError('Dias híbridos devem estar entre zero e sete')
    if not isinstance(delivery.get('planilha_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,}', delivery['planilha_id']):
        raise ValueError('Informe o ID da sua planilha Google Sheets')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', delivery.get('horario', '07:00')):
        raise ValueError('Horário deve estar em HH:MM')
    if type(delivery.get('autorizado_email_diario', False)) is not bool:
        raise ValueError('Autorização de e-mail deve ser booleana')
    ids = [delivery.get(k, default) for k, default in
           (('sheet_id',0),('sheet_id_graduacao',1),('sheet_id_ingles',2),('sheet_id_historico',4))]
    if any(type(v) is not int or v < 0 for v in ids) or len(set(ids)) != 4:
        raise ValueError('IDs das quatro abas devem ser distintos e não negativos')
    links = profile.get('links', {})
    claims = profile.get('afirmacoes', {})
    if not isinstance(links, dict) or not isinstance(claims, dict):
        raise ValueError('links e afirmacoes devem ser objetos JSON')
    for link in list(links.values()) + ([delivery['curriculo_url']] if delivery.get('curriculo_url') else []):
        canonical(link)
    for claim in claims.values():
        if not isinstance(claim, dict) or not claim.get('texto') or not claim.get('fonte'):
            raise ValueError('Afirmações exigem texto e fonte fornecidos pelo candidato')
    return data


def configure(root=ROOT, cadastro=None, templates=None):
    root = Path(root)
    examples = Path(templates) if templates else ROOT/'exemplos'
    prefs_path = root/'config/preferencias.yaml'
    marker_path = root/'config/instalacao.json'
    if prefs_path.exists():
        marker = read(marker_path) if marker_path.exists() else {}
        if marker.get('concluido') is not False or not read(prefs_path).get('configuracao_inicial_pendente'):
            return {'ok': True, 'instalacao_existente_preservada': True, 'arquivos_alterados': 0}
    payload = validate(read(cadastro)) if cadastro else None
    if payload:
        # Não converter uma instalação que já iniciou atividades em outro perfil.
        runtime = root/'data'
        if runtime.exists() and any(runtime.iterdir()):
            raise ValueError('Instalação com dados operacionais: configuração inicial não pode sobrescrevê-la')
        for name in TEMPLATES:
            path = root/name
            if path.exists() and read(path) != read(examples/name):
                raise ValueError('Arquivo local alterado; preservar personalizações e configurar manualmente: '+name)
    values = {name: read(examples/name) for name in TEMPLATES}
    if payload:
        values['perfil/fatos_confirmados.json'].update(payload['perfil'])
        values['config/preferencias.yaml'].update(payload['preferencias'])
        values['config/preferencias.yaml'].update(configuracao_inicial_pendente=False, pausado=True)
        values['config/entrega_diaria.json'].update(payload['entrega'])
        d = values['config/entrega_diaria.json']
        d['planilha_url'] = 'https://docs.google.com/spreadsheets/d/'+d['planilha_id']+'/edit'
        values['config/agendamento.json']['horario'] = d['horario']
    changed = 0
    for name, value in values.items():
        target = root/name
        if payload or not target.exists():
            write(target, value)
            changed += 1
    write(marker_path, {'concluido': payload is not None})
    if not (root/'entrada/curadoria.json').exists():
        write(root/'entrada/curadoria.json', [])
    return {'ok': True, 'arquivos_alterados': changed, 'configuracao_pendente': payload is None,
            'pausado': True, 'agendamento_criado': False, 'contas_conectadas': False,
            'proximo_passo': 'Conferir perfil, currículo e destinos; conectar suas contas e só então usar resume'}
