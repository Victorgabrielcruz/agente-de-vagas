# Cache e retomada da pesquisa

Vigente desde 17/11/2026. O Python guarda checkpoints locais; o Codex continua responsável pelas buscas e pelos conectores. Cache não é um motor de pesquisa nem um agendador.

## Quando executar

A mesma automação diária inicia a rotina no horário diário configurado (America/Sao_Paulo). Ao começar uma pesquisa autorizada, atualizar temporariamente essa automação existente para intervalo de cinco minutos, preservando id, thread, prompt, estado e demais campos. Isso também permite recuperar uma interrupção abrupta após o último checkpoint. Não criar outra automação, serviço ou cron.

Em cada despertar, conferir `cache-busca status` e `verificar` antes de trabalhar. Sem cache pendente, antes do horário diário configurado ou com entrega já confirmada no dia, não iniciar uma rodada nova; restaurar a cadência diária no horário diário configurado. Com pesquisa pendente válida, retomar somente quando vencer `proxima_tentativa_em`. Não usar sleep para esperar o intervalo. Depois de concluir a entrega ou encontrar bloqueio não transitório, restaurar a cadência diária. A automação depende de máquina, app, conexões e assinatura disponíveis; o horário de despertar não é garantido pelo cache.

## Preparar o plano

Criar `entrada/plano-cache.json` com consultas planejadas para os nove grupos e janelas 24h/7d. Cada item exige `grupo`, `consulta`, `fonte`, `tipo_fonte` (`oficial`/`buscador`), `janela`; `ampliacao: true` identifica ampliações futuras. Não marcar consultas como realizadas ao montar o plano. Consultas novas podem ser acrescentadas chamando iniciar com plano ampliado: tarefas concluídas não são apagadas.

```powershell
.\scripts\vagas.cmd cache-busca iniciar --plano entrada/plano-cache.json
.\scripts\vagas.cmd cache-busca status
```

`iniciar --nova-rodada` somente por pedido direto para nova rodada. A retomada da mesma pesquisa usa a autorização persistida, não uma nova autorização de entrega. Se a mudança de dia, validade (24h) ou critérios invalidar o cache, criar plano revalidado e chamar iniciar: a sessão anterior fica arquivada no banco, e consultas/análises precisam ser refeitas com evidência atual. Não exportar dados expirados.

## Cobertura interna configurada

Fontes com `busca_interna.habilitada` em config/fontes.yaml definem `identificador_cache`, `grupos` e `janelas`. Cada nova sessão guarda essas exigências. Criar tarefas com `fonte` exatamente igual ao identificador; buscas externas não satisfazem consultas internas, mesmo quando usam `site:`. `consultas_internas_faltantes` enumera combinações não consultadas nem isoladas com evidência. Enquanto houver combinações faltantes, a exportação permanece bloqueada. Fonte isolada mantém cobertura parcial e não é contada como consulta concluída.

## Fila individual de todas as chaves

Quando `todas_chaves_obrigatorias` estiver habilitado na fonte, o gerador lê `chaves_individuais`, `modificadores_nivel`, cargos adicionais, todas as empresas preferidas e localidades configuradas. Use `python -m src.cli plano-busca --interno --salvar entrada/plano-interno.json`; o comando somente grava planejamento. `iniciar` acrescenta a fila obrigatória automaticamente, mesmo se o plano fornecido omitir chaves.

Uma tarefa identifica chave literal, tipo termo/empresa, portal, superfície, localidade, modalidade e janela. O ID inclui esses campos; uma pesquisa não satisfaz outra. Chaves repetidas idênticas são deduplicadas, sem agrupar termos diferentes com OR. Modificadores usam consultas próprias `software + nível`, além dos títulos base. Cada empresa recebe tarefa individual; validar escopo de tecnologia/software nos resultados.

