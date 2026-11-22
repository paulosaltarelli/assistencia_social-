# Gestão Social Municipal · Vexo

Plataforma municipal de assistência social. A homologação de Santa Cruz de Minas reúne busca de pessoas por CPF/NIS no cadastro municipal, famílias, atendimentos, benefícios eventuais, Vale-Alimentação, pedidos e estoque de materiais, execução financeira, documentos, prestação de contas, indicadores e gestão de acessos.

## Ambiente de desenvolvimento em nuvem

Use um arquivo `.env` privado, com permissão 0600. Preencha `SOCIAL_ADMIN_PASSWORD`, `SOCIAL_DB_PASSWORD`, `DJANGO_SECRET_KEY` e `SOCIAL_CHAVE_INDICE` com quatro valores aleatórios distintos. O índice protegido de CPF e NIS precisa de uma chave estável para recuperar os cadastros após atualizações. As variáveis aceitas estão em `.env.example`.

```sh
dc() { docker compose -p social-prefeituras-dev -f compose.yaml -f compose.dev.yaml -f compose.antivirus.yaml "$@"; }
dc up --build -d social-db social-antivirus
set -a
. ./.env
set +a
dc run --rm -T --no-deps -e SOCIAL_ADMIN_PASSWORD social-web sh infra/migrate.sh
dc up --build -d social-web
```

O web escuta em `127.0.0.1:18081`. `/health/` consulta a disponibilidade do esquema com a conta da aplicação. O scanner recebe os arquivos pela rede privada de verificação. A inclusão de documentos exige assinaturas válidas e varredura concluída.

## Testes e demonstração

A suíte Django exige um PostgreSQL descartável com a role `social_app` criada por `infra/init-db.sh`. Forneça uma conta administrativa apenas ao processo que cria o banco dos testes. A suíte também verifica as operações sob `social_app`. O teste integrado da carga exige o scanner real.

```sh
dc run --rm -T --no-deps -e SOCIAL_DB_USER=postgres -e SOCIAL_DB_PASSWORD="$SOCIAL_ADMIN_PASSWORD" social-web python manage.py test
python -m unittest discover -s tests -p 'test_base_legal.py'
```

Para executar `tests/smoke.py`, defina uma senha exclusiva de desenvolvimento em `SOCIAL_DEMO_PASSWORD`. O comando `seed_demo` provisiona os dois municípios fictícios usados nesse teste. O smoke faz requisições HTTP com sessão e CSRF e verifica o isolamento entre perfis e municípios.

```sh
dc run --rm -T --no-deps -e SOCIAL_DB_USER=postgres -e SOCIAL_DB_PASSWORD="$SOCIAL_ADMIN_PASSWORD" -e SOCIAL_DEMO_PASSWORD social-web python manage.py seed_demo
SOCIAL_SMOKE_URL=http://127.0.0.1:18081 python tests/smoke.py
```

Para a demonstração municipal, o tenant deve se chamar **Santa Cruz de Minas** e ter um autor já vinculado. Com `SOCIAL_HOMOLOGACAO=1`, execute `python manage.py popular_demonstracao --municipio-id ID --usuario USUARIO --confirmar-homologacao` como `social_app`. A primeira execução fixa o período de doze meses. O comando é transacional, protege contra cargas concorrentes e pode ser repetido. Pessoas, endereços, atendimentos, valores e arquivos trazem identificação de simulação. Os CPFs e NIS dos exemplos ficam em branco.

A consulta de CPF/NIS cobre o cadastro municipal autorizado. O uso de bases governamentais depende do canal institucional e do credenciamento descritos em [Integrações cadastrais](docs/integracoes.md). A matriz das 18 partes do documento do cliente está em [Cobertura do produto](docs/gestao-publica/cobertura-produto.md). A operação do piloto e a recuperação de dados estão em [Operação](docs/operacao.md).
