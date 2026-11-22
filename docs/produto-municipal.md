# Gestão Social Municipal

**Proposta de produto da Vexo · Município piloto informado pelo cliente: Santa Cruz de Minas, MG.** Diagnóstico de 22 de novembro de 2026 sobre a homologação no commit f1277cb. Os testes funcionais usaram duas prefeituras fictícias na nuvem. A aplicação e o painel da VPS tinham os mesmos arquivos de código inspecionados. A experiência de servidores municipais ainda precisa ser observada no piloto.

## O que a avaliação encontrou

Em um teste de recepção, cadastrar uma família voltou ao formulário limpo. Procurar a mesma referência antes do primeiro atendimento devolveu “Nenhum atendimento encontrado” e sugeriu cadastrar outra família. No atendimento, duas pessoas homônimas de famílias diferentes apareceram como opções idênticas. A equipe precisa poder encontrar, confirmar e retomar o cadastro antes de criar qualquer registro.

Na amostra com 51 atendimentos, o histórico exibiu 50 e ofereceu zero controles para avançar. Um atendimento salvo apareceu em uma linha sem ação para registrar retorno. O painel distingue volume de registros por município, mas o modelo original só guarda a data de digitação, a unidade em texto e o encaminhamento em texto. A coordenação precisa saber quem assumiu uma providência, para quando e com qual desfecho.

Em 390 × 844 px, a página coube na largura. O campo de busca começou a 931 px do topo, abaixo da primeira tela, e o nome do profissional ficou oculto. No formulário havia texto auxiliar sem o identificador indicado pelo leitor de tela. O smoke test versionado parou na linha 35 após a separação de páginas, pois ainda procurava um seletor de família na tela inicial.

Uma inspeção de metadados encontrou material privado de emissão e de TLS dentro da imagem web em execução. O processo da aplicação tinha permissão de leitura. A inspeção não mediu uso por terceiros. A correção prioritária é construir a partir de fontes limpas, isolar emissão e renovação, substituir as chaves e verificar as imagens de publicação e reversão.

## Acolhimento pelo CPF

A entrada principal proposta é **Localizar pessoa**. O profissional registra a finalidade da consulta, informa o CPF e recebe o registro municipal autorizado ou inicia uma consulta à fonte oficial habilitada para aquele órgão. O sistema mostra quais campos foram retornados, origem e data. A equipe confirma a identidade, resolve divergências e completa somente as informações necessárias ao serviço.

| Situação | Comportamento do produto |
|---|---|
| Já há registro municipal | Abrir a ficha por identificador interno, com família, atendimento anterior e pendências autorizadas. |
| Primeira passagem com fonte habilitada | Consultar no servidor, apresentar prévia mínima e vincular a pessoa após confirmação. Registrar quem consultou, finalidade, fonte e resultado técnico. |
| CadÚnico disponível institucionalmente | Consultar os atributos autorizados para a finalidade específica. Distinguir informação federal, declaração da família e registro municipal. |
| Fonte indisponível ou pessoa sem CPF | Acolher com cadastro mínimo e criar pendência de conferência. Vincular o registro depois com revisão humana e preservação do histórico. |
| Homônimo ou dados divergentes | Mostrar contexto mínimo para distinguir pessoas. Solicitar revisão antes de vincular ou alterar o cadastro. |

O CPF é um identificador para consulta restrita. Para acesso do cidadão ao próprio histórico, usar autenticação apropriada. Códigos internos nas URLs, dados pessoais mascarados na lista e credenciais de integração por prefeitura reduzem a exposição. A resposta de uma fonte é um insumo para o atendimento. A decisão sobre uma concessão cabe ao responsável autorizado.

Para Santa Cruz de Minas, a disponibilidade de API e a autorização para uso ainda precisam de confirmação institucional. Acesso de um servidor ao sistema do CadÚnico e uma integração para uso pela Vexo têm requisitos próprios. O nome comercial ou técnico “CPF Light” exige identificação do serviço e contrato antes de homologar o conector.

## Escopo funcional mínimo do cliente

| Área do documento | Fluxos que precisam funcionar de ponta a ponta |
|---|---|
| Identidade, login e painel | Identificação configurável da secretaria, contas nominais, recuperação, perfis por função, indicadores com origem e filtros. |
| Pessoas, famílias e consulta integrada | Busca por CPF, NIS, nome, família ou bairro conforme atribuição, ficha, composição, edição, renda, território, histórico e separação de registros técnicos. |
| Benefícios eventuais | Modalidade e critério local, solicitação, análise, decisão integral/parcial ou indeferimento, entrega, anexos, motivo protegido e histórico. |
| Materiais | Pedido, análise, aprovação, entrada, saldo, entrega e recibo. Duas entregas concorrentes respeitam o saldo disponível. |
| Vale-Alimentação | Titular, valor, vigência, periodicidade, inclusão, suspensão, desligamento e histórico consultável na ficha. |
| Financeiro | Exercício, fonte, fundo, programa, dotação e alterações, receitas previstas/recebidas, compromissos, empenho, liquidação e pagamento, incluindo operações parciais e conciliação. |
| Gestor, documentos e contas | Autorização específica, conferência de despesas, notas PDF/XML/imagem, alerta de duplicidade, versões, histórico e dossiê por período com índice e originais. |
| Relatórios, alertas, auditoria e operação | Relatórios sociais e financeiros, PDF/planilha, pendências, prazos, exportações auditadas, backup recuperável, controles por município e testes entre os módulos. |