Para registrar uma tarefa individual, além de `evidencia`, `novas` e `candidatas`, informar `termo_pesquisado`, `url_busca`, `filtros_observados` (objeto) e `limitacoes_filtros` (lista). O termo deve coincidir com a chave e a URL deve pertencer ao portal correto. A API privada não é necessária nem autorizada por esse formato.

`cache-busca status --resumo` (e `--resumo` nos comandos de progresso) exibe somente as próximas dez tarefas e as contagens totais, mantendo a fila inteira no banco. Continuar até zerar; a primeira página do resumo não é a fila completa.

`chaves_individuais` mostra total, concluídas, indisponíveis e pendentes. `consultas_individuais_faltantes` bloqueia a exportação, mesmo quando grupos gerais já foram cobertos. Retomadas preservam tarefas concluídas. Falhas de uma fonte ficam isoladas por tarefa com evidência real; não contam como pesquisa concluída, e a entrega permanece explicitamente parcial.

## Salvar após cada operação real

O estado fica em `data/cache_busca.sqlite`, separado do SQLite de candidaturas. Escritas usam transações e bloqueio de escrita; falhas revertem o checkpoint inteiro. Resultado recebido e ainda não registrado pode exigir repetir a última consulta, mas as já registradas são preservadas.

Após CADA consulta real, gravar resultado JSON com `evidencia` (fonte/resultado observado), `novas` (quantidade real após deduplicação, não inventada) e `candidatas` (lista de objetos com empresa, titulo e URL HTTPS, incluindo outros dados coletados). Usar o id retornado pelo cache:

```powershell
.\scripts\vagas.cmd cache-busca registrar --tarefa ID --resultado entrada/resultado-consulta.json
```

Uma consulta que falhou não deve ser registrada como concluída com zero resultados. Se a falha for específica da fonte, isolá-la e continuar as demais; pausar a sessão somente quando a falha impedir o trabalho geral. Registrar uma consulta idêntica já concluída é idempotente; evidência diferente exige consulta nova/revalidação, sem sobrescrever a anterior. URLs canônicas deduplicam candidatas; uma evidência nova que mude os dados reabre sua análise.

Após analisar CADA candidata, gravar objeto completo da vaga, com `url`, `empresa`, `titulo`, `evidencia_analise`, critérios, pendências e incompatibilidades conforme o runbook:

```powershell
.\scripts\vagas.cmd cache-busca analisar --url https://empresa.example/vaga --resultado entrada/analise-vaga.json
```

Análise concluída não significa elegibilidade. Vagas excluídas também devem ter análise registrada com seus motivos; não deixar a fila parada por uma incompatibilidade conhecida. Recência e demais filtros continuam sendo aplicados na geração.

## Pausar e tentar novamente

```powershell
.\scripts\vagas.cmd cache-busca pausar --motivo timeout
.\scripts\vagas.cmd cache-busca retomar
```

Motivos transitórios: `timeout`, `conexao`, `limite_temporario`, `interrupcao`. Intervalos em `config/cache_busca.json`: 5, 10, 20, 30 e 60 minutos; falhas seguintes permanecem em 60. Progresso registrado zera falhas consecutivas. A pausa repetida da mesma falha não adia o timer. `retomar` antes do vencimento devolve estado de espera, sem liberar registros. Se a ferramenta informar prazo de recuperação maior, respeitar esse prazo; não tentar contornar limites.

Se um despertar encontrar `pesquisando` abandonado por uma execução interrompida, registrar pausa `interrupcao` e esperar o próximo prazo, sem inferir que a consulta em andamento terminou. A mesma conversa processa os despertares serialmente; não iniciar outro pesquisador concorrente sobre a mesma sessão.

Outros motivos, como CAPTCHA/login, aprovação, credenciais ou regra incompatível, geram estado `bloqueada`, sem timer. Resolver a causa; somente após confirmação real usar `cache-busca desbloquear --motivo "causa resolvida"`. Não transformar bloqueio de permissão, pausa do usuário ou falha de envio em repetição automática. A pausa da busca não altera `preferencias.pausado`; a pausa global do usuário continua prevalecendo.

