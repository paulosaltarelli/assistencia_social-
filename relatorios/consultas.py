"""Consultas municipais com seções limitadas às permissões de cada domínio."""
from datetime import timedelta

from django.db.models import Count, F, Sum, Value
from django.db.models.functions import Coalesce, NullIf, TruncMonth
from django.utils import timezone

from atendimentos.acesso import tem_permissao
from atendimentos.models import Atendimento, Cidadao, Familia
from cadastros.models import ComplementoFamilia, ComplementoPessoa
from programas.models import ConcessaoVale, Material, MovimentoEstoque, PedidoMaterial, SolicitacaoBeneficio

LIMITE_EXPORTACAO = 5000


class RelatorioExtenso(ValueError):
    pass


def tabela(titulo, colunas, linhas):
    return {'titulo': titulo, 'colunas': colunas, 'linhas': list(linhas)}


def periodo(consulta, campo, filtros):
    if filtros.get('inicio'):
        consulta = consulta.filter(**{f'{campo}__gte': filtros['inicio']})
    if filtros.get('fim'):
        consulta = consulta.filter(**{f'{campo}__lte': filtros['fim']})
    return consulta


def mensal(consulta, campo, titulo):
    dados = consulta.order_by().annotate(mes=TruncMonth(campo)).values('mes').annotate(total=Count('pk')).order_by('mes')
    return tabela(titulo, ['Mês', 'Quantidade'], [(item['mes'].strftime('%m/%Y'), item['total']) for item in dados if item['mes']])


def linhas_limitadas(consulta, campos):
    if consulta.count() > LIMITE_EXPORTACAO:
        raise RelatorioExtenso('O relatório excede 5.000 registros identificados. Reduza o período ou filtre o bairro.')
    return consulta.values_list(*campos)


def consultas_sociais(municipio, filtros):
    familias = Familia.objects.filter(municipio=municipio)
    bairro = filtros.get('bairro')
    if bairro:
        familias = familias.filter(pk__in=ComplementoFamilia.objects.filter(
            municipio=municipio, bairro__icontains=bairro).values('familia_id'))
    pessoas = Cidadao.objects.filter(municipio=municipio, familia__in=familias)
    return familias, pessoas


def resumo_inicial(municipio, vinculo):
    """Contagens reaproveitáveis, sem carregar nomes ou valores financeiros."""
    resumo = []
    if tem_permissao(vinculo, 'cadastros.ver'):
        resumo.extend([
            ('Famílias', Familia.objects.filter(municipio=municipio).count()),
            ('Cidadãos', Cidadao.objects.filter(municipio=municipio).count()),
        ])
    if tem_permissao(vinculo, 'atendimentos.ver'):
        atendimentos = Atendimento.objects.filter(municipio=municipio)
        if not tem_permissao(vinculo, 'sigilo.ver'):
            atendimentos = atendimentos.exclude(acompanhamento__sigiloso=True)
        resumo.append(('Atendimentos registrados', atendimentos.count()))
    if tem_permissao(vinculo, 'beneficios.ver'):
        resumo.append(('Benefícios aguardando análise', SolicitacaoBeneficio.objects.filter(
            municipio=municipio, situacao__in=['solicitado', 'analise']).count()))
    if tem_permissao(vinculo, 'vale.ver'):
        resumo.append(('Concessões ativas do Vale-Alimentação', ConcessaoVale.objects.filter(
            municipio=municipio, situacao='ativo').count()))
    return resumo


