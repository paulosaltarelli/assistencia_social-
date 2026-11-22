# Integrações cadastrais

O PDF do cliente é referência de necessidades. Integrações dependem de documentação e autorização próprias.

## Cadastro Único

Identificar com o gestor municipal do Cadastro Único e a TI o canal institucional autorizado pelo MDS, o instrumento de acesso ou compartilhamento e as operações permitidas. A implementação do conector depende dessas informações. Registrar finalidade, profissional, município, data, origem, resultado e identificador da operação. Minimizar campos armazenados e estabelecer prazo de atualização e retenção.

## CPF Light

Fornecedor e produto ainda precisam ser identificados pelo responsável. Solicitar documentação, condições contratuais, campos retornados, limites e ambiente de teste. Consulta cadastral de CPF auxilia na identificação conforme o serviço contratado. Elegibilidade a benefícios depende de critérios e análise próprios.

## Requisitos técnicos

Executar consultas no backend, guardar credenciais no mecanismo de segredos do ambiente, conceder permissões por profissional e município e registrar auditoria sem copiar o conteúdo cadastral para logs. Implementar timeout, tratamento de indisponibilidade e rastreabilidade da origem dos dados. Validar divergências com a equipe responsável antes de sobrescrever cadastros.

## Referências jurídicas para revisão municipal

Conferir a adoção municipal da Lei 14.129/2021 conforme seu art. 2º, III. Avaliar finalidade e base legal por operação à luz da LGPD, regras do MDS e atos municipais. A revisão dos agentes identificou essas dependências, mas o proxy bloqueou a consulta textual às fontes oficiais nesta sessão. A conferência atualizada permanece pendente.
