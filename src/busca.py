"""Termos de descoberta e triagem de senioridade; não executa pesquisas web."""
import re
import unicodedata


def plano_interno(preferencias, fontes):
    """Fila determinística: uma chave, portal, região e janela por tarefa."""
    from .verificacao import SEARCH_GROUPS
    catalogo = fontes.get('chaves_individuais', [])
    tasks = []
    for source in fontes.get('fontes', []):
        rule = source.get('busca_interna', {})
        if rule.get('habilitada') is not True or rule.get('todas_chaves_obrigatorias') is not True:
            continue
        if not isinstance(catalogo, list) or not catalogo:
            raise ValueError('Busca individual exige catálogo explícito de chaves')
        label = rule.get('identificador_cache')
        if not isinstance(label, str) or not label.strip():
            raise ValueError('Portal interno exige identificador_cache')
        keys, seen = [], set()

        def add(term, group, kind='termo'):
            if (not isinstance(term, str) or not term.strip() or
                    any(c in term for c in ('\n', '\r')) or group not in SEARCH_GROUPS):
                raise ValueError('Chave individual exige termo e grupo válidos')
            identity = (term.strip().casefold(), kind)
            if identity not in seen:
                seen.add(identity)
                keys.append((term.strip(), group, kind))

        for key in catalogo:
            if not isinstance(key, dict):
                raise ValueError('Chave individual deve ser objeto')
            add(key.get('termo'), key.get('grupo'))
        for term in preferencias.get('cargos_adicionais', []):
            add(term, 'sem_nivel')
        for level in fontes.get('modificadores_nivel', []):
            if not isinstance(level, str) or not level.strip():
                raise ValueError('Modificador de nível inválido')
            add('software '+level.strip(), 'cargos_equivalentes')
        if fontes.get('pesquisar_cada_empresa') is True:
            for company in preferencias.get('empresas_preferidas', []):
                add(company, 'empresas_preferidas', 'empresa')
        cities = preferencias.get('cidades_presenciais', [])
        if not isinstance(cities, list):
            raise ValueError('Cidades devem ser uma lista')
        regions = [(preferencias.get('mercado') or 'Brasil', 'remoto')]
        for city in cities:
            if not isinstance(city, str) or not city.strip():
                raise ValueError('Cidade inválida')
            region = (city.strip(), 'presencial/híbrido')
            if region not in regions:
                regions.append(region)
        windows = rule.get('janelas', ['24h', '7d'])
        if not isinstance(windows, list) or not windows or any(w not in ('24h', '7d') for w in windows):
            raise ValueError('Janelas internas inválidas')
        for window in ('24h', '7d'):
            if window not in windows:
                continue
            for region, mode in regions:
                for term, group, kind in keys:
                    tasks.append(dict(grupo=group if mode == 'remoto' else 'bh_nova_lima',
                        consulta=term, chave=term, chave_tipo=kind, fonte=label,
                        tipo_fonte='oficial', janela=window, localidade=region,
                        modalidade=mode, superficie='vagas'))
            # Publicações são cobertura adicional do LinkedIn, sem inventar esse recurso na Gupy.
            if 'posts_alertas' in rule.get('grupos', []):
                tasks.append(dict(grupo='posts_alertas', consulta='desenvolvedor júnior',
                    chave='desenvolvedor júnior', chave_tipo='termo', fonte=label,
                    tipo_fonte='oficial', janela=window,
                    localidade=preferencias.get('mercado') or 'Brasil',
                    modalidade='remoto', superficie='publicacoes'))
    # Priorizar 24h em ambos os portais, preservando ordem do catálogo dentro de cada janela.
    return sorted(tasks, key=lambda q: 0 if q['janela'] == '24h' else 1)


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto)).lower()
                   if not unicodedata.combining(c))


def nivel_titulo(titulo):
    texto = normalizar(titulo)
    if re.search(r'\b(estagio|estagiari[oa]|internship|intern)\b', texto):
        return 'estagio'
    if re.search(r'\b(pleno|senior|sr|staff|principal|especialista|lead|lider|ii|iii|iv)\b', texto) or re.search(
            r'\b(engineer|developer|programador|desenvolvedor|analista(?: de sistemas)?)\s+[2-9]\b', texto):
        return 'fora_escopo'
    if re.search(r'\b(junior|jr|trainee)\b', texto):
        return 'junior'
    if re.search(r'\b(associate|entry[ -]level)\b', texto) or re.search(
            r'\b(analista(?: de sistemas| de desenvolvimento)?|programador|desenvolvedor|engineer|developer)\s+(i|1)\b', texto):
        return 'equivalente'
    return 'nao_informado'


def plano_busca(cargos_adicionais=(), cidades=None):
    """Consultas sugeridas; só registrar cobertura depois de executá-las."""
    familias = {
        'cargos_equivalentes': [
            '("Analista de Sistemas I" OR "Analista de Desenvolvimento I" OR "Programador I")',
            '("Software Engineer I" OR "Software Developer I" OR "Associate Software Engineer" OR "Entry Level Developer")',
            '("desenvolvedor" OR "software") ("júnior" OR "jr" OR "trainee")',
        ],
        'sem_nivel': [
            '("desenvolvedor Java" OR "desenvolvedor backend" OR "analista de sistemas")',
            '("desenvolvedor full stack" OR "desenvolvedor Node.js" OR "desenvolvedor React Native")',
            '("desenvolvedor Python" OR "analista de automação" OR "analista de testes")',
        ],
    }
    # Cargos configurados entram sem presumir senioridade pelo título.
    for cargo in cargos_adicionais:
        if not isinstance(cargo, str) or not cargo.strip() or '"' in cargo or '\n' in cargo or '\r' in cargo:
            raise ValueError('Cargo adicional deve ser um título não vazio, sem aspas ou quebras de linha')
        termos = f'"{cargo.strip()}"'
        if termos not in familias['sem_nivel']:
            familias['sem_nivel'].append(termos)
    locations = ['(remoto OR "remote Brazil")']
    if cidades:
        if not isinstance(cidades, list) or any(not isinstance(c, str) or not c.strip() or any(x in c for x in ('"','\n','\r')) for c in cidades):
            raise ValueError('Cidades devem ser uma lista de nomes sem aspas ou quebras de linha')
        locations.append('('+' OR '.join('"'+city.strip()+'"' for city in cidades)+')')
    return [dict(grupo=grupo, consulta=f'{termos} {local}', janela=janela,
                 tipo_fonte='buscador')
            for grupo, termos_lista in familias.items() for termos in termos_lista
            for local in locations
            for janela in ('24h', '7d')]
