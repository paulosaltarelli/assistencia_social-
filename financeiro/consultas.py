from calendar import monthrange
from datetime import date
from decimal import Decimal

from django import forms
from django.db.models import OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import (Compromisso, Conciliacao, Despesa, Dotacao, Fonte, Fundo, Lancamento, Programa,
                     Receita, RevisaoOrcamento)

ZERO = Decimal("0")


class FiltrosFinanceiros(forms.Form):
    ano = forms.IntegerField(label="Exercício", min_value=1900, max_value=9999, required=False)
    mes = forms.IntegerField(label="Até o mês", min_value=1, max_value=12, required=False)
    fonte = forms.ModelChoiceField(queryset=Fonte.objects.none(), required=False, empty_label="Todas as fontes")
    fundo = forms.ModelChoiceField(queryset=Fundo.objects.none(), required=False, empty_label="Todos os fundos")
    programa = forms.ModelChoiceField(queryset=Programa.objects.none(), required=False, empty_label="Todos os programas")

    def clean(self):
        dados = super().clean()
        if dados.get("mes") and not dados.get("ano"):
            self.add_error("ano", "Informe o exercício para aplicar o mês de corte.")
        return dados


def filtros_financeiros(municipio, params, exercicio_atual=False):
    if exercicio_atual and not params.get("ano"):
        params = params.copy()
        params["ano"] = timezone.localdate().year
    form = FiltrosFinanceiros(params)
    for nome in ["fonte", "fundo", "programa"]:
        model = form.fields[nome].queryset.model
        form.fields[nome].queryset = model.objects.filter(municipio=municipio).only("pk", "codigo", "nome")
    return form


def data_corte(filtros):
    ano, mes = filtros.get("ano"), filtros.get("mes") or 12
    return date(ano, mes, monthrange(ano, mes)[1]) if ano else None


def dotacoes_filtradas(municipio, filtros):
    qs = Dotacao.objects.filter(municipio=municipio)
    for nome in ["fonte", "fundo", "programa"]:
        if filtros.get(nome):
            qs = qs.filter(**{nome: filtros[nome]})
    if filtros.get("ano"):
        qs = qs.filter(exercicio__ano=filtros["ano"])
    return qs


def no_periodo(queryset, corte):
    return queryset.filter(data__lte=corte) if corte else queryset


def totais_por_tipo(queryset):
    return dict(queryset.order_by().values_list("tipo").annotate(total=Sum("valor")))


def resumo_financeiro(municipio, filtros):
    """Valores nominais da execução acumulada por dotações, até o corte informado."""
    dotacoes = dotacoes_filtradas(municipio, filtros)
    corte = data_corte(filtros)
    abertura = dotacoes.aggregate(orcamento=Sum("valor_inicial", default=ZERO), caixa=Sum("saldo_inicial", default=ZERO))
    revisoes = totais_por_tipo(no_periodo(RevisaoOrcamento.objects.filter(dotacao__in=dotacoes), corte))
    receitas = totais_por_tipo(no_periodo(Receita.objects.filter(dotacao__in=dotacoes), corte))
    etapas = totais_por_tipo(no_periodo(Lancamento.objects.filter(despesa__dotacao__in=dotacoes), corte))
    compromissos = no_periodo(Compromisso.objects.filter(dotacao__in=dotacoes), corte)
    abertos = Q(finalizado_em__isnull=True)
    if corte:
        abertos |= Q(finalizado_em__gt=corte)
    comprometido = compromissos.filter(abertos).aggregate(total=Sum("valor", default=ZERO))["total"]
    atualizado = abertura["orcamento"] + revisoes.get("credito", ZERO) - revisoes.get("anulacao", ZERO)
    empenhado = etapas.get("empenho", ZERO)
    recebido = receitas.get("recebida", ZERO)
    pago = etapas.get("pagamento", ZERO)
    return {
        "orcamento_inicial": abertura["orcamento"],
        "orcamento_atualizado": atualizado,
        "saldo_inicial": abertura["caixa"],
        "previsto": receitas.get("prevista", ZERO),
        "recebido": recebido,
        "comprometido": comprometido,
        "empenhado": empenhado,
        "liquidado": etapas.get("liquidacao", ZERO),
        "pago": pago,
        "saldo_orcamentario": atualizado - empenhado,
        "saldo_financeiro": abertura["caixa"] + recebido - pago,
        "execucao_percentual": (100 * empenhado / atualizado) if atualizado else ZERO,
    }


