# Preparação e envio ao GitHub

O repositório distribui código e modelos, sem dados de uma instalação real. Não publique toda a pasta por upload manual ou ignorando o .gitignore.

## O que pode ser publicado

Somente arquivos de `PUBLICACAO.json`: fontes revisadas, testes com exemplos fictícios, configurador, documentação genérica e exemplos vazios. Configurações e perfil reais, bancos SQLite, currículos, relatórios, cache, snapshots, anexos, backups, histórico de documentos e scripts de migração pessoal permanecem locais e ignorados.

`STATUS.md`, `documentacao/OPERACAO_LOCAL.md` e `documentacao/PROMPT_AUTOMACAO_VAGAS.md` são privados. O roteiro compartilhável fica em `documentacao/AUTOMACAO_MODELO.md`. Não copie IDs de automação, conversa, arquivo ou conexão de outra pessoa para os exemplos.

## Auditoria e pacote

```text
python -m unittest discover -s tests -v
python scripts/publicacao.py
python scripts/publicacao.py --pacote tmp/vagas-compartilhavel.zip
```

A auditoria cruza arquivos candidatos ao Git com o manifesto, sinaliza caminhos de usuário, e-mails fora dos domínios de exemplo, IDs pessoais reconhecíveis e padrões de chaves. Quando o perfil privado existe, verifica também seus contatos/links sem imprimir os valores. O ZIP inclui somente a lista revisada e retorna SHA-256.

Essas verificações reduzem o risco, mas não substituem revisar conteúdo novo: dados pessoais podem aparecer em formatos não reconhecidos. Não use `git add -f` para contornar arquivos ignorados. Um arquivo privado já rastreado por Git continua rastreado mesmo depois de entrar no .gitignore; a auditoria deve ser resolvida antes de seguir.

## Revisar e enviar

Depois de escolher ou criar um repositório GitHub vazio na sua conta:

```text
git status --short
git add .
git diff --cached --stat
git diff --cached
python scripts/publicacao.py
git commit -m "Prepara agente de vagas reutilizável"
git branch -M main
git remote add origin <URL_DO_SEU_REPOSITORIO>
git push -u origin main
```

Se já houver origin, confira `git remote -v` antes de alterar destinos. O projeto não faz login no GitHub nem executa push automaticamente. O histórico Git também precisa estar livre de arquivos privados: um ZIP limpo não remove dados que tenham sido commitados anteriormente. A primeira preparação não cria commits ou remoto por conta própria.

## Testar como outra pessoa

Extraia o ZIP em uma pasta nova e execute os testes sem copiar config/, perfil/, data/ ou qualquer artefato local. Rode o configurador, preencha um cadastro próprio e siga INSTALACAO.md. O clone não herda dados, conexões, permissões de e-mail, agendamento ou assinatura do autor.

Ao adicionar fontes novas, atualizar PUBLICACAO.json e revisar o novo conteúdo antes de empacotar. Não inclua um arquivo apenas para fazer a auditoria passar. Antes de abrir distribuição pública para reutilização, escolha também as condições de licença desejadas; nenhuma licença foi presumida nesta preparação.