## Isolar uma fonte indisponível

HTTP 403/429 ou indisponibilidade de uma fonte pública não deve bloquear as fontes independentes. Registrar a consulta pendente com `cache-busca isolar-fonte --tarefa ID --resultado entrada/falha-fonte.json`. O JSON exige `motivo` (`http403`, `http429`, `fonte_indisponivel` ou `dependencia_bloqueada`) e `evidencia` real. A tarefa continua não concluída, separada em `consultas_adiadas`, sem zero resultados inventado nem repetição automática. Não trocar credenciais, endereço ou ferramenta para contornar recusa. Login/CAPTCHA, pausa global e envio incerto mantêm suas restrições.

A exportação pode concluir a fila acessível depois das análises e cobertura restantes, incluindo as ampliações finais. As fontes isoladas ficam explícitas em `fontes_indisponiveis`; a cobertura integral permanece falsa e o relatório deve informar a limitação. Isso não autoriza incluir vagas cuja publicação original não foi comprovada.

## Terminar e entregar

```powershell
.\scripts\vagas.cmd cache-busca exportar
.\scripts\vagas.cmd verificar --exigir-sincronizacao
.\scripts\vagas.cmd lista --cobertura "resumo real das fontes"
```

Exportação exige todas as consultas acessíveis e análises concluídas, nove grupos, janelas/fontes e duas ampliações finais distintas sem novidades. Sem cobertura suficiente, ampliar o plano e continuar. Não há meta fixa de vagas/consultas nem limite artificial de duração da busca.

`exportar` monta `entrada/curadoria.json` e `entrada/cobertura.json` a partir do checkpoint autoritativo. Se a escrita for interrompida, reexportar. A verificação bloqueia lista com cache incompleto, inválido ou entradas diferentes da exportação; não usar entrada antiga para contornar a pausa. Sincronizar marcações atuais antes da entrega, inclusive nas retomadas.

Publicar/verificar/enviar conforme o runbook. Falha após publicação ou durante envio exige reconciliação da entrega existente, sem repetir busca ou mensagem às cegas. Após confirmação real de planilha e e-mail:

```powershell
.\scripts\vagas.cmd cache-busca concluir
```

Restaurar a automação existente para a cadência diária no horário diário configurado. Não reenviar entrega confirmada por causa de um checkpoint ainda não fechado. A primeira ativação deste recurso não executa pesquisa nem cria entrega.

## Limpeza automática

`config/cache_busca.json` define `limpeza_automatica: true` e `retencao_dias: 7`. Ao iniciar/retomar o plano por `iniciar` e depois de `concluir` a entrega, o código remove checkpoints concluídos ou invalidados cuja última atualização tenha mais de sete dias. O instante de invalidação inicia a retenção da sessão substituída.

Preservar sempre o checkpoint mais recente, estados desconhecidos/inválidos, pesquisas em andamento, aguardando tentativa, bloqueadas ou prontas para entrega. Mesmo uma sessão invalidada fica preservada se tiver consultas ou análises pendentes. A validade de 24h não autoriza sua exclusão. O banco de candidaturas, ledger, entregas, currículos e arquivos de entrada não são alvos desta limpeza.

As exclusões são transacionais. Depois, a limpeza compacta páginas livres do próprio banco; se houver bloqueio concorrente, a compactação fica pendente para nova tentativa. O comando retorna contagens de elegíveis, removidos e preservados. Nenhum agendamento adicional é necessário: os comandos já usados na rotina acionam a limpeza.

Para inspecionar ou executar separadamente:

```powershell
.\scripts\vagas.cmd cache-busca limpar --simular
.\scripts\vagas.cmd cache-busca limpar
```

Simulação não exclui, compacta nem cria banco. Não apagar o arquivo SQLite inteiro para liberar espaço: isso removeria o ponto de retomada. Pesquisas pendentes antigas exigem resolução/revalidação explícita, e não descarte automático por idade.
