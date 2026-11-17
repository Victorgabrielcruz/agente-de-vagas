# Vagas — agente de curadoria assistida

Rotina local para pesquisar vagas, analisar requisitos, manter histórico em SQLite e preparar listas para Google Sheets e relatório por e-mail. Candidaturas são feitas manualmente pelo candidato.

O Codex realiza as buscas e opera os conectores. O Python valida entradas, filtra anúncios, registra checkpoints e gera os arquivos de entrega. Clonar este repositório não instala um modelo de IA, não conecta contas e não cria um agendamento.

## Instalação rápida

Requer Python 3.11 ou superior e Git. O núcleo e os testes usam apenas a biblioteca padrão.

```powershell
git clone <URL_DO_REPOSITORIO>
cd <PASTA_DO_REPOSITORIO>
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m unittest discover -s tests -v
python -m src.cli configurar
```

A configuração inicial cria arquivos privados e começa pausada. Preencha `entrada/cadastro.json` a partir de `exemplos/cadastro.json` e execute:

```powershell
python -m src.cli configurar --arquivo entrada/cadastro.json
```

Instalações existentes são preservadas. O configurador não sobrescreve perfis/configurações ativos, não faz buscas e não envia mensagens. Só remova a pausa depois de conferir os destinos, conectar suas próprias contas e aprovar o currículo.

Veja o [guia de instalação](documentacao/INSTALACAO.md) para criar a planilha, preencher o perfil e configurar uma automação na sua conta.

## Comandos principais

```powershell
python -m src.cli verificar
python -m src.cli plano-busca
python -m src.cli cache-busca status
python -m src.cli cache-busca limpar --simular
python -m src.cli lista --cobertura "fontes realmente consultadas"
python -m src.cli pause
python -m src.cli resume
```

No Windows, `scripts/vagas.cmd` é um atalho que usa a `.venv`, o Python do PATH ou o runtime local disponível. O comando legado `run` não pertence ao fluxo de curadoria e permanece bloqueado nesse modo.

## Como funciona

1. O agendador desperta o Codex na pasta local.
2. O agente confere pausa, critérios e entregas existentes.
3. Pesquisa páginas oficiais e buscadores, registrando consultas/análises reais em cache.
4. Em falhas temporárias, retoma pendências após o prazo; não repete entregas confirmadas.
5. Sincroniza marcações da planilha, gera e verifica as listas, publica e confirma o relatório autorizado.
6. Fecha o cache e limpa sessões terminais antigas sem pendências.

O preset é para vagas iniciais no Brasil, com datas no fuso America/Sao_Paulo, publicações originais comprovadas em até sete dias e orçamento adicional zero. Cidades, piso salarial, tecnologias, empresas e cargos adicionais pertencem à configuração de cada pessoa.

## Documentação

- [RUNBOOK.md](RUNBOOK.md): operação e critérios de conclusão.
- [AGENTS.md](AGENTS.md): instruções reutilizáveis do agente.
- [Instalação](documentacao/INSTALACAO.md): cópia independente e contas próprias.
- [Cache e retomada](documentacao/RETOMADA_BUSCA.md): checkpoints, recuperação e limpeza.
- [Modelo de automação](documentacao/AUTOMACAO_MODELO.md): roteiro sem IDs ou caminhos pessoais.
- [Preparar para GitHub](documentacao/PUBLICACAO.md): auditoria e pacote compartilhável.

Para PDFs, instale opcionalmente `python -m pip install -r requirements-pdf.txt`. O PDF revisado pode ser fornecido pelo próprio candidato. Qualquer currículo novo exige inspeção visual antes de uso.

## Privacidade e publicação

Arquivos reais de perfil, configuração, dados, currículos, relatórios, backups, scripts históricos e o estado local não são publicados. Os testes usam exclusivamente exemplos fictícios, sem precisar de arquivos privados. Nenhuma credencial é necessária para rodar os testes.

```powershell
python scripts/publicacao.py
python scripts/publicacao.py --pacote tmp/vagas-compartilhavel.zip
```

`PUBLICACAO.json` contém a lista explícita de arquivos da distribuição. O empacotador só inclui essa lista e bloqueia arquivos Git extras ou padrões de dados pessoais sinalizados pela auditoria. Revise também qualquer alteração futura antes de publicar.

Sem destino remoto configurado, preparar o projeto não cria repositório nem envia dados ao GitHub.
