# Orientações do agente de vagas

## Fontes e configuração independente

- Leia RUNBOOK.md antes de operar; README.md é o mapa do projeto.
- Se existir, STATUS.md contém somente o estado local desta instalação e não deve ir ao Git. Em instalação nova, seguir documentacao/INSTALACAO.md.
- Se existir, documentacao/OPERACAO_LOCAL.md guarda regras privadas da instalação original. Pedidos atuais do usuário e configurações aprovadas prevalecem sobre exemplos ou regras históricas. Não copiar esse arquivo para outra pessoa.
- `config/` contém os destinos e critérios do usuário; `perfil/`, somente fatos aprovados; `data/` e evidências reais registram o que aconteceu. Exemplos não são fatos de um candidato.
- Não inferir nome, graduação, idioma, experiência, cidade ou autorização a partir do código ou dos testes.

## Operação

- Somente curadoria para candidatura manual. Não candidatar, editar perfis ou contatar recrutadores.
- Antes de pesquisar, executar `python -m src.cli verificar`; conferir também o cache e as entregas da data local. Não repetir entrega confirmada sem pedido direto para nova rodada.
- Somente novidades com publicação original comprovada em sete dias, prioridade 24h. Preservar vagas antigas no histórico.
- Seguir documentacao/RETOMADA_BUSCA.md: registrar cada consulta/análise real e retomar somente pendências após o prazo. CAPTCHA, aprovação, login e envio incerto não autorizam contornos.
- Ler metadados e sincronizar marcações por URL/cabeçalhos antes de renovar listas. Usar os IDs configurados e preservar anotações, outras abas, checkboxes e decisões. Manter congelamentos e controles existentes conforme a estrutura real; não restaurar menus antigos sobre flags solicitadas pelo usuário.
- Orçamento adicional zero. Conectar contas e criar automação somente na conta da pessoa que configurou esta instalação; nenhum consentimento da instalação original é herdado.
- A limpeza automática remove somente sessões terminais antigas sem pendências; preservar sempre o checkpoint mais recente. Não apagar o histórico ou o banco inteiro.
- Publicação e e-mail exigem confirmação real e autorização própria; registrar IDs sem expor dados pessoais no Git.

## Manutenção e compartilhamento

- Uma conversa por objetivo. Atualizar STATUS.md local com objetivo, decisões, pendências, evidências e próximo passo.
- Manter dados privados e backups fora do Git. Preservar versões locais em diretório ignorado, sem publicar o histórico pessoal.
- Mudanças de código: `python -m unittest discover -s tests -v`.
- Antes de compartilhar: `python scripts/publicacao.py`; usar somente arquivos de PUBLICACAO.json.
- Não criar dashboard, serviço, outra automação ou publicação remota sem pedido correspondente.
