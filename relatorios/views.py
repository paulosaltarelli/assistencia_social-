from decimal import Decimal

from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from .consultas import RelatorioExtenso, alertas_sociais, relatorio_social, tabela
from .exportacao import pdf, xlsx
from .financeiro import alertas_financeiros, relatorio_financeiro
from .forms import FiltrosRelatorio


def preparar_tabelas(tabelas):
    for item in tabelas:
        item['exibidas'] = item['linhas'][:50]
        item['total_linhas'] = len(item['linhas'])
        if len(item['colunas']) == 2 and all(isinstance(linha[1], (int, float, Decimal)) and linha[1] >= 0 for linha in item['linhas']):
            item['maximo'] = max([linha[1] for linha in item['linhas']], default=1) or 1
    return tabelas


@municipal('relatorios.ver')
@require_GET
def inicio(request):
    financeiro_autorizado = tem_permissao(request.vinculo, 'financeiro.ver')
    nominal_autorizado = tem_permissao(request.vinculo, 'cadastros.ver')
    exportar_autorizado = tem_permissao(request.vinculo, 'relatorios.exportar')
    form = FiltrosRelatorio(request.GET, municipio=request.municipio)
    for campo, permissao in [('modalidade', 'beneficios.ver'), ('material', 'materiais.ver'), ('situacao_vale', 'vale.ver')]:
        if not tem_permissao(request.vinculo, permissao):
            form.fields.pop(campo)
    if not nominal_autorizado:
        form.fields.pop('nominal')
    form_financeiro = None
    tabelas = []
    valido = form.is_valid()
    formato = request.GET.get('formato', '')
    if formato and formato not in {'pdf', 'xlsx'}:
        return HttpResponseBadRequest('Formato indisponível.')
    if formato and not exportar_autorizado:
        registrar_evento(request, 'exportacao_relatorios_recusada')
        return HttpResponseForbidden()
    if request.GET.get('nominal') and not nominal_autorizado:
        registrar_evento(request, 'relatorio_nominal_recusado')
        return HttpResponseForbidden()
    if financeiro_autorizado:
        from financeiro.consultas import filtros_financeiros
        form_financeiro = filtros_financeiros(request.municipio, request.GET, exercicio_atual=True)
        valido = form_financeiro.is_valid() and valido
    if valido:
        filtros = form.cleaned_data
        try:
            tabelas = relatorio_social(request.municipio, request.vinculo, filtros)
            if financeiro_autorizado:
                tabelas.extend(relatorio_financeiro(request.municipio, form_financeiro.cleaned_data))
        except RelatorioExtenso as erro:
            form.add_error(None, str(erro))
            valido = False
    if formato and not valido:
        return render(request, 'relatorios/inicio.html', {
            'form': form, 'form_financeiro': form_financeiro, 'tabelas': [],
            'exportar_autorizado': exportar_autorizado,
        }, status=400)
    if formato:
        metadados = tabela('Critérios da consulta', ['Critério', 'Seleção'], [
            ['Município', request.municipio.nome], ['Gerado em', timezone.localtime().strftime('%d/%m/%Y %H:%M')],
            ['Início social', form.cleaned_data.get('inicio') or 'Todos'],
            ['Fim social', form.cleaned_data.get('fim') or 'Até hoje'],
            ['Bairro', form.cleaned_data.get('bairro') or 'Todos'],
            ['Modalidade', str(form.cleaned_data.get('modalidade') or 'Todas')],
            ['Material', str(form.cleaned_data.get('material') or 'Todos')],
            ['Situação do vale', dict(form.fields['situacao_vale'].choices).get(form.cleaned_data.get('situacao_vale'), 'Todas') if 'situacao_vale' in form.fields else 'Sem acesso'],
            ['Identificação pessoal', 'Incluída' if form.cleaned_data.get('nominal') else 'Agregado'],
        ])
        if financeiro_autorizado:
            for campo, valor in form_financeiro.cleaned_data.items():
                metadados['linhas'].append([f'Filtro financeiro — {campo}', str(valor) if valor is not None else 'Todos'])
        resposta = {'pdf': pdf, 'xlsx': xlsx}[formato]([metadados, *tabelas], request.municipio.nome)
        registrar_evento(request, f'exportacao_relatorios_{formato}_' + ('nominal' if form.cleaned_data.get('nominal') else 'agregada'))
        resposta['Cache-Control'] = 'no-store'
        resposta['X-Content-Type-Options'] = 'nosniff'
        return resposta
    registrar_evento(request, 'consulta_relatorios')
    parametros = request.GET.copy()
    parametros.pop('formato', None)
    return render(request, 'relatorios/inicio.html', {
        'form': form, 'form_financeiro': form_financeiro,
        'tabelas': preparar_tabelas(tabelas), 'parametros': parametros.urlencode(),
        'exportar_autorizado': exportar_autorizado, 'financeiro_autorizado': financeiro_autorizado,
    })


@municipal('relatorios.ver')
@require_GET
def alertas(request):
    itens = alertas_sociais(request.municipio, request.vinculo)
    if tem_permissao(request.vinculo, 'financeiro.ver'):
        itens.extend(alertas_financeiros(request.municipio))
    if tem_permissao(request.vinculo, 'documentos.ver'):
        from .documentais import alertas_documentais
        itens.extend(alertas_documentais(request.municipio, request.vinculo))
    registrar_evento(request, 'consulta_alertas')
    return render(request, 'relatorios/alertas.html', {'alertas': itens, 'hoje': timezone.localdate()})
