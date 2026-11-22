# Base de legislação e gestão pública

## Objetivo e abrangência

Esta base orienta o agente de gestão pública da Vexo na formação, verificação e utilização de um acervo durável de legislação. O objetivo solicitado é reunir o acervo geral integral dos três entes relevantes à implantação inicial, União, Estado de Minas Gerais e Município de Santa Cruz de Minas. A prioridade de coleta e análise é a Assistência Social e o SUAS. Essa prioridade organiza o trabalho e a indexação. O universo pretendido continua abrangendo a legislação geral desses entes, inclusive normas históricas, alteradoras e revogadas, com seu estado identificado.

O acervo deve abranger Constituição Federal, Constituição Estadual, Lei Orgânica municipal, emendas, leis complementares e ordinárias, leis delegadas quando existentes, medidas provisórias federais, decretos, regulamentos e atos normativos infralegais publicados pelas autoridades competentes. Incluir resoluções e deliberações de conselhos, instruções normativas e portarias de conteúdo normativo. Registrar atos orçamentários, financeiros, administrativos, de transparência e proteção de dados. Atos individuais e demais documentos publicados devem ser classificados para permitir verificar o universo de cada diário e justificar o que é material normativo.

Nos demais municípios clientes, criar uma cobertura municipal própria com as mesmas regras de proveniência e verificação. A legislação de Santa Cruz de Minas não deve ser aplicada automaticamente a outro município. As normas federais e estaduais são compartilhadas com controle de jurisdição e de competência.

## Estado real em 22 de novembro de 2026

O arquivo `fontes.csv` é um inventário de canais e normas identificadas para coleta. Ele registra fontes candidatas e o resultado observado das consultas. Este diretório ainda não contém cópias oficiais dos atos, índice textual completo ou evidência de cobertura integral. Nenhuma leitura de texto legal pela rede foi concluída nesta sessão.

O acesso aos portais consultados retornou `403 Forbidden` no túnel do proxy. Foram tentados Prefeitura, ALMG, Diário Oficial de Minas Gerais, SEDESE, Planalto, Diário Oficial da União, MDS, Câmara dos Deputados, Senado e Portal de Legislação da Presidência. A repetição fora do sandbox para ALMG e, em consultas anteriores desta tarefa, Planalto e Câmara também retornou bloqueio. Isso demonstra um bloqueio no caminho de acesso deste ambiente. O resultado não demonstra ausência dos atos nem indisponibilidade dos portais para outros usuários.

As normas federais listadas são âncoras identificadas por referência conhecida. Seus textos, alterações e vigência atuais precisam de conferência documental. As fontes estaduais são candidatas oficiais a consultar. Para Santa Cruz de Minas, o endereço da Prefeitura foi fornecido pelo cliente. Lei Orgânica, atos de organização da assistência social, benefícios, CMAS, FMAS, regulamentação do governo digital e demais atos locais continuam sem inventário validado. Não foram identificados números ou datas de atos municipais nesta coleta.

Os arquivos de PDF fornecidos pelo cliente são referências de produto. Não são fontes de publicação legal nem prova da norma municipal aplicável. A documentação do software, uma página institucional e o resultado de um modelo de linguagem também não substituem o ato oficial.

## Fontes e descoberta

Use `fontes.csv` como ponto de partida e preserve seu histórico de verificação. Uma URL cadastrada pode apontar para um catálogo, portal, diário ou texto de ato. Consulte o campo `tipo_registro` antes de tratá-la como documento normativo. `natureza_url` distingue um texto específico de um canal de descoberta. A existência de um endereço não estabelece que seu conteúdo foi lido.

Para a União, cruzar os textos e históricos do Planalto e da Presidência com a publicação no Diário Oficial da União. Câmara e Senado podem ajudar a localizar texto, alterações e tramitação. Registrar a origem de cada versão. A norma promulgada e o projeto de lei devem ocupar classes distintas no índice.

Para Minas Gerais, descobrir atos e relações de alteração no catálogo da ALMG e verificar a publicação no Diário Oficial estadual. A SEDESE e os canais oficiais do Conselho Estadual de Assistência Social podem apontar para atos setoriais. Confirmar o endereço e a competência do conselho antes de cadastrar documentos como deliberação estadual.

Para Santa Cruz de Minas, começar pelo portal fornecido pelo cliente e localizar os canais oficiais de legislação, transparência, Câmara Municipal e diário usado pelo Município. Se o diário for operado por associação ou fornecedor, registrar a evidência de que ele é o veículo oficial e os períodos em que foi adotado. Confirmar Lei Orgânica, catálogo de leis, decretos, atos da secretaria competente e resoluções do CMAS. Solicitar ao órgão um inventário ou cópia pública dos atos quando a publicação não estiver acessível. Nenhum ato local pode ser deduzido por analogia com outra prefeitura.

