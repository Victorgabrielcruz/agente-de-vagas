# Modelo de roteiro de automação

Copie o texto abaixo para uma automação da sua conta. Substitua os campos entre colchetes pelos dados da sua própria instalação. Nenhum campo deve ser herdado do computador, conversa ou conta de outra pessoa. A criação é feita pelo agendador do aplicativo; salvar este Markdown não ativa nada.

---

Execute a curadoria de vagas na pasta [PASTA_DESTA_INSTALACAO], seguindo AGENTS.md e RUNBOOK.md. Consulte STATUS.md local se existir e documentacao/RETOMADA_BUSCA.md. Os parâmetros, horário diário e destinos são os arquivos privados de config/. Os fatos aprovados são os de perfil/.

Antes de agir, rode verificar e cache-busca status. Respeite pausa global, configuração inicial pendente, orçamento adicional zero e candidatura manual. Entrega confirmada na data local encerra o trabalho do dia. Nova rodada/e-mail adicional somente por pedido direto do usuário desta instalação.

Use somente suas conexões autorizadas. Se não houver pesquisa pendente válida, inicie o ciclo após o horário diário configurado e somente se ainda não houver entrega do dia. Criar plano para os nove grupos e janelas 24h/7d, iniciar o cache e adaptar temporariamente ESTA automação para intervalo de cinco minutos antes da primeira consulta. Preservar ID, conversa e demais campos; não criar outra automação de retomada.

Quando config/fontes.yaml habilitar busca_interna, pesquisar na interface visível dos próprios portais com a sessão desta instalação, criando tarefas por grupo/janela com a fonte identificadora exata. Buscador externo não substitui busca interna. Registrar termos, filtros realmente aplicados, URLs, paginação e análise completa; validar publicação original e deduplicar por ID/URL/requisição. Respeitar recusas e regras da plataforma; não usar API privada, exportar cookies ou automatizar autenticação. Sessão ausente ou bloqueada deve ser documentada como fonte indisponível, sem travar fontes independentes ou alegar cobertura integral.

Se a instalação habilitar todas_chaves_obrigatorias nas fontes, gerar plano-busca --interno --salvar entrada/plano-interno.json e iniciar com essa fila. Pesquisar cada chave literal e cada empresa individualmente em cada portal/região/janela, sem agrupamento OR ou amostragem. O cache acrescenta a fila obrigatória e impede exportação enquanto faltar tarefa acessível. Registrar termo_pesquisado exato, url_busca do próprio portal, filtros_observados e limitacoes_filtros, além da evidência/resultados. Conferir contagens concluídas, indisponíveis e pendentes; falhas documentadas não contam como consultas concluídas.

Depois de cada consulta real ou análise de vaga, registrar o checkpoint. Não contar plano como consulta realizada. Continuar apenas pendências. Em falha transitória, salvar pausa com motivo real e encerrar a execução atual. O agendador desperta novamente, mas o cache determina quando a tentativa está liberada: 5, 10, 20, 30 e até 60 minutos. Respeitar também qualquer prazo maior informado pela ferramenta. Não usar espera bloqueante.

Cache abandonado por interrupção exige registrar o motivo antes da retomada. Mudança de data, critérios ou validade exige novo plano/evidências revalidados, preservando a sessão antiga. Login, CAPTCHA, aprovação, pausa do usuário e envio incerto exigem resolver a causa; não contornar bloqueios com repetições.

Em HTTP 403/429 ou indisponibilidade restrita a uma fonte pública, registrar isolar-fonte com a tarefa, motivo e evidência real; continuar fontes independentes e análises pendentes. Não concluir a consulta falha com zero, não repetir automaticamente nem contornar a recusa. Ao entregar a fila acessível, informar as fontes indisponíveis e a cobertura parcial. Login/CAPTCHA, pausa global e entrega incerta continuam sujeitos às restrições do runbook.

Exportar somente após consultas acessíveis e análises completas, cobertura dos grupos/fontes/janelas e duas ampliações finais distintas sem novidades. Aceitar somente publicações originais comprovadas em até sete dias, priorizando 24h. Cidades, salário, tecnologias e cargos adicionais vêm das preferências; não inventar fatos pessoais.

Sincronizar marcações atuais da planilha por URLs/cabeçalhos, usando IDs configurados. Preservar histórico, flags, congelamentos, anotações e outras abas. Gerar e conferir as três listas. Publicar e verificar somente as áreas gerenciadas. Relatório por e-mail apenas com autorização explícita para o destinatário desta instalação; registrar confirmação real. Entrega parcial ou envio incerto exige reconciliação, sem repetir às cegas.

Após confirmação de entrega, concluir o cache e restaurar a cadência diária no horário configurado. Restaurar também quando não houver pendências ou houver bloqueio não transitório. A limpeza de cache já é acionada pelo código em iniciar/concluir; não criar tarefa adicional. Informar resultados ou falhas relevantes conforme as preferências do usuário e manter STATUS.md local atualizado.
