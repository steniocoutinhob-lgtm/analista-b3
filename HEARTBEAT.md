# HEARTBEAT.md — Monitoramento Contínuo: Painel de Ações B3

## Visão Geral

Este arquivo configura as tarefas periódicas e orientadas a eventos do agente OpenClaw para o repositório do Painel de Ações B3. O agente roda 24/7 e se comunica exclusivamente via Telegram.

---

## Tarefas Periódicas

### 🔁 A cada 15 minutos — Monitoramento de CI/CD

```yaml
task: ci-monitor
schedule: "*/15 * * * *"
repo: seu-usuario/painel-b3
steps:
  - run: gh run list --limit 5 --json status,name,conclusion,url
  - if: conclusion == "failure"
    then:
      - run: gh run view --log
      - notify: telegram
        message: |
          🔴 CI Falhou — Painel B3

          Workflow: {{ run.name }}
          Step: {{ run.failed_step }}
          Erro: {{ run.log_summary }}

          🔗 {{ run.url }}
  - if: conclusion == "success" AND previous_conclusion == "failure"
    then:
      - notify: telegram
        message: |
          ✅ CI Recuperado — Painel B3

          Workflow: {{ run.name }} voltou a passar.

          🔗 {{ run.url }}
```

---

### 🔁 A cada 30 minutos — Novos PRs

```yaml
task: pr-watcher
schedule: "*/30 * * * *"
repo: seu-usuario/painel-b3
filter: pr.user.type != "Bot"
steps:
  - run: gh pr list --state open --json number,title,author,additions,deletions,url
  - for_each: pr
    if: pr.reviewed_by_agent == false
    then:
      - run: gh pr view {{ pr.number }} --json files,body,commits
      - analyze: soul.md#review-de-pull-requests
      - run: gh pr review {{ pr.number }} --comment --body "{{ review_output }}"
      - mark: pr.reviewed_by_agent = true
      - notify: telegram
        message: |
          🔀 PR Revisado — Painel B3

          PR #{{ pr.number }}: {{ pr.title }}
          Autor: {{ pr.author }}
          Alterações: +{{ pr.additions }} / -{{ pr.deletions }}

          Recomendação: {{ review_recommendation }}

          🔗 {{ pr.url }}
```

---

### 🔁 A cada hora — Novas Issues

```yaml
task: issue-watcher
schedule: "0 * * * *"
repo: seu-usuario/painel-b3
steps:
  - run: gh issue list --state open --json number,title,labels,createdAt,url
  - for_each: issue
    if: issue.labels == [] AND issue.agent_processed == false
    then:
      - analyze: soul.md#labels-do-repositório
      - run: gh issue edit {{ issue.number }} --add-label "{{ suggested_label }}"
      - mark: issue.agent_processed = true
      - notify: telegram
        message: |
          🐛 Nova Issue — Painel B3

          #{{ issue.number }}: {{ issue.title }}
          Label aplicada: {{ suggested_label }}

          🔗 {{ issue.url }}
```

---

### ☀️ Diário às 08h00 — Relatório Matinal

```yaml
task: morning-report
schedule: "0 8 * * *"
repo: seu-usuario/painel-b3
steps:
  - run: gh issue list --state open --json number,title,labels
  - run: gh pr list --state open --json number,title,createdAt,url
  - run: gh run list --limit 3 --json name,status,conclusion,url
  - notify: telegram
    message: |
      📊 Relatório Matinal — Painel B3
      {{ now | date: "%d/%m/%Y" }}

      🐛 Issues abertas: {{ issues.count }}
      {{- if issues.sem_label > 0 }}
        ⚠️ Sem label: {{ issues.sem_label }}
      {{- end }}

      🔀 PRs abertos: {{ prs.count }}
      {{- if prs.sem_review > 0 }}
        ⚠️ Aguardando review há +24h: {{ prs.sem_review }}
      {{- end }}

      ⚙️ Último CI: {{ last_run.name }} — {{ last_run.conclusion }}
      🔗 {{ last_run.url }}
```

---

### 🌙 Diário às 23h00 — Verificação Noturna de Dados

```yaml
task: data-integrity-check
schedule: "0 23 * * *"
repo: seu-usuario/painel-b3
description: >
  Verifica se os arquivos principais do painel foram alterados
  e se as referências à API brapi.dev e ao Google Sheets estão íntegras.
steps:
  - run: gh api repos/seu-usuario/painel-b3/commits?per_page=5
  - for_each: commit
    if: commit.files contains "painel-acoes.html" OR "painel-acoes-v2.html"
    then:
      - run: gh api repos/seu-usuario/painel-b3/contents/painel-acoes-v2.html
      - check:
          - pattern: "brapi.dev"
            must_exist: true
            label: "API brapi.dev presente"
          - pattern: "1rThd3_aum1TryPJbRdSOUrJuIVnaiwpuZPo8D_4VrTU"
            must_exist: true
            label: "ID do Google Sheets presente"
          - pattern: "Chart.js"
            must_exist: true
            label: "Chart.js referenciado"
      - if: any_check_failed
        then:
          - notify: telegram
            message: |
              ⚠️ Alerta de Integridade — Painel B3

              Um arquivo principal foi alterado e pode ter perdido
              referências críticas:

              {{ failed_checks | join: "\n" }}

              Commit: {{ commit.sha | truncate: 7 }}
              Autor: {{ commit.author }}

              🔗 {{ commit.url }}
```

---

## Tarefas Orientadas a Eventos (Webhooks)

```yaml
webhooks:
  - event: pull_request.opened
    action: pr-watcher (imediato)

  - event: issues.opened
    action: issue-watcher (imediato)

  - event: workflow_run.completed
    if: conclusion == "failure"
    action: ci-monitor (imediato)

  - event: push
    branch: main
    action: |
      notify: telegram
      message: |
        🚀 Push em main — Painel B3

        Autor: {{ push.author }}
        Mensagem: {{ push.commit_message }}

        🔗 {{ push.url }}
```

---

## Comandos Manuais via Telegram

Estes comandos podem ser enviados a qualquer momento:

| Comando | Ação disparada |
|---|---|
| `status repo` | Executa o relatório matinal sob demanda |
| `revisar pr #N` | Dispara o pr-watcher para o PR especificado |
| `abrir issue [texto]` | Cria issue com label sugerida automaticamente |
| `listar issues` | Lista as 5 issues abertas mais recentes |
| `logs ci` | Retorna o log do último run de CI |
| `checar dados` | Executa o data-integrity-check imediatamente |

---

## Limites de Segurança

```yaml
safety:
  auto_merge: false               # nunca faz merge automaticamente
  auto_close_issues: false        # nunca fecha issues sem confirmação
  auto_delete_branch: false       # nunca deleta branches
  require_confirmation:
    - delete
    - merge
    - close
  confirmation_phrase: "SIM"      # resposta esperada no Telegram
  protected_values:
    - "1rThd3_aum1TryPJbRdSOUrJuIVnaiwpuZPo8D_4VrTU"  # Google Sheets ID
    - "brapi.dev"                                        # API de mercado
```

---

## Troubleshooting

| Problema | Comando |
|---|---|
| Review não foi postado no PR | `openclaw logs` |
| Telegram não recebeu alerta | `openclaw doctor` |
| Agente não reconhece novo evento | `clawhub search "github"` |
| CI monitor não está rodando | Verificar cron com `openclaw status` |