Para os três entes, levantar a data inicial de cada catálogo, séries, tipos documentais, intervalos disponíveis e lacunas. Duplicatas entre catálogos devem apontar para a mesma identidade do ato, preservando as diferentes evidências de publicação e consolidação.

## Ordem inicial de trabalho

1. Resolver acesso às fontes e confirmar os canais de publicação. Registrar cobertura por ente, tipo de ato e intervalo temporal.
2. Coletar as normas-âncora federais do inventário, o marco estadual aplicável e os atos municipais ligados à implantação. Conferir alterações, vigência e regulamentação.
3. Expandir incrementalmente para todo o acervo geral dos três entes. Manter fila de períodos históricos, ramos de direito e coleções pendentes, com contagem de itens esperados e verificados quando a fonte permitir.
4. Acompanhar novas edições dos diários e alterações nos catálogos. Reprocessar as referências de atos já indexados e as regras de produto afetadas.

A fila de Assistência Social deve relacionar organização do SUAS, serviços, benefícios, gestão do trabalho, conselhos e fundos, registros técnicos, sigilo, direitos do usuário e financiamento. A fila geral deve incluir os demais ramos e competências, entre eles orçamento, contabilidade, licitações, contratos, pessoal, administração, arquivos, transparência, governo digital, acessibilidade e proteção de dados.

## Registro durável de cada ato e versão

Ao importar um documento, guardar no acervo operacional os seguintes dados e evidências.

- Identidade do ente, órgão e autoridade emitente, tipo, número, data, ementa e identificador interno estável. Registrar os dados desconhecidos como pendentes.
- URL de origem, URL final, natureza da fonte, data e hora da consulta, resultado HTTP, veículo, edição, seção, página e data de publicação quando disponíveis.
- Original obtido, formato, hash SHA-256, tamanho, método de extração, texto extraído e referência à página ou dispositivo. OCR requer sinalização e conferência dos trechos citados.
- Datas de publicação, início e fim de vigência quando expressos, vacatio legis, alcance territorial, matérias, destinatários e condições de aplicabilidade.
- Relações com atos alteradores, regulamentadores, revogadores, retificações e republicações. Guardar os trechos afetados e o intervalo temporal de cada versão.
- Estado de revisão, responsável e data da conferência. Manter vínculo entre o dispositivo, a conclusão jurídica e a regra de software que ele fundamenta.

Uma mudança no arquivo ou hash pode ser uma correção editorial, alteração normativa ou mudança de formato. Requer análise. Preservar a cópia anterior e sua proveniência. Uma cópia que não apresenta assinatura digital pode continuar sendo evidência de publicação no veículo oficial. Registrar o tipo de evidência disponível e conferir assinaturas quando existirem.

## Vigência, publicação e aplicabilidade

Um documento recém-publicado não é automaticamente a versão aplicável ao fato analisado. Antes de recomendar uma ação, conferir o texto vigente na data do fato, alterações, revogações expressas, regras de transição, condições, competência da autoridade e efeitos de decisões que afetem sua aplicação. Revogação tácita, conflito de normas e alcance de decisão judicial exigem análise jurídica identificada. Não marcar esses casos automaticamente como resolvidos.

Guardar o texto original e as versões consolidadas com data de referência. Um ato revogado pode fundamentar fatos ocorridos durante sua vigência. Uma obrigação de âmbito federal pode ter destinatário limitado. Uma norma municipal não substitui exigência nacional de competência aplicável. Verificar a articulação entre os entes e o instrumento local de execução.

A Lei nº 14.129/2021 é uma âncora expressamente solicitada. Seu art. 2º, III exige verificar a adoção por ato normativo próprio para aplicação às administrações estaduais, distrital e municipais. A existência do portal de Santa Cruz de Minas não comprova essa adoção. O teor atual do dispositivo e eventual ato de adesão devem ser obtidos e citados antes de uma conclusão local.

Na LGPD, identificar finalidade, categorias de dados, base legal pertinente, compartilhamentos, atribuições do controlador e do operador e medidas de proteção. A seleção de uma base legal exige examinar a operação concreta. No módulo de benefícios, conferir o art. 22 da LOAS e os atos locais aplicáveis. No módulo financeiro, conferir Lei nº 4.320/1964, LRF e regras de execução do ente. Essas referências iniciais não bastam para declarar conformidade do sistema.

