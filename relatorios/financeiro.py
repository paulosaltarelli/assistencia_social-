"""Apresentação reutiliza os cálculos e cortes do módulo financeiro."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Exists, F, OuterRef, Q, Sum
from django.utils import timezone

from financeiro.consultas import data_corte, despesas_filtradas, execucao_por_grupo, no_periodo, resumo_financeiro
from financeiro.models import Compromisso, Exercicio, Lancamento, VinculoSocial
from .consultas import tabela

ROTULOS = {
    'orcamento_inicial': 'Orçamento inicial', 'orcamento_atualizado': 'Orçamento atualizado',
    'saldo_inicial': 'Saldo financeiro inicial', 'previsto': 'Receitas previstas', 'recebido': 'Recursos recebidos',
    'comprometido': 'Compromissos em aberto', 'empenhado': 'Empenhado', 'liquidado': 'Liquidado',
    'pago': 'Pago', 'saldo_orcamentario': 'Saldo orçamentário',
    'saldo_financeiro': 'Saldo financeiro', 'execucao_percentual': 'Execução (%)',
}


def relatorio_financeiro(municipio, filtros):
    resumo = resumo_financeiro(municipio, filtros)
    tabelas = [tabela('Execução financeira no corte selecionado', ['Indicador', 'Valor'], [
        [rotulo, resumo[codigo]] for codigo, rotulo in ROTULOS.items()
    ])]
    for campo, rotulo in [('fonte', 'Fonte'), ('fundo', 'Fundo'), ('programa', 'Programa'), ('mes', 'Mês')]:
        dados = execucao_por_grupo(municipio, filtros, campo)
        tabelas.append(tabela(f'Execução por {rotulo.lower()}', [rotulo, 'Recebido', 'Empenhado', 'Liquidado', 'Pago'], [
            [item['rotulo'], item['recebido'], item['empenho'], item['liquidacao'], item['pagamento']]
            for item in dados
        ]))
        if campo == 'mes':
            tabelas.append(tabela('Pagamentos por mês (R$)', ['Mês', 'Pago (R$)'], [
                [item['rotulo'], item['pagamento']] for item in dados
            ]))
    exercicios = Exercicio.objects.filter(municipio=municipio).order_by('ano')
    linhas = []
    for exercicio in exercicios:
        valores = resumo_financeiro(municipio, {**filtros, 'ano': exercicio.ano, 'mes': None})
        linhas.append([exercicio.ano, valores['orcamento_atualizado'], valores['recebido'],
                       valores['empenhado'], valores['pago'], valores['saldo_financeiro']])
    tabelas.append(tabela('Comparativo anual por exercício — ano completo', ['Exercício', 'Orçamento atualizado', 'Recebido', 'Empenhado', 'Pago', 'Saldo financeiro'], linhas))
    tabelas.append(tabela('Pagamentos por origem social agregada (R$)', ['Classificação da despesa', 'Pago (R$)'], custos_sociais(municipio, filtros)))
    return tabelas


def alertas_financeiros(municipio):
    hoje = timezone.localdate()
    compromissos = Compromisso.objects.filter(municipio=municipio).exclude(situacao__in=['cancelado', 'empenhado'])
    lancamentos = Lancamento.objects.filter(municipio=municipio)
    empenhos = lancamentos.filter(tipo='empenho').annotate(
        executado=Sum('derivados__valor', filter=Q(derivados__tipo='liquidacao')))
    liquidacoes = lancamentos.filter(tipo='liquidacao').annotate(
        executado=Sum('derivados__valor', filter=Q(derivados__tipo='pagamento')))
    resumo = resumo_financeiro(municipio, {'ano': hoje.year})
    alerta_recursos = int(resumo['recebido'] > Decimal('0') and resumo['saldo_financeiro'] <= resumo['recebido'] * Decimal('0.10'))
    return [
        ('Compromissos vencidos em aberto', compromissos.filter(vencimento__lt=hoje).count(), 'financeiro:inicio'),
        ('Compromissos a vencer em 7 dias', compromissos.filter(vencimento__range=(hoje, hoje + timedelta(days=7))).count(), 'financeiro:inicio'),
        ('Empenhos com liquidação pendente', empenhos.filter(Q(executado__isnull=True) | Q(executado__lt=F('valor'))).count(), 'financeiro:inicio'),
        ('Liquidações com pagamento pendente', liquidacoes.filter(Q(executado__isnull=True) | Q(executado__lt=F('valor'))).count(), 'financeiro:inicio'),
        ('Saldo financeiro até 10% dos recursos recebidos no exercício atual', alerta_recursos, 'financeiro:inicio'),
    ]


def custos_sociais(municipio, filtros):
    """Classifica cada pagamento uma vez; despesas mistas têm grupo próprio."""
    despesas = despesas_filtradas(municipio, filtros)
    pagamentos = no_periodo(Lancamento.objects.filter(
        municipio=municipio, tipo='pagamento', despesa__in=despesas), data_corte(filtros))
    for campo in ['vale', 'material', 'beneficio']:
        origens = VinculoSocial.objects.filter(municipio=municipio, despesa_id=OuterRef('despesa_id'),
                                               **{campo + '__isnull': False})
        pagamentos = pagamentos.annotate(**{'tem_' + campo: Exists(origens)})
    grupos = {'Vale-Alimentação': Decimal('0'), 'Materiais de construção': Decimal('0'),
              'Benefícios eventuais': Decimal('0'), 'Compartilhadas entre origens sociais': Decimal('0'),
              'Sem vínculo social registrado': Decimal('0')}
    classificacoes = pagamentos.order_by().values('tem_vale', 'tem_material', 'tem_beneficio').annotate(total=Sum('valor'))
    for item in classificacoes:
        categorias = [rotulo for campo, rotulo in [('vale', 'Vale-Alimentação'),
                      ('material', 'Materiais de construção'), ('beneficio', 'Benefícios eventuais')] if item['tem_' + campo]]
        if len(categorias) > 1:
            rotulo = 'Compartilhadas entre origens sociais'
        elif categorias:
            rotulo = categorias[0]
        else:
            rotulo = 'Sem vínculo social registrado'
        grupos[rotulo] += item['total']
    return list(grupos.items())
