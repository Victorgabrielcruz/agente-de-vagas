# Rotina de curadoria para candidatura manual

Este procedimento é reutilizável. Os dados e destinos reais ficam nos arquivos privados desta instalação. Se existir, `documentacao/OPERACAO_LOCAL.md` registra particularidades privadas; elas não devem ser copiadas para outro usuário. Pedidos diretos atuais prevalecem sobre procedimentos antigos.

## 1. Preparar

Concluir a configuração inicial conforme [Instalação](documentacao/INSTALACAO.md). Ler preferências, entrega, fontes, política e perfil. Respeitar pausa, orçamento adicional zero e contratação no Brasil; o preset usa America/Sao_Paulo. Não assumir fatos com base nos exemplos.

Conferir `data/entregas/AAAA-MM-DD.json` na data de Brasília. Entrega confirmada não deve ser repetida automaticamente. Nova rodada exige pedido direto, `--nova-rodada` e sincronização posterior à última confirmação. Entrega parcial ou e-mail incerto exige conferir publicação/Enviados e retomar a entrega existente.

Executar `python -m src.cli verificar` antes da pesquisa. Após ler marcações atuais, executar também `verificar --exigir-sincronizacao`. Lista e build_daily verificam automaticamente antes de gerar os arquivos.

Não candidatar, editar perfis, aceitar compromissos ou contatar recrutadores. Relatório por e-mail somente com autorização explícita desta pessoa para o próprio destinatário configurado. Credenciais permanecem nos conectores, não em arquivos do projeto.

## 2. Sincronizar marcações

Ler metadados e células das abas existentes com cabeçalhos e URLs. Usar nomes/IDs de `config/entrega_diaria.json`, sem supor que a quarta aba tenha um ID específico. Preservar quaisquer outras abas e colunas de anotações.

Diárias: A:N informações, O candidatura, P decisão; histórico: A:T, checkbox A, URL L e decisão T. Resumo linhas 1–4, cabeçalho 5 e dados desde 6. Preservar congelamento das cinco primeiras linhas e quatro primeiras colunas quando aplicável. Células mescladas não podem atravessar a borda congelada; ajustar mesclagens do resumo sem perder texto.

As decisões internas aceitas são `Não vou me candidatar`, `Não dá para candidatar` e vazio. O controle visual pode ser flag com valor personalizado: marcado guarda uma dessas decisões; desmarcado guarda vazio. Isso preserva compatibilidade com o sincronizador. Ler a validação real antes de escrever. Não converter decisões em candidatura ou vaga encerrada.

Salvar o snapshot completo em `entrada/marcacoes-planilha.json` e executar:

```powershell
python -m src.controle_vagas sincronizar entrada/marcacoes-planilha.json
```

Identidade por URL, aliases/requisição e empresa/cargo; nunca número de linha. Mudanças reais prevalecem sobre cópias antigas; histórico prevalece em conflito simultâneo. Desmarcar reabre pendência no histórico sem transformar vaga antiga em inédita. Não truncar o histórico.

## 3. Pesquisar com cache

Seguir [Cache e retomada](documentacao/RETOMADA_BUSCA.md). O Codex executa as buscas; `plano-busca` só imprime consultas externas sugeridas. Fontes com `busca_interna.habilitada` exigem tarefas pela interface do próprio portal, por grupo e janela configurados, com `fonte` igual ao `identificador_cache`. Quando `todas_chaves_obrigatorias` estiver habilitado, gerar `plano-busca --interno --salvar entrada/plano-interno.json`: todas as chaves e empresas têm tarefas individuais por portal/localidade/modalidade/janela, acrescentadas automaticamente ao iniciar. Nenhuma consulta genérica substitui outra chave. Buscador externo não substitui essa cobertura; indisponibilidade documentada permite entrega parcial sem alegar sucesso interno. Registrar filtros reais, termos, URLs, paginação e leituras dos anúncios; não usar APIs privadas ou contornar recusas. Cidades e cargos adicionais vêm das preferências. Registrar somente consultas efetivamente realizadas e evidências observadas.

