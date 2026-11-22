# Operação da homologação de Santa Cruz de Minas

O projeto Compose `social-prefeituras` tem banco PostgreSQL, usuário de aplicação `social_app`, volume, redes, backup, chaves e certificado próprios. O Apache encaminha `https://2.25.146.67:8447` para `127.0.0.1:18081`. As versões ficam em `/opt/social-prefeituras/releases/`. O `.env` original é privado. O arquivo `/var/lib/social-prefeituras/piloto.env` mantém a configuração e a chave estável do índice de documentos fora do checkout e da imagem. Use os três arquivos Compose da versão, `.env` e `piloto.env` explicitamente. A imagem publicada é identificada pela revisão Git.

## Publicação

1. Registre em modo de leitura a saúde do app atual e dos pontos públicos do Vendra, Vale Expresso e Minasul. Confira a disponibilidade de RAM e disco no host. O web tem limite de 384 MiB. O scanner tem limite de 2 GiB e 0,45 CPU e usa uma rede dedicada. O PostgreSQL fica na rede privada do projeto.
2. Construa as imagens na nuvem de desenvolvimento usando um checkout limpo. O Dockerfile só copia arquivos de aplicação e o script de migração. Compare o SHA-256 do conteúdo da aplicação na origem e após a transferência. Registre a revisão e preserve uma imagem anterior verificada para reversão.
3. Faça `pg_dump -Fc` do banco `social`, criptografando por streaming com GPG AES-256. A chave de recuperação fica separada das imagens, com acesso administrativo. Restaure com `pg_restore --exit-on-error` em outro banco exclusivo desta aplicação. Compare esquema e contagens de contas, vínculos, cadastros e auditoria, ensaie as migrações e apresente o plano para autorização do responsável antes de migrar o banco publicado.
4. Com a autorização, execute o job de migração e confira as permissões e migrações pendentes. Mantenha a credencial administrativa apenas no job transitório. Verifique o scanner, habilite as permissões aprovadas para o piloto e execute a carga fictícia com `social_app`. Verifique a segunda execução sem duplicações.
5. Troque somente `social-web` com `docker compose ... up -d --no-deps --no-build social-web`. Verifique `/health/`, login em HTTPS com origem do navegador, totais, documentos, filtros, exportações e saúde dos demais serviços. A publicação da aplicação usa o virtual host e a porta existentes. Uma revisão do Apache com novo diff exige autorização expressa.

O certificado para o IP e sua conta ACME ficam em `/var/lib/social-prefeituras/tls/`. O agendamento de renovação exclusivo fica em `/etc/cron.d/social-prefeituras-certificado`. Verifique o serial servido e a validade com `openssl s_client` e `openssl x509`. A renovação deve continuar pelo procedimento revisado do projeto.

## Backup e reversão

`infra/backup-social.sh` faz backup diário cifrado, valida a leitura do catálogo e gera um SHA-256. A agenda de baixa prioridade está em `infra/social-prefeituras-backup.cron`. As cópias diárias da homologação ficam em `/var/backups/social-prefeituras/diarios/`, com retenção de 15 dias e reserva mínima de 10 GiB de disco livre. Os backups manuais pré-migração ficam fora dessa rotação. A recuperação completa é ensaiada antes de cada publicação com mudança de banco. Para uso com dados reais, contratar e testar armazenamento externo durável e custódia da chave de recuperação.

Na reversão de uma versão compatível com o esquema, aponte `SOCIAL_WEB_IMAGE` para a imagem anterior verificada e recrie somente o contêiner web do projeto. Se houver incompatibilidade, preserve a base atual e restaure a cópia cifrada em outro banco. Valide integridade, reconcilie as escritas posteriores e obtenha autorização antes de trocar a conexão. A credencial de aplicação permite selecionar o banco com `SOCIAL_DB_NAME` no serviço.

## Privacidade e incidentes

O ambiente público identificado como homologação utiliza dados fictícios. O controlador municipal define base legal e prazos para cada classe de documento, registro e backup antes de inserir dados de cidadãos. A equipe de TI registra o incidente e preserva as trilhas de acesso, revoga o acesso afetado e aciona o encarregado. O encarregado avalia alcance, risco e comunicação aplicável com a assessoria jurídica. Descartes de acervos dependem de autorização e tabela de temporalidade. O sistema preserva versões, responsáveis e histórico de conferência.