## Coleta incremental e verificações

Guardar um ponto de continuidade por fonte, coleção e período, com última consulta concluída, última edição processada, documentos pendentes e falhas. O importador deve poder retomar e repetir uma coleta sem criar duplicatas. Uma consulta incompleta não avança o marcador de cobertura concluída.

Comparar identificadores de edição, datas e referências dos catálogos com os documentos efetivamente importados. Detectar lacunas de sequência, páginas ausentes, anexos faltantes, texto vazio, redirecionamento para login e páginas de erro com HTTP 200. Validar amostras de extração e todos os dispositivos usados em citações ou regras do produto. Quando a fonte não fornecer um total confiável, registrar essa limitação.

Usar TLS e integridade dos artefatos. Respeitar os termos, limites e canais de obtenção de cada fonte. Registrar indisponibilidade, bloqueio de rede e restrição de acesso com motivos distintos. Não substituir uma fonte bloqueada por texto inventado. Uma cópia pública fornecida pelo órgão pode ser importada com sua origem documentada e verificação de publicação pendente.

O agendamento é uma configuração operacional por fonte. Proposta inicial sujeita à validação é verificar novas publicações em cada dia útil e alterações consolidadas ao menos semanalmente. Antes de implantação, regra de benefício, pagamento ou resposta jurídica relevante, revalidar as normas citadas e registrar a data de corte. A periodicidade de coleta não garante atualização de uma fonte que sofreu falha.

## Instruções de utilização pelo agente

1. Determinar município, estado, assunto, serviço, data do fato e objetivo da consulta. Buscar nos três níveis e nos atos de regulamentação ou execução relacionados.
2. Consultar o estado de cobertura e coleta das fontes. Informar a data de corte e lacunas que possam afetar a resposta.
3. Usar apenas documento efetivamente obtido e dispositivo conferido como fundamento textual. Normas identificadas sem texto obtido são pistas de pesquisa. Explicitar essa condição.
4. Classificar a conclusão como obrigação legal com dispositivo aplicável, regra municipal confirmada, orientação técnica, proposta de produto ou pendência de validação. Recomendações de usabilidade não devem receber uma justificativa legal inventada.
5. Citar ente, órgão, tipo e número do ato, data, artigo ou item, versão e data de referência, publicação e link oficial. Quando houver acervo local, acrescentar o identificador do documento ou hash. Deixar claro quando o link leva a um portal de descoberta em vez do ato.
6. Se a aplicabilidade ou vigência estiver incerta, apresentar a questão concreta para jurídico, gestão municipal, contabilidade ou encarregado, conforme o assunto. Prosseguir com as partes verificadas.
7. Associar propostas de alteração do sistema às regras de negócio afetadas e a critérios de aceite verificáveis. Mudanças em critérios de concessão, acesso a dados e execução financeira exigem validação do responsável municipal antes da configuração operacional.

Formato recomendado para uma resposta jurídica operacional é indicar a pergunta, jurisdição e data, achado sustentado, dispositivos e versão, efeito no processo, proposta de implementação e pendências. Uma busca sem resultado deve ser descrita como busca sem resultado no acervo e intervalo consultados. Não demonstra inexistência de norma.

## Critérios para ampliar a alegação de cobertura

Para cada ente, deve existir inventário de fontes e períodos, relação dos tipos de atos, evidência de coleta dos originais e anexos, índice recuperável, controle de versões, verificação de integridade e relatório das lacunas. Manter o texto das normas históricas com status temporal.

Só declarar uma coleção integralmente coletada quando houver universo de comparação confiável e reconciliação documentada. Informar exatamente ente, fonte, tipo e intervalo cobertos. A expressão geral “toda a legislação na base” depende da conclusão de todas as coleções e da manutenção das publicações posteriores. O estado atual deste projeto é a preparação do inventário e das regras para essa formação.

## Pendências iniciais

- Habilitar o acesso de leitura às fontes oficiais pelos controles de rede do ambiente.
- Confirmar os canais de publicação do Município e seu inventário histórico, além das coleções e períodos do Estado e da União.
- Obter, verificar e indexar os originais e as versões das normas-âncora. As URLs deste inventário ainda não comprovam texto vigente.
- Confirmar atos municipais de benefícios, organização da rede, conselho e fundo, governo digital, proteção de dados e retenção documental.
- Configurar armazenamento, importação, consulta e rastreabilidade operacionais conforme o fluxo mantido pelo agente principal. Este documento especifica os requisitos de conteúdo e uso dessa base.
