from src.core import ROOT, read, write
from src.controle_vagas import empty


def prepare_root(root, date='2026-11-16'):
    for name in ('preferencias.yaml', 'entrega_diaria.json', 'politica_autorizacao.yaml'):
        write(root/'config'/name, read(ROOT/'exemplos/config'/name))
    prefs=read(root/'config/preferencias.yaml')
    prefs.update(pausado=False,configuracao_inicial_pendente=False)
    write(root/'config/preferencias.yaml',prefs)
    settings=read(root/'config/entrega_diaria.json')
    settings.update(planilha_id='planilha_ficticia_somente_testes',planilha_url='https://example.org/planilha',
                    email='pessoa@example.org',curriculo_url='https://example.org/curriculo.pdf')
    write(root/'config/entrega_diaria.json',settings)
    ledger = empty()
    ledger.update(synced_date=date, synced_at=date+'T06:59:00-03:00')
    write(root/'data/controle_vagas.json', ledger)
    return read(root/'config/entrega_diaria.json')