def relatorio_social(municipio, vinculo, filtros):
    familias, pessoas = consultas_sociais(municipio, filtros)
    tabelas = []
    if tem_permissao(vinculo, 'cadastros.ver'):
        tabelas.append(tabela('Cadastros no bairro selecionado', ['Indicador', 'Quantidade'], [
            ['Famílias cadastradas', familias.count()], ['Cidadãos cadastrados', pessoas.count()],
        ]))
        bairros = familias.order_by().annotate(bairro_relatorio=Coalesce(
            NullIf('complemento__bairro', Value('')), Value('Bairro não informado'))
        ).values('bairro_relatorio').annotate(total=Count('pk')).order_by('bairro_relatorio')
        tabelas.append(tabela('Famílias por bairro', ['Bairro', 'Famílias'], bairros.values_list('bairro_relatorio', 'total')))
        if filtros.get('nominal'):
            dados = pessoas.order_by('nome', 'id')
            tabelas.append(tabela('Cadastro nominal', ['Identificador', 'Nome', 'Família'],
                                  linhas_limitadas(dados, ['id', 'nome', 'familia__referencia'])))
    if tem_permissao(vinculo, 'atendimentos.ver'):
        atendimentos = Atendimento.objects.filter(municipio=municipio)
        if filtros.get('bairro'):
            atendimentos = atendimentos.filter(cidadao__in=pessoas)
        if not tem_permissao(vinculo, 'sigilo.ver'):
            atendimentos = atendimentos.exclude(acompanhamento__sigiloso=True)
        atendimentos = atendimentos.annotate(data_relatorio=Coalesce('acompanhamento__data_efetiva', 'criado'))
        atendimentos = periodo(atendimentos, 'data_relatorio__date', filtros)
        tabelas.append(mensal(atendimentos, 'data_relatorio', 'Atendimentos por mês — data efetiva ou registro legado'))
        tabelas.append(tabela('Atendimentos por bairro', ['Bairro', 'Atendimentos'], atendimentos_por_bairro(atendimentos)))
        if filtros.get('nominal'):
            tabelas.append(tabela('Atendimentos identificados', ['Pessoa', 'Data efetiva ou registro legado', 'Unidade'],
                                  linhas_limitadas(atendimentos.order_by('criado', 'id'), ['cidadao__nome', 'data_relatorio', 'unidade'])))
    if tem_permissao(vinculo, 'beneficios.ver'):
        base_beneficios = SolicitacaoBeneficio.objects.filter(municipio=municipio, familia__in=familias)
        if filtros.get('modalidade'):
            base_beneficios = base_beneficios.filter(tipo=filtros['modalidade'])
        beneficios = periodo(base_beneficios, 'solicitado_em', filtros)
        dados = beneficios.order_by().values('tipo__nome', 'situacao').annotate(total=Count('pk')).order_by('tipo__nome', 'situacao')
        rotulos = dict(SolicitacaoBeneficio.SITUACOES)
        tabelas.append(tabela('Benefícios por modalidade e situação', ['Modalidade', 'Situação', 'Quantidade'], [
            [item['tipo__nome'], rotulos.get(item['situacao'], item['situacao']), item['total']] for item in dados
        ]))
        tabelas.append(mensal(beneficios, 'solicitado_em', 'Benefícios solicitados por mês'))
        concedidos = periodo(base_beneficios.filter(concedido_em__isnull=False), 'concedido_em__date', filtros)
        tabelas.append(mensal(concedidos, 'concedido_em', 'Concessões de benefícios por mês'))
        if filtros.get('nominal'):
            tabelas.append(tabela('Solicitações de benefícios identificadas', ['Família', 'Modalidade', 'Solicitação', 'Situação'],
                                  linhas_limitadas(beneficios.order_by('solicitado_em', 'id'), ['familia__referencia', 'tipo__nome', 'solicitado_em', 'situacao'])))
    if tem_permissao(vinculo, 'materiais.ver'):
        pedidos = periodo(PedidoMaterial.objects.filter(municipio=municipio, familia__in=familias), 'solicitado_em', filtros)
        if filtros.get('material'):
            pedidos = pedidos.filter(material=filtros['material'])
        dados = pedidos.order_by().values('material__nome', 'material__unidade').annotate(
            pedidos=Count('pk'), solicitado=Sum('quantidade_solicitada'), entregue=Sum('entregue')).order_by('material__nome')
        tabelas.append(tabela('Materiais solicitados e entregues', ['Material', 'Unidade', 'Pedidos', 'Solicitado', 'Entregue acumulado'], [
            [item['material__nome'], item['material__unidade'], item['pedidos'], item['solicitado'], item['entregue']] for item in dados
        ]))
        movimentos = periodo(MovimentoEstoque.objects.filter(municipio=municipio, tipo='saida', pedido__familia__in=familias), 'criado_em__date', filtros)
        if filtros.get('material'):
            movimentos = movimentos.filter(material=filtros['material'])
        tabelas.append(mensal(movimentos, 'criado_em', 'Movimentações de entrega por mês'))
        entregas = movimentos.order_by().annotate(mes=TruncMonth('criado_em')).values(
            'mes', 'material__nome', 'material__unidade').annotate(quantidade=Sum('quantidade')).order_by('mes', 'material__nome')
        tabelas.append(tabela('Quantidades entregues por mês e material', ['Mês', 'Material', 'Unidade', 'Quantidade'], [
            [item['mes'].strftime('%m/%Y'), item['material__nome'], item['material__unidade'], item['quantidade']]
            for item in entregas
        ]))
    if tem_permissao(vinculo, 'vale.ver'):
        vales = ConcessaoVale.objects.filter(municipio=municipio, familia__in=familias)
        if filtros.get('situacao_vale'):
            vales = vales.filter(situacao=filtros['situacao_vale'])
        por_situacao = vales.order_by().values('situacao').annotate(total=Count('pk')).order_by('situacao')
        rotulos_vale = dict(ConcessaoVale.SITUACOES)
        tabelas.append(tabela('Vale-Alimentação por situação', ['Situação', 'Concessões'], [
            [rotulos_vale[item['situacao']], item['total']] for item in por_situacao
        ]))
        por_bairro = vales.order_by().values('familia__complemento__bairro', 'situacao').annotate(total=Count('pk')).order_by('familia__complemento__bairro', 'situacao')
        tabelas.append(tabela('Vale-Alimentação por bairro e situação', ['Bairro', 'Situação', 'Concessões'], [
            [item['familia__complemento__bairro'] or 'Bairro não informado', rotulos_vale[item['situacao']], item['total']] for item in por_bairro
        ]))
        tabelas.append(tabela('Vale-Alimentação na data da consulta', ['Indicador', 'Quantidade'], [
            ['Concessões ativas', vales.filter(situacao='ativo').count()],
            ['Beneficiários distintos ativos', vales.filter(situacao='ativo').values('cidadao_id').distinct().count()],
        ]))
        inclusoes = periodo(vales.filter(incluido_em__isnull=False), 'incluido_em__date', filtros)
        tabelas.append(mensal(inclusoes, 'incluido_em', 'Inclusões de Vale-Alimentação por mês'))
        if filtros.get('nominal'):
            tabelas.append(tabela('Concessões de vale identificadas', ['Pessoa', 'Situação', 'Periodicidade'],
                                  linhas_limitadas(vales.order_by('id'), ['cidadao__nome', 'situacao', 'periodicidade'])))
    return tabelas