def resumo_despesa(despesa):
    return totais_por_tipo(despesa.lancamentos.all())


def despesas_filtradas(municipio, filtros):
    dotacoes = dotacoes_filtradas(municipio, filtros)
    return no_periodo(Despesa.objects.filter(dotacao__in=dotacoes), data_corte(filtros))


def pendentes_de_conferencia(despesas, corte):
    ultima = no_periodo(Conciliacao.objects.filter(despesa_id=OuterRef("pk")), corte).order_by("-data", "-criado_em", "-pk")
    return despesas.alias(resultado=Subquery(ultima.values("situacao")[:1])).filter(
        Q(resultado__isnull=True) | Q(resultado="divergente"))


def recursos_por_origem(municipio, filtros):
    receitas = Receita.objects.filter(dotacao__in=dotacoes_filtradas(municipio, filtros), tipo="recebida")
    totais = dict(no_periodo(receitas, data_corte(filtros)).order_by().values_list("dotacao__fonte__origem").annotate(total=Sum("valor")))
    return [(nome, totais.get(chave, ZERO)) for chave, nome in Fonte.Origem.choices
            if chave in {"municipal", "estadual", "federal"} or chave in totais]


def execucao_por_grupo(municipio, filtros, grupo):
    """Agrega cada evento uma vez e conserva meses sem pagamentos."""
    if grupo not in {"fonte", "fundo", "programa", "mes"}:
        grupo = "fonte"
    dotacoes = dotacoes_filtradas(municipio, filtros)
    corte = data_corte(filtros)
    receitas = no_periodo(Receita.objects.filter(dotacao__in=dotacoes, tipo="recebida"), corte)
    movimentos = no_periodo(Lancamento.objects.filter(despesa__dotacao__in=dotacoes), corte)
    if grupo == "mes":
        receitas = receitas.annotate(grupo=TruncMonth("data"))
        movimentos = movimentos.annotate(grupo=TruncMonth("data"))
        chave_rec = chave_mov = "grupo"
        nomes = {}
    else:
        chave_rec = f"dotacao__{grupo}_id"
        chave_mov = f"despesa__dotacao__{grupo}_id"
        nomes = {pk: f"{codigo} · {nome}" for pk, codigo, nome in dotacoes.order_by().values_list(
            f"{grupo}_id", f"{grupo}__codigo", f"{grupo}__nome").distinct()}
    linhas = {}

    def linha(chave):
        if chave not in linhas:
            rotulo = nomes[chave] if grupo != "mes" else f"{chave:%Y/%m}"
            linhas[chave] = {"rotulo": rotulo, "recebido": ZERO, "empenho": ZERO, "liquidacao": ZERO, "pagamento": ZERO}
        return linhas[chave]

    for chave in nomes:
        linha(chave)
    for item in receitas.order_by().values(chave_rec).annotate(soma=Sum("valor")):
        linha(item[chave_rec])["recebido"] = item["soma"]
    for item in movimentos.order_by().values(chave_mov, "tipo").annotate(soma=Sum("valor")):
        linha(item[chave_mov])[item["tipo"]] = item["soma"]
    maximo = max((row["pagamento"] for row in linhas.values()), default=ZERO)
    for row in linhas.values():
        row["percentual_pago"] = round(row["pagamento"] * 100 / maximo) if maximo else 0
    return sorted(linhas.values(), key=lambda row: row["rotulo"])