Cobrir nove grupos: engenharia_software, java_spring, fullstack_mobile, python_qa_automacao, bh_nova_lima, empresas_preferidas, posts_alertas, cargos_equivalentes e sem_nivel. `bh_nova_lima` é uma chave legada de cobertura: nesta instalação representa as localidades configuradas, não uma obrigação de buscar essas cidades. Fontes oficiais e buscador externo; primeiro 24h, depois sete dias. E-mails de alerta somente com conta/filtro autorizados.

Buscar títulos iniciais e equivalentes, inclusive Analista de Sistemas I, Programador I, Software Engineer I, Associate, Entry Level e Trainee; também buscar sem nível no título. Não excluir globalmente sênior da consulta: avaliar o cargo real. Cargos adicionais não comprovam senioridade.

Concluir a análise de todas as candidatas e duas ampliações finais distintas sem novidades plausíveis após deduplicação. Sem meta fixa de vagas, teto de consultas ou limite artificial de 30 minutos. Interrupções reais devem registrar a fila restante e o motivo. Não alegar esgotamento da internet.

## 4. Filtrar

- Publicação original comprovada em sete dias; prioridade 24h, mais recentes primeiro. Descoberta, data de agregador ou republicação não comprovam recência. Datas futuras, antigas ou desconhecidas ficam fora das novidades; registrar motivos.
- Nível júnior/trainee/equivalente; excluir novos estágios, pleno/sênior ou superiores e experiência profissional obrigatória acima de dois anos. Não somar projetos a anos de emprego.
- Localidades presenciais, piso CLT e dias híbridos conforme preferências. Remoto precisa aceitar a localidade do candidato; usar `aceita_localidade`. `aceita_bh` é compatibilidade com entradas antigas.
- Salário não divulgado pode permanecer pendente; condições PJ precisam ser confirmadas. Jornada é informativa, sem filtro de horas.
- Usar somente fatos aprovados. Desconhecido não vira atendido; incompatibilidades comprovadas excluem a vaga.

Separar principal, graduação completa e inglês acima do perfil. Ambas as exigências: apenas aba de inglês, com os dois alertas. As exceções não liberam salário, localidade ou experiência incompatíveis. Não inventar idioma ou curso concluído. Vagas já entregues permanecem no histórico, sem reaparecer como novidades.

## 5. Gerar e entregar

Exportar o cache somente com consultas acessíveis e análises concluídas, e cobertura restante validada. Falha específica de fonte deve ser isolada conforme RETOMADA_BUSCA; informar fontes indisponíveis e cobertura parcial no relatório, sem contornar a recusa ou inventar resultados. Se a escrita for interrompida, reexportar; a verificação bloqueia entrada inconsistente. Sincronizar marcações atuais antes de gerar a lista:

```powershell
python -m src.cli lista --cobertura "resumo real das fontes consultadas"
```

O CLI produz JSON/CSV/Markdown, valores Sheets e manifesto em `relatorios/AAAA-MM-DD-lista`. Ele não pesquisa, publica ou envia sozinho. Reutilizar o currículo factual revisado; PDF novo exige dependências opcionais, conferência de texto/links e inspeção visual registrada. Não alterar currículo aprovado sem necessidade ou acrescentar experiência.

Preparar backup das células e publicar somente as áreas gerenciadas: diárias A:P, histórico A:T. Usar boolValue para candidatura e stringValue para textos/decisões; preservar a validação de flags escolhida pelo usuário. Não executar fórmulas de anúncios. Substituir listas somente após pesquisa concluída, sem limpar antes. Falha mantém lista anterior; zero novidades é permitido após pesquisa real concluída.

Conferir readback e visual disponível, salvar snapshot final e confirmar:

```powershell
python -m src.controle_vagas confirmar-publicacao entrada/marcacoes-planilha.json --jobs relatorios/AAAA-MM-DD-lista/vagas.json
```

Após publicação verificada, enviar somente o relatório autorizado: data, três contagens, total, pendências, cobertura, motivo de encerramento e links da planilha/currículo. Registrar IDs e confirmações em data/entregas. Rascunho não é envio. Confirmar no conector antes de declarar sucesso.

Fechar o cache depois da entrega confirmada e restaurar a cadência diária da mesma automação. A limpeza automática retém sete dias de sessões terminais sem pendências, preserva o checkpoint mais recente e não remove candidaturas/entregas. Atualizar STATUS.md local. Nenhuma promessa de execução com máquina, aplicativo ou conexões indisponíveis.
