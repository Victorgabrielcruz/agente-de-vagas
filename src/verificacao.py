"""Verificação local, somente leitura, antes da pesquisa e da geração diária."""
from datetime import datetime
from pathlib import Path
import sqlite3
import re

from .core import BR, now, read

SEARCH_GROUPS = ['engenharia_software', 'java_spring', 'fullstack_mobile',
                 'python_qa_automacao', 'bh_nova_lima', 'empresas_preferidas',
                 'posts_alertas', 'cargos_equivalentes', 'sem_nivel']


def execution_time(at=None):
    value = datetime.fromisoformat((at or now()).replace('Z', '+00:00'))
    return (value.replace(tzinfo=BR) if value.tzinfo is None else value.astimezone(BR)).isoformat(timespec='seconds')


def verificar(root, at=None, settings=None, exigir_sincronizacao=False, nova_rodada=False):
    """Não consulta serviços remotos, não escreve nem concede autorização externa."""
    root = Path(root)
    stamp = execution_time(at)
    issues, warnings = [], []

    def load(relative):
        try:
            data = read(root / relative)
            if not isinstance(data, dict):
                raise ValueError('Esperado objeto JSON')
            return data
        except (OSError, ValueError, TypeError):
            issues.append({'codigo': 'arquivo_invalido', 'arquivo': relative})
            return {}

    prefs = load('config/preferencias.yaml')
    delivery_config = load('config/entrega_diaria.json') if settings is None else settings
    if not isinstance(delivery_config, dict):
        issues.append({'codigo': 'configuracao_invalida'})
        delivery_config = {}
    policy = load('config/politica_autorizacao.yaml')
    if prefs.get('configuracao_inicial_pendente') is True:
        issues.append({'codigo':'configuracao_inicial_pendente'})

    def expect(data, key, expected, source):
        if key not in data or type(data[key]) is not type(expected) or data[key] != expected:
            issues.append({'codigo': 'configuracao_divergente', 'arquivo': source, 'campo': key})

    if prefs.get('pausado') is True:
        issues.append({'codigo': 'pausado'})
    elif prefs.get('pausado') is not False:
        issues.append({'codigo': 'pausa_nao_definida'})
    for key, expected in {'timezone': 'America/Sao_Paulo', 'orcamento_adicional_brl': 0,
                          'horas_semanais': None, 'max_consultas_por_ciclo': None,
                          'curadoria_limite_segundos': None,
                          'curadoria_analisar_todas_coletadas': True,
                          'mercado': 'Brasil', 'salario_nao_divulgado': True}.items():
        expect(prefs, key, expected, 'preferencias')
    if type(prefs.get('clt_acima_de')) not in (int,float) or prefs['clt_acima_de'] < 0:
        issues.append({'codigo':'piso_clt_invalido'})
    cities = prefs.get('cidades_presenciais')
    if not isinstance(cities,list) or not cities or any(not isinstance(c,str) or not c.strip() for c in cities):
        issues.append({'codigo':'cidades_invalidas'})
    if type(prefs.get('max_dias_hibrido')) is not int or not 0 <= prefs['max_dias_hibrido'] <= 7:
        issues.append({'codigo':'dias_hibridos_invalidos'})
    recency = {'publicacao_max_dias': 7, 'prioridade_publicacao_horas': 24,
               'publicacao_original_obrigatoria': True,
               'incluir_data_desconhecida_nas_novidades': False, 'preservar_historico_antigo': True}
    for data, source in ((prefs, 'preferencias'), (delivery_config, 'entrega_diaria')):
        for key, expected in recency.items():
            expect(data, key, expected, source)
    expected_delivery = {'modo': 'curadoria_manual', 'controle_candidaturas': True,
                         'somente_ineditas_nas_abas_diarias': True,
                         'preservar_nao_marcadas_no_historico': True,
                         'preservar_decisoes_no_historico': True,
                         'timezone': 'America/Sao_Paulo', 'diarias_intervalo': 'A1:P1000',
                         'historico_intervalo': 'A1:T1000', 'diarias_checkbox_coluna': 'O',
                         'historico_checkbox_coluna': 'A', 'diarias_decisao_coluna': 'P',
                         'historico_decisao_coluna': 'T',
                         'incluir_graduacao_completa_em_aba_separada': True,
                         'incluir_ingles_acima_perfil_em_aba_separada': True,
                         'decisao_opcoes': ['Não vou me candidatar', 'Não dá para candidatar'],
                         'ampliacoes_sem_novidades_para_encerrar': 2}
    for key, expected in expected_delivery.items():
        expect(delivery_config, key, expected, 'entrega_diaria')
    ids = [delivery_config.get(k) for k in ('sheet_id','sheet_id_graduacao','sheet_id_ingles','sheet_id_historico')]
    if any(type(v) is not int or v < 0 for v in ids) or len({v for v in ids if type(v) is int}) != 4:
        issues.append({'codigo':'ids_abas_invalidos'})
    if not isinstance(delivery_config.get('horario'),str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',delivery_config['horario']):
        issues.append({'codigo':'horario_invalido'})
    groups = delivery_config.get('grupos_busca')
    if not isinstance(groups, list) or not set(SEARCH_GROUPS).issubset(g for g in groups if isinstance(g, str)):
        issues.append({'codigo': 'grupos_busca_incompletos'})
    expect(policy, 'modo_atual', 'curadoria_manual', 'politica_autorizacao')
    expect(policy, 'envio_producao_global', False, 'politica_autorizacao')

    delivery_path = f'data/entregas/{stamp[:10]}.json'
    if (root / delivery_path).exists():
        previous = load(delivery_path)
        if previous.get('planilha_publicada') is True and previous.get('email_enviado') is True:
            if not nova_rodada:
                issues.append({'codigo': 'entrega_ja_confirmada'})
        else:
            issues.append({'codigo': 'entrega_pendente_reconciliacao',
                           'acao': 'Conferir publicação e Enviados; retomar a entrega existente antes de gerar outra'})

    synced = False
    ledger_path = root / 'data/controle_vagas.json'
    if ledger_path.exists():
        ledger = load('data/controle_vagas.json')
        synced = ledger.get('synced_date') == stamp[:10] and isinstance(ledger.get('items'), dict)
        if nova_rodada and (root / delivery_path).exists():
            previous = load(delivery_path)
            confirmed = previous.get('entrega_confirmada_em')
            try:
                synced = synced and bool(confirmed) and execution_time(ledger.get('synced_at') or 'invalid') > execution_time(confirmed)
            except (ValueError, TypeError):
                synced = False
    if not synced:
        message = {'codigo': 'sincronizacao_necessaria',
                   'acao': 'Ler marcações atuais da planilha e executar controle_vagas sincronizar'}
        (issues if exigir_sincronizacao else warnings).append(message)
    if (root/'data/cache_busca.sqlite').exists():
        try:
            from .cache_busca import status
            cache = status(root, at=stamp)
            if cache['estado'] not in ('sem_cache', 'concluida'):
                if cache.get('cache_invalido') or cache['estado'] != 'pronta' or not cache.get('exportacao_coerente'):
                    message = {'codigo': 'pesquisa_em_cache_pendente',
                               'estado': cache['estado'], 'acao': 'Retomar/revalidar cache antes de gerar lista'}
                    (issues if exigir_sincronizacao else warnings).append(message)
        except (OSError, ValueError, sqlite3.Error):
            issues.append({'codigo': 'cache_invalido', 'acao': 'Preservar arquivo e recuperar checkpoint antes de continuar'})
    warnings.append({'codigo': 'somente_verificacao_local',
                     'acao': 'Conectores, marcações remotas e automação precisam de verificação pelo Codex'})
    return {'ok': not issues, 'data': stamp[:10], 'verificado_em': stamp,
            'sincronizacao_do_dia': synced, 'bloqueios': issues, 'avisos': warnings}


def exigir(result):
    if not result['ok']:
        raise ValueError('Verificação prévia bloqueou a execução: ' +
                         ', '.join(issue['codigo'] for issue in result['bloqueios']))
