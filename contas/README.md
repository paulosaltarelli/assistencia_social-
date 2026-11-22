# Contas, identidade municipal e contrato de autorização

O app deve ser registrado como `contas.apps.ContasConfig` e incluído com `path("contas/", include("contas.urls"))`. `LOGIN_URL` deve apontar para `contas:entrar` e o login antigo deve redirecionar para esse fluxo para preservar o contador persistente e a auditoria de autenticação. As telas autenticadas estendem `app_shell.html`, bloco `conteudo`.

## Contrato aos módulos

`from atendimentos.acesso import municipal, tem_permissao, registrar_evento`.

`@municipal("cadastros.ver", post="cadastros.editar")` exige usuário autenticado e vínculo ativo. O contexto RLS deriva exclusivamente desse vínculo e fica limitado à transação. A view recebe `request.municipio` e `request.vinculo`. Use filtros de município também nas consultas de relações. `registrar_evento(request, "cadastro_criado", objeto)` recebe modelo com PK UUID, UUID ou string de UUID. PKs incompatíveis geram erro explícito. Eventos sem objeto usam `None` intencionalmente.

Os códigos e a matriz explícita ficam em `permissoes.py`. Administrador administra contas e identidade. Conteúdo financeiro e sigiloso exige acesso próprio. O painel inicial usa `painel.ver` para todos os perfis reconhecidos. `gestao.ver` exige perfil Gestor e concessão individual expressa. A autorização de parecer `beneficios.tecnico` também depende de `sigilo.ver`; alterações de conteúdo protegido devem verificar `sigilo.editar`. Documentos combinam sua permissão com a permissão do alvo.

Ajustes por profissional podem conceder ou retirar ações individuais. Os poderes `contas.conceder_financeiro`, `contas.conceder_sigilo` e `contas.conceder_gestao` exigem procedimento operacional explícito e não podem ser atribuídos no formulário. O administrador não altera suas próprias permissões. Designar um perfil que traz acesso protegido também passa pela validação de concessão.

## Habilitação operacional do piloto

Após aprovação municipal e confirmação do vínculo correto, execute com a credencial administrativa do banco em job descartável:

```
python manage.py habilitar_acesso --usuario gestor.vexo --municipio-id ID_CONFIRMADO --conceder gestao.ver --confirmar-autorizacao --confirmar-piloto
```

Para habilitar ações adicionais de homologação, repita `--conceder CODIGO` para cada ação aprovada. Por exemplo, `--conceder cadastros.editar --conceder atendimentos.editar --conceder contas.gerir --conceder configuracao.editar`. Concessões financeiras, sigilosas, de delegação ou exportação devem ser especificadas individualmente. O comando preserva a senha existente e não altera a identidade do município. Os valores oficiais da Secretaria e o brasão ficam em branco até confirmação.

## Recuperação e sessão

O responsável emite link pessoal de uso único, com uma hora de validade, para entrega direta por canal oficial após confirmar a identidade. O profissional define a própria senha. O segredo é guardado como HMAC no banco. O navegador recebe o comprovante em fragmento `#`, remove o fragmento do histórico e envia o valor por POST, protegido por CSRF. Respostas têm `never_cache`, e campos sensíveis ficam ocultos dos relatórios de exceção do Django. Nenhum envio usa o backend de console.

SMTP é opcional. Para habilitar a recuperação automática configure `CONTAS_SMTP_ATIVO = True` no settings, `EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, TLS apropriado e `DEFAULT_FROM_EMAIL`. O responsável deve confirmar que cada e-mail pertence ao profissional antes de usar esse canal. Sem SMTP real, a recuperação pública orienta procurar o responsável e preserva links manuais já emitidos. A resposta pública é uniforme para evitar confirmação da existência de contas.

Troca de senha, redefinição, alteração administrativa e desativação revogam as sessões do profissional. A troca autenticada mantém a sessão atual com a chave renovada. O limite de login persiste em PostgreSQL, permite oito tentativas por identificador em quinze minutos, e é zerado após login válido. O contador usa somente HMAC do identificador. Requer política de operação para tentativas dirigidas a uma conta e monitoramento dos eventos. Agende `python manage.py manutencao_contas` para eliminar sessões expiradas e contadores vencidos. Eventos de auditoria são preservados até que o município defina retenção.

## Banco e upload

As migrations incluem perfis legados, tabelas municipais com RLS, privilégios mínimos usados pelos fluxos de conta e função restrita para resolver um comprovante de recuperação válido antes de estabelecer o contexto municipal. Execute migrations com a conta administrativa, separada da execução da aplicação. Os eventos de autenticação e contadores precisam aceitar registros antes do login; a conta da aplicação só insere eventos e lê seu ID para `RETURNING`.

O brasão exige Pillow. Aceita PNG/JPEG até 1 MB e 2048 pixels por lado, verifica e reencoda como PNG removendo metadados. O conteúdo fica no banco municipal e é servido apenas a usuários autenticados do município com `nosniff`. Arquivos SVG e outros formatos são recusados.

## Testes

`python manage.py test contas` verifica perfis, concessão explícita do gestor, bloqueio de autoelevação e de concessões protegidas, criação nominal por link, isolamento entre municípios, desativação, troca e redefinição de senha, revogação e limitação persistente. Os testes de banco executam fluxos com `SET ROLE social_app`, portanto a configuração de testes precisa usar PostgreSQL administrativo para criar o banco e aplicar migrations, com o papel `social_app` já provisionado no cluster de testes.