def alertas_sociais(municipio, vinculo):
    alertas = []
    if tem_permissao(vinculo, 'beneficios.ver'):
        dados = SolicitacaoBeneficio.objects.filter(municipio=municipio)
        alertas.extend([
            ('Benefícios aguardando análise', dados.filter(situacao__in=['solicitado', 'analise']).count(), 'programas:beneficios'),
            ('Benefícios aprovados sem entrega', dados.filter(situacao__in=['aprovado', 'parcial'], entregue_em__isnull=True).count(), 'programas:beneficios'),
        ])
    if tem_permissao(vinculo, 'materiais.ver'):
        pedidos = PedidoMaterial.objects.filter(municipio=municipio)
        alertas.extend([
            ('Pedidos de material aguardando análise', pedidos.filter(situacao__in=['solicitado', 'analise']).count(), 'programas:pedidos'),
            ('Entregas de material pendentes', pedidos.filter(situacao__in=['aprovado', 'parcial', 'disponibilidade'], entregue__lt=F('quantidade_aprovada')).count(), 'programas:pedidos'),
            ('Materiais no limite mínimo ou sem saldo', Material.objects.filter(municipio=municipio, saldo__lte=F('estoque_minimo')).count(), 'programas:estoque'),
        ])
    if tem_permissao(vinculo, 'vale.ver'):
        alertas.append(('Vale-Alimentação aguardando análise', ConcessaoVale.objects.filter(municipio=municipio, situacao='analise').count(), 'programas:vales'))
    if tem_permissao(vinculo, 'cadastros.ver'):
        corte = timezone.now() - timedelta(days=730)
        familias = Familia.objects.filter(municipio=municipio)
        pessoas = Cidadao.objects.filter(municipio=municipio)
        atualizadas_familias = ComplementoFamilia.objects.filter(municipio=municipio, atualizado__gte=corte).values('familia_id')
        atualizadas_pessoas = ComplementoPessoa.objects.filter(municipio=municipio, atualizado__gte=corte).values('cidadao_id')
        alertas.extend([
            ('Famílias sem complemento ou sem atualização há 730 dias', familias.exclude(pk__in=atualizadas_familias).count(), 'cadastros:familias'),
            ('Cidadãos sem complemento ou sem atualização há 730 dias', pessoas.exclude(pk__in=atualizadas_pessoas).count(), 'cadastros:inicio'),
        ])
    return alertas



def atendimentos_por_bairro(consulta):
    dados = consulta.order_by().annotate(bairro_relatorio=Coalesce(
        NullIf('cidadao__familia__complemento__bairro', Value('')), Value('Bairro não informado'))
    ).values('bairro_relatorio').annotate(total=Count('pk')).order_by('bairro_relatorio')
    return list(dados.values_list('bairro_relatorio', 'total'))


