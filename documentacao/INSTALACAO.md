# Instalação independente

Cada pessoa usa sua própria conta do Codex, conectores, planilha e arquivos. Não copie a pasta pessoal de quem criou o projeto: clone o repositório ou extraia o ZIP de distribuição auditado.

## 1. Baixar e testar sem dados privados

Instale Python 3.11+ e Git por seus canais oficiais. Em um terminal:

```text
git clone <URL_DO_REPOSITORIO>
cd <PASTA_DO_REPOSITORIO>
python -m venv .venv
```

No Windows: `.venv\Scripts\Activate.ps1`. No Linux/macOS: `source .venv/bin/activate`.
Se a ativação do PowerShell não estiver disponível, execute diretamente `.venv\Scripts\python.exe`; não é necessário reduzir a política de segurança do computador.

```text
python -m unittest discover -s tests -v
python -m src.cli configurar
```

O núcleo usa a biblioteca padrão; SQLite já acompanha Python. PDF é opcional: `python -m pip install -r requirements-pdf.txt`. Nenhum teste usa suas contas, credenciais, e-mail ou planilha.

## 2. Preencher cadastro privado

Copie `exemplos/cadastro.json` para `entrada/cadastro.json`. Edite somente essa cópia privada com:

- Perfil: nome, cidade, e-mail, telefone opcional e links HTTPS.
- Preferências: cidades presenciais, piso CLT, dias híbridos, tecnologias, empresas e cargos adicionais. Os exemplos não descrevem uma pessoa real.
- Entrega: ID da sua planilha, seus e-mails/destinos, horário e IDs reais das abas.
- `curriculo_url`: link privado autorizado de um currículo factual revisado, se já disponível. Não torne o currículo público para facilitar a automação.
- `autorizado_email_diario`: começa `false`. Só marque `true` se quiser autorizar o relatório diário para o destinatário informado. O cadastro não envia nada.

Nunca inclua senha, cookie, chave de API ou token. `gmail_link_id` é apenas o identificador da conexão autorizada disponível no ambiente; não é uma credencial que possa ser copiada de outra pessoa.

As `afirmacoes` do perfil começam vazias. Preencha cada afirmação com `texto` e `fonte` reais fornecidos por você, opcionalmente `secao`. Não declare idioma, formação ou experiência que ainda não confirmou. Pode deixar o perfil factual vazio enquanto prepara os materiais, mas não gerar currículo nessa condição.

```text
python -m src.cli configurar --arquivo entrada/cadastro.json
```

Esse comando só completa uma instalação nova ou uma configuração inicial ainda não personalizada. Se já houver arquivos locais alterados, pesquisa iniciada ou instalação ativa, ele preserva os dados e informa a limitação. Não existe `--force`. Para alterar preferências de uma instalação ativa, edite os arquivos privados correspondentes com o agente e revise o resultado.

## 3. Criar sua planilha e conectar suas contas

Abra a pasta do projeto no Codex. Conecte suas próprias contas de Google Sheets/Drive e, se quiser relatório por e-mail, Gmail. O projeto não instala conectores, copia sessões nem acessa contas de outra pessoa.

Peça ao agente para criar uma planilha vazia e conferir os metadados antes de preencher `config/entrega_diaria.json`. Registre os IDs reais de cada aba; eles não precisam ser sequenciais:

| Aba | Estrutura |
|---|---|
| Vagas do dia | A:P |
| Graduação completa | A:P |
| Inglês acima do nível atual | A:P |
| Histórico de vagas | A:T |

Diárias: A:N informações da vaga; O é `Já me candidatei`; P é `Decisão`. Histórico: A é `Já me candidatei`, L é `Link da vaga`, T é `Decisão`. Cabeçalho na linha 5 e vagas a partir da 6. O módulo `src/controle_vagas.py` define os cabeçalhos do histórico; `src/curadoria.py`, os das listas.

Para decisão com flag, usar checkbox com valor marcado personalizado `Não vou me candidatar` e desmarcado vazio. Decisões anteriores `Não dá para candidatar` podem ter esse valor personalizado preservado na própria célula. Checkbox de candidatura usa booleanos nativos. Não renomeie os cabeçalhos usados pelo sincronizador sem adaptar o código.

Congelar linhas 1–5 e colunas A:D facilita navegar. Mesclagens do resumo devem terminar até D para não atravessar a borda congelada. Preserve colunas de anotações além das gerenciadas.

## 4. Conferir antes de ativar

```text
python -m src.cli verificar
python -m src.cli plano-busca
python -m src.cli cache-busca status
```

A instalação começa pausada, então o bloqueio `pausado` é esperado. A sincronização ainda não realizada aparece como aviso antes da pesquisa e bloqueio antes de gerar a lista. Não invente um snapshot para liberar essa etapa: leia a planilha real pelo conector.

Confirme destinos, autorização de comunicação, fatos e currículo. Quando estiver pronto:

```text
python -m src.cli resume
python -m src.cli verificar
```

Teste uma execução assistida com o agente seguindo RUNBOOK.md antes de criar o agendamento. Pesquisa real exige acesso às ferramentas da sua conta; o comando `plano-busca` não faz buscas sozinho. Não há API de IA nem chave de modelo no código.

## 5. Agendar na sua própria conta

Use [AUTOMACAO_MODELO.md](AUTOMACAO_MODELO.md) como roteiro e peça ao Codex para criar uma automação vinculada à conversa e pasta desta instalação, no horário informado em `config/entrega_diaria.json`. Antes de criar, confira se já existe uma automação correspondente; não duplique.

Registre o ID retornado em `config/agendamento.json`. Esse arquivo começa sem ID e não cria automações sozinho. Cada cópia deve ter seu próprio ID, conversa, conta e pasta. A máquina, o aplicativo e as conexões locais precisam estar disponíveis. Não há garantia de recuperar uma execução perdida com o computador desligado.

As retomadas usam temporariamente a mesma automação em intervalos de cinco minutos, respeitando o prazo do cache; depois voltam à cadência diária. Confira a primeira execução e a primeira retomada reais.

## Limites desta distribuição

O preset é para contratação no Brasil e datas em America/Sao_Paulo. Mudar o fuso exige também revisar a lógica de data do código, não apenas trocar uma string. Os nove grupos e a janela de sete dias fazem parte do protocolo atual. A chave legada `bh_nova_lima` representa o grupo de localidades configuradas.

O repositório não envia candidaturas, não hospeda um agente na nuvem e não inclui dashboard. APIs/conectores e limites de uso dependem da conta e do ambiente de cada pessoa. O gerador genérico de currículo usa somente os textos aprovados e pode precisar de revisão de layout; PDFs existentes não são regenerados automaticamente.