Exemplo fictício para validar o financeiro com a contabilidade: com dotação de R$ 10.000, recebimento de R$ 7.000, empenho de R$ 1.000, liquidação de R$ 600 e pagamento de R$ 400, o saldo orçamentário é R$ 9.000, o financeiro é R$ 6.600 e restam R$ 200 liquidados a pagar, se não houver outros movimentos. Anexar a nota fiscal ao processo deve preservar esses valores. Conferir sempre com a fonte contábil oficial da prefeitura.

## Diferenciais para outras prefeituras

| Recurso proposto | Uso e benefício verificável | Como demonstrar no piloto |
|---|---|---|
| Agenda, fila e distribuição por unidade | Recepção acolhe, agenda e encaminha à equipe com capacidade. Coordenação identifica demandas sem responsável. | Medir espera até o primeiro atendimento e localizar demanda que ficou sem atribuição. |
| Plano de acompanhamento familiar | Técnica pactua objetivos, agenda revisão e mantém continuidade quando muda o profissional de referência. | Outro profissional autorizado recupera objetivo e próxima ação sem redigitar o histórico. |
| Encaminhamento com confirmação e retorno | A rede confirma recebimento, registra devolutiva e permite à equipe fechar ou reabrir a providência. | Acompanhar um caso da origem ao retorno. Medir proporção com devolutiva e tempo de resposta. |
| Qualidade cadastral e revisão de vínculos | Localizar homônimos, detectar possíveis duplicidades e registrar supervisão com possibilidade de correção. | Distinguir duas pessoas com o mesmo nome e revisar um vínculo preservando autoria e histórico. |
| Portal e atendimento assistido pelo mesmo protocolo | Cidadão acompanha as etapas publicáveis, presta informação pendente e mantém atendimento presencial quando precisar. | Iniciar solicitação no balcão e consultar seu estado pelo canal autenticado sem expor o prontuário técnico. |
| Regras municipais com vigência e revisão | Cada prefeitura mantém catálogo, norma, critério e responsável. A decisão guarda a regra que valia no dia. | Atualizar a regra do município A, reabrir decisão histórica e conferir que B manteve sua regra. |
| Visitas e busca ativa territorial | Equipe organiza roteiro, agenda e retorno. A operação offline é opcional e exige dispositivo protegido, expiração e sincronização controlada. | Simular interrupção de rede e retorno do dispositivo sem perda ou duplicação da visita. |
| Implantação assistida e portabilidade | Importar legado com prévia de divergências, mapear unidades, treinar por função e devolver dados e documentos ao contratante. | Restaurar somente o município A em ambiente vazio e reconciliar vínculos, anexos e saldos. |

## Produto replicável e critérios de adoção

A Vexo mantém uma versão do produto. Cada município configura identidade, unidades, profissionais, atribuições, fontes de recurso, programas, vigências, canais de integração e retenção. Suporte técnico e administração municipal têm acesso compatível com suas atribuições. Todas as consultas, filas de processamento, arquivos e exportações precisam preservar a separação municipal.

A venda deve demonstrar uma história fictícia completa. Recepção identifica a pessoa, técnica acompanha uma providência, gestor confere a entrega e a despesa, e controle interno recupera a documentação que sustentou a decisão. Na homologação com duas prefeituras, validar que alterações de regra, privilégios, relatórios e arquivos de uma só aparecem para a equipe autorizada.

Prioridades de implantação: primeiro a acolhida e o acompanhamento com segurança. Depois benefícios, estoque e Vale-Alimentação com regras locais aprovadas. Em seguida execução financeira, documentação e prestação de contas conciliadas. Integrações externas entram quando houver canal autorizado e homologado. As funcionalidades novas acima podem ser implantadas por módulo, mantendo o escopo mínimo acordado.

Medir no piloto a proporção de campos redigitados após consulta oficial, o tempo até localizar a família correta, os encaminhamentos com retorno registrado, a conciliação de saldos, a recuperação de uma cópia de segurança e a navegação acessível por teclado e celular. Pactuar a linha de base e as metas com a equipe municipal antes de atribuir ganhos ao produto.

## Gestão pública e fontes

A Lei 14.129/2021, art. 2º, III, relaciona sua aplicação pelos municípios à adoção por ato próprio. Benefícios eventuais dependem de critérios locais no marco do art. 22 da LOAS. Para integrações, a prefeitura deve documentar finalidade, base legal, atribuições, dados mínimos e regras de compartilhamento e retenção. O financeiro deve respeitar as etapas da despesa e a conciliação com a contabilidade oficial.

O portal da prefeitura foi indicado pelo cliente. A rede do ambiente retornou 403 ao consultá-lo e a outras fontes oficiais. O nome das unidades, a identidade institucional autorizada, os atos locais, o acesso federal e a vigência dos textos precisam de confirmação. A base do agente prevê inventários por União, Minas Gerais e Santa Cruz de Minas, íntegra versionada, fonte, data de coleta, citação e indicação de lacunas.

Referências para conferência: [Prefeitura de Santa Cruz de Minas](https://www.santacruzdeminas.mg.gov.br/), [Lei de Governo Digital](https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14129.htm), [LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), [LOAS](https://www.planalto.gov.br/ccivil_03/leis/l8742.htm), [Lei 4.320/1964](https://www.planalto.gov.br/ccivil_03/leis/l4320.htm), [Cadastro Único](https://www.gov.br/mds/pt-br/acoes-e-programas/cadastro-unico) e [Conecta gov.br](https://www.gov.br/conecta).
