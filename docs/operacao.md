# Implantação por IP

Projeto social-prefeituras em /opt/social-prefeituras; aplicação em 127.0.0.1:18081 e PostgreSQL apenas na rede do projeto. A proposta de entrada é HTTPS em 2.25.146.67:8447. Exige certificado exclusivo confiável com o IP no campo subjectAltName e renovação automatizada. Verificar o desafio de emissão antes de modificar Apache. Solicitar aprovação específica para liberar TCP 8447 e revisar o novo arquivo infra/social-prefeituras.conf. Conferir os módulos SSL, headers, proxy e proxy_http. Criar somente o virtual host dedicado, testar apache2ctl configtest e obter autorização para reload.

## Sequência de publicação

1. Registrar baseline dos serviços existentes, portas, espaço, volumes e respostas HTTPS. Conferir o certificado e a rota do firewall da Hostinger. Reservar diretório, rede, volume e nomes exclusivos. Instalar somente a versão revisada e gerar os segredos no destino.
2. Executar Compose com -p social-prefeituras -f compose.yaml -f compose.prod.yaml. Construir imagens, registrar os IDs e iniciar só social-db.
3. Fazer backup custom com pg_dump -Fc, criptografar por streaming com GPG para a chave de recuperação do responsável e enviar para armazenamento externo. Guardar data, versão e checksum do arquivo cifrado. Proteger a chave de recuperação separadamente.
4. Em banco isolado com a role social_app disponível, decifrar para pg_restore --exit-on-error. Conferir esquema e contagens contra a origem. Revisar migrate --plan e aguardar autorização. Na primeira implantação, as migrations criam novas tabelas, índices e políticas no banco exclusivo. Nas seguintes, avaliar locks e reversibilidade de cada mudança.
5. Executar infra/migrate.sh passando a credencial administrativa apenas ao job descartável e iniciar social-web. Validar saúde, login e isolamento. Provisionar contas nominais por canal seguro.
6. Após aprovações, ativar o proxy e testar HTTPS, certificado, login, dados por município, logs e portas dos demais sistemas. Limitar e rotacionar logs e inspecionar uso de disco. Definir frequência de backup e retenção com o controlador municipal.

## Reversão

Desabilitar somente a entrada do projeto após aprovação do diff e reload. Restaurar a imagem anterior registrada se o esquema for compatível. Para reversão de dados, interromper escritas somente no sistema social, restaurar o backup em volume novo, verificar integridade e obter autorização antes da troca. Preservar o volume anterior e os registros posteriores para reconciliação.