def series_resumidas(municipio, vinculo, meses=6):
    """Seis gráficos da página inicial, condicionados aos direitos do domínio.

    Cada item contém titulo, linhas [(rótulo, valor)], maximo, unidade e descricao.
    Séries mensais incluem o mês atual parcial e meses vazios com zero.
    """
    from datetime import date
    hoje = timezone.localdate()
    meses = max(1, min(meses, 12))
    referencia = hoje.year * 12 + hoje.month - 1
    inicios = [date(indice // 12, indice % 12 + 1, 1)
               for indice in range(referencia - meses + 1, referencia + 1)]
    filtros = {'inicio': inicios[0], 'fim': hoje}
    descricao_periodo = f"De {inicios[0]:%d/%m/%Y} a {hoje:%d/%m/%Y}."
    series = []

    def incluir(titulo, linhas, unidade, descricao=descricao_periodo):
        series.append({'titulo': titulo, 'linhas': linhas, 'unidade': unidade, 'descricao': descricao,
                       'maximo': max([linha[1] for linha in linhas], default=1) or 1})

    if tem_permissao(vinculo, 'atendimentos.ver'):
        atendimentos = Atendimento.objects.filter(municipio=municipio)
        if not tem_permissao(vinculo, 'sigilo.ver'):
            atendimentos = atendimentos.exclude(acompanhamento__sigiloso=True)
        atendimentos = atendimentos.annotate(data_relatorio=Coalesce('acompanhamento__data_efetiva', 'criado'))
        atendimentos = periodo(atendimentos, 'data_relatorio__date', filtros)
        contagens = dict(mensal(atendimentos, 'data_relatorio', '')['linhas'])
        incluir('Atendimentos por mês', [(data.strftime('%m/%Y'), contagens.get(data.strftime('%m/%Y'), 0))
                                        for data in inicios], 'atendimentos',
                descricao_periodo + ' Data efetiva cadastrada ou data de registro nos casos anteriores.')
        incluir('Distribuição territorial dos atendimentos', atendimentos_por_bairro(atendimentos), 'atendimentos por bairro')
    if tem_permissao(vinculo, 'beneficios.ver'):
        concedidos = periodo(SolicitacaoBeneficio.objects.filter(municipio=municipio, concedido_em__isnull=False),
                             'concedido_em__date', filtros)
        modalidades = concedidos.order_by().values('tipo__nome').annotate(total=Count('pk')).order_by('tipo__nome')
        incluir('Benefícios concedidos por modalidade', list(modalidades.values_list('tipo__nome', 'total')), 'concessões')
    solicitacoes = {}
    possui_solicitacoes = False
    for modelo, permissao in [(SolicitacaoBeneficio, 'beneficios.ver'), (PedidoMaterial, 'materiais.ver'), (ConcessaoVale, 'vale.ver')]:
        if tem_permissao(vinculo, permissao):
            possui_solicitacoes = True
            consulta = periodo(modelo.objects.filter(municipio=municipio), 'solicitado_em', filtros)
            for rotulo, valor in mensal(consulta, 'solicitado_em', '')['linhas']:
                solicitacoes[rotulo] = solicitacoes.get(rotulo, 0) + valor
    if possui_solicitacoes:
        incluir('Evolução das solicitações', [(data.strftime('%m/%Y'), solicitacoes.get(data.strftime('%m/%Y'), 0))
                                             for data in inicios], 'solicitações',
                descricao_periodo + ' Soma de benefícios, materiais e vale dos módulos autorizados à conta.')
    if tem_permissao(vinculo, 'vale.ver'):
        vales = ConcessaoVale.objects.filter(municipio=municipio, situacao='ativo').order_by().annotate(
            bairro_relatorio=Coalesce(NullIf('familia__complemento__bairro', Value('')), Value('Bairro não informado'))
        ).values('bairro_relatorio').annotate(total=Count('cidadao_id', distinct=True)).order_by('bairro_relatorio')
        incluir('Beneficiários do Vale-Alimentação por bairro', list(vales.values_list('bairro_relatorio', 'total')),
                'pessoas ativas', f'Situação atual em {hoje:%d/%m/%Y}. Cada pessoa ativa é contada uma vez no bairro.')
    if tem_permissao(vinculo, 'financeiro.ver'):
        from financeiro.consultas import execucao_por_grupo
        despesas = execucao_por_grupo(municipio, {'ano': hoje.year, 'mes': hoje.month}, 'programa')
        incluir('Despesas pagas por programa', [(item['rotulo'], item['pagamento']) for item in despesas], 'R$ pagos',
                f'Exercício {hoje.year}, acumulado até o mês {hoje.month:02d}. Estágio de pagamento efetivo.')
    return series
