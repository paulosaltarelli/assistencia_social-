# Assistência Social Municipal

Fundação de um sistema Django e PostgreSQL para o atendimento municipal. A tela autenticada permite registrar famílias, vincular cidadãos e registrar unidade e encaminhamento. O histórico exibe os 50 atendimentos mais recentes. A conta de auditor tem acesso de leitura. Cada profissional tem um vínculo municipal.

## Desenvolvimento na nuvem

Na raiz do checkout, copie .env.example para .env com permissão 0600. Gere três valores aleatórios distintos para Django, PostgreSQL e a conta da aplicação. Use apenas dados fictícios no desenvolvimento. Execute:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
set -a
. ./.env
set +a
docker compose -f compose.yaml -f compose.dev.yaml run --rm -e SOCIAL_ADMIN_PASSWORD social-web sh infra/migrate.sh
```

O serviço de desenvolvimento escuta no loopback, porta 18081. A rota /health/ verifica a disponibilidade do banco e do esquema. Para o teste funcional, defina SOCIAL_DEMO_PASSWORD no ambiente e execute:

```sh
export SOCIAL_DEMO_PASSWORD
SOCIAL_DB_USER=postgres SOCIAL_DB_PASSWORD="$SOCIAL_ADMIN_PASSWORD" docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps -e SOCIAL_DEMO_PASSWORD -e SOCIAL_DB_USER -e SOCIAL_DB_PASSWORD social-web python manage.py seed_demo
docker compose -f compose.yaml -f compose.dev.yaml run --rm -T -e SOCIAL_DEMO_PASSWORD social-web python manage.py shell < tests/smoke.py
```

## Arquitetura e segurança

O vínculo do usuário autenticado define o município no início da transação. O PostgreSQL aplica políticas por linha a famílias, cidadãos, atendimentos e auditoria. A conta de execução tem permissões explícitas. Cada cadastro e consulta ao painel registra o usuário e município, com referência por UUID nas alterações. Cookies seguros em produção, CSRF, ORM parametrizado, escape dos templates, sessão com expiração por inatividade e logout com revogação. O limite de login por conta usa cache de processo e pressupõe uma única instância de um worker.

O escopo atual abrange homologação com dados fictícios. Uploads, benefícios e administração de equipes são fases posteriores. A unidade é informada no atendimento. Antes do uso com cidadãos reais, definir prazos de retenção e descarte, contas nominais, recuperação de acesso, revisão dos perfis e operação de backups. Ver docs/operacao.md.
