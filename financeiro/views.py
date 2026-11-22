import re
from decimal import Decimal
from functools import wraps
from uuid import UUID

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef, Q, Subquery, Sum
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from .consultas import (data_corte, despesas_filtradas, execucao_por_grupo, filtros_financeiros,
                        pendentes_de_conferencia, recursos_por_origem, resumo_despesa, resumo_financeiro)
from .forms import (CADASTROS, FormConciliacao, FormDespesa, FormEdicao, FormEtapa, FormOrigem,
                    FormSituacao, formulario_cadastro)
from .historico import linha_do_tempo
from .models import (Compromisso, Conciliacao, Despesa, Dotacao, Historico, Lancamento,
                     Receita, RevisaoOrcamento, VinculoSocial)
from .templatetags.financas import reais
from .servicos import alterar_compromisso, atualizar_despesa, cadastrar, executar_etapa


def _pagina(request, qs, tamanho=30, parametro="pagina"):
    return Paginator(qs, tamanho).get_page(request.GET.get(parametro))


def _edita(request):
    return tem_permissao(request.vinculo, "financeiro.editar")


def edicao_financeira(view):
    @municipal("financeiro.editar")
    @wraps(view)
    def editar(request, *args, **kwargs):
        if not tem_permissao(request.vinculo, "financeiro.ver"):
            return HttpResponseForbidden("Consulta financeira indisponível para esta conta.")
        return view(request, *args, **kwargs)
    return editar


def _salvar(request, form, acao, evento):
    if request.method != "POST" or not form.is_valid():
        return None
    try:
        with transaction.atomic():
            objeto = acao()
            registrar_evento(request, evento, objeto.pk)
    except ValidationError as exc:
        form.add_error(None, " ".join(exc.messages))
    except IntegrityError:
        form.add_error(None, "Registro já existente ou incompatível com os dados selecionados. Confira a referência e o município.")
    else:
        messages.success(request, "Registro financeiro salvo.")
        return objeto


def _formulario(request, titulo, form, retorno, contexto=None):
    return render(request, "financeiro/formulario.html", {
        "titulo": titulo, "form": form, "retorno": retorno, "contexto": contexto,
    })


def _painel(request, gestor):
    municipio = request.municipio
    filtros = filtros_financeiros(municipio, request.GET, exercicio_atual=True)
    grupo = request.GET.get("grupo", "fonte")
    if grupo not in {"fonte", "fundo", "programa", "mes"}:
        grupo = "fonte"
    resumo, quadro, documentos, recursos, pendentes = None, [], None, [], None
    if filtros.is_valid():
        resumo = resumo_financeiro(municipio, filtros.cleaned_data)
        quadro = execucao_por_grupo(municipio, filtros.cleaned_data, grupo)
        if gestor:
            despesas = despesas_filtradas(municipio, filtros.cleaned_data)
            recursos = recursos_por_origem(municipio, filtros.cleaned_data)
            pendentes = pendentes_de_conferencia(despesas, data_corte(filtros.cleaned_data)).count()
            if tem_permissao(request.vinculo, "documentos.ver"):
                from documentos.servicos import documentos_autorizados, metricas_despesas
                documentos = metricas_despesas(despesas, docs=documentos_autorizados(request))
    registrar_evento(request, "gestao.painel" if gestor else "financeiro.painel")
    return render(request, "financeiro/painel.html", {
        "titulo": "Painel do gestor" if gestor else "Financeiro", "filtros": filtros,
        "resumo": resumo, "quadro": quadro, "grupo": grupo, "gestor": gestor,
        "documentos": documentos, "edita": _edita(request), "recursos": recursos, "pendentes": pendentes,
        "cadastros": [(chave, dados[0]) for chave, dados in CADASTROS.items()],
        "pode_gestao": tem_permissao(request.vinculo, "gestao.ver"),
        "pode_ver": tem_permissao(request.vinculo, "financeiro.ver"),
        "pode_relatorios": tem_permissao(request.vinculo, "relatorios.ver"),
    })


@municipal("financeiro.ver")
@require_GET
def inicio(request):
    return _painel(request, gestor=False)


@municipal("gestao.ver")
@require_GET
def gestor(request):
    if request.vinculo.perfil != "gestor" or not tem_permissao(request.vinculo, "financeiro.ver"):
        return HttpResponseForbidden("Acesso financeiro do gestor indisponível.")
    return _painel(request, gestor=True)


@municipal("financeiro.ver", post="financeiro.editar")
@require_http_methods(["GET", "POST"])
def cadastro(request, tipo):
    if tipo not in CADASTROS:
        raise Http404
    if not tem_permissao(request.vinculo, "financeiro.ver"):
        return HttpResponseForbidden("Consulta financeira indisponível para esta conta.")
    titulo, model, _ = CADASTROS[tipo]
    municipio = request.municipio
    form = formulario_cadastro(tipo)(request.POST if request.method == "POST" else None, municipio=municipio)
    if _salvar(request, form, lambda: cadastrar(form.save(commit=False), municipio, request.user), "financeiro.cadastro"):
        return redirect("financeiro:cadastro", tipo=tipo)
    registros = model.objects.filter(municipio=municipio)
    if model is Dotacao:
        registros = registros.select_related("exercicio", "fonte", "programa", "fundo", "natureza")
    elif model in {Compromisso, Receita, RevisaoOrcamento}:
        registros = registros.select_related("dotacao__exercicio", "dotacao__programa")
    registros = registros.select_related("responsavel")
    if not registros.ordered:
        registros = registros.order_by("-criado_em", "pk")
    return render(request, "financeiro/cadastro.html", {
        "titulo": titulo, "tipo": tipo, "form": form, "pagina": _pagina(request, registros),
        "edita": _edita(request),
    })


@municipal("financeiro.ver")
@require_GET
def receita(request, pk):
    dados = Receita.objects.select_related("responsavel", "dotacao__fonte", "dotacao__fundo",
                                          "dotacao__programa", "dotacao__exercicio")
    registro = get_object_or_404(dados, pk=pk, municipio=request.municipio)
    registrar_evento(request, "financeiro.receita.consulta", registro.pk)
    return render(request, "financeiro/receita.html", {
        "titulo": registro.get_tipo_display(), "receita": registro, "documentos": tem_permissao(request.vinculo, "documentos.ver"),
        "anexa": _edita(request) and tem_permissao(request.vinculo, "documentos.editar"),
    })


@edicao_financeira
@require_http_methods(["GET", "POST"])
def situacao_compromisso(request, pk):
    comp = get_object_or_404(Compromisso, pk=pk, municipio=request.municipio)
    form = FormSituacao(request.POST if request.method == "POST" else None, initial={"situacao": comp.situacao})
    retorno = reverse("financeiro:cadastro", args=["compromissos"])

    def gravar():
        alterar_compromisso(comp, form.cleaned_data["situacao"], form.cleaned_data["data"], request.user)
        return comp

    if _salvar(request, form, gravar, "financeiro.compromisso.situacao"):
        return redirect(retorno)
    return _formulario(request, "Atualizar compromisso", form, retorno, str(comp))


@municipal("financeiro.ver")
@require_GET
def central(request):
    filtros = filtros_financeiros(request.municipio, request.GET)
    busca = request.GET.get("busca", "").strip()[:100]
    situacao = request.GET.get("situacao", "")
    pendencias = request.GET.get("conferencia") == "pendente"
    tem_docs = tem_permissao(request.vinculo, "documentos.ver")
    despesas = Despesa.objects.none()
    if filtros.is_valid():
        despesas = despesas_filtradas(request.municipio, filtros.cleaned_data).select_related(
            "dotacao__fonte", "dotacao__fundo", "dotacao__programa", "dotacao__natureza", "responsavel")
        termos = Q(descricao__icontains=busca) | Q(fornecedor__icontains=busca) | Q(processo__icontains=busca)
        termos |= Q(documento__icontains=busca)
        cnpj = re.sub(r"[\s./-]", "", busca).upper()
        if cnpj:
            termos |= Q(cnpj=cnpj)
        limite = data_corte(filtros.cleaned_data)
        if busca:
            empenhos = Lancamento.objects.filter(despesa_id=OuterRef("pk"), tipo="empenho", referencia__icontains=busca)
            if limite:
                empenhos = empenhos.filter(data__lte=limite)
            termos |= Q(Exists(empenhos))
        if tem_docs:
            from documentos.models import Categoria, Versao
            from documentos.servicos import documentos_autorizados, versoes_atuais
            notas = documentos_autorizados(request).filter(categoria=Categoria.NOTA)
            recente = Versao.objects.filter(documento__in=notas, documento__despesa_id=OuterRef("pk")).order_by("-criado_em", "-pk")
            despesas = despesas.annotate(nota_recente=Subquery(recente.values("numero_nota")[:1]))
            if busca:
                registros = versoes_atuais(notas).filter(numero_nota__icontains=busca).order_by()
                termos |= Q(pk__in=registros.values("documento__despesa_id"))
        if busca:
            despesas = despesas.filter(termos)
        if pendencias:
            despesas = pendentes_de_conferencia(despesas, limite)
        qdata = Q(lancamentos__data__lte=limite) if limite else Q()
        despesas = despesas.annotate(
            empenhado=Sum("lancamentos__valor", filter=qdata & Q(lancamentos__tipo="empenho"), default=Decimal(0)),
            pago=Sum("lancamentos__valor", filter=qdata & Q(lancamentos__tipo="pagamento"), default=Decimal(0)))
        if situacao == "paga":
            despesas = despesas.filter(pago=F("valor"))
        elif situacao == "parcial":
            despesas = despesas.filter(pago__gt=0, pago__lt=F("valor"))
        elif situacao == "aberta":
            despesas = despesas.filter(pago=0)
    registrar_evento(request, "financeiro.despesas.consulta")
    return render(request, "financeiro/central.html", {
        "titulo": "Central de despesas", "filtros": filtros, "busca": busca, "situacao": situacao,
        "pagina": _pagina(request, despesas.order_by("-data", "-criado_em", "pk")), "edita": _edita(request),
        "tem_docs": tem_docs, "pendencias": pendencias,
    })


@edicao_financeira
@require_http_methods(["GET", "POST"])
def nova_despesa(request):
    form = FormDespesa(request.POST if request.method == "POST" else None, municipio=request.municipio)
    tipo, protocolo = request.GET.get("origem_tipo"), request.GET.get("origem_id")
    origem = None
    contexto = None
    retorno = reverse("financeiro:central")
    if tipo is not None or protocolo is not None:
        if tipo not in FONTES_SOCIAIS or not protocolo:
            raise Http404
        permissao, rotulo, url = FONTES_SOCIAIS[tipo]
        if not tem_permissao(request.vinculo, permissao):
            return HttpResponseForbidden("Consulta à origem social indisponível para esta conta.")
        try:
            pk = UUID(protocolo)
        except ValueError:
            raise Http404
        modelo = VinculoSocial._meta.get_field(tipo).related_model
        origem = get_object_or_404(modelo, pk=pk, municipio=request.municipio)
        contexto = f"Origem social: {rotulo} · {origem.pk}"
        retorno = reverse(url, args=[origem.pk])

    def gravar():
        despesa = cadastrar(form.save(commit=False), request.municipio, request.user)
        if origem:
            vinculo = cadastrar(VinculoSocial(despesa=despesa, **{tipo: origem}), request.municipio, request.user)
            registrar_evento(request, "financeiro.vinculo_social", vinculo.pk)
        return despesa

    obj = _salvar(request, form, gravar, "financeiro.despesa.cadastro")
    if obj:
        return redirect("financeiro:despesa", pk=obj.pk)
    return _formulario(request, "Registrar despesa", form, retorno, contexto)


def _despesa(request, pk):
    qs = Despesa.objects.select_related("dotacao__fonte", "dotacao__fundo", "dotacao__programa", "dotacao__natureza",
                                       "dotacao__exercicio", "responsavel")
    return get_object_or_404(qs, pk=pk, municipio=request.municipio)


@edicao_financeira
@require_http_methods(["GET", "POST"])
def editar_despesa(request, pk):
    obj = _despesa(request, pk)
    form = FormEdicao(request.POST if request.method == "POST" else None, municipio=request.municipio, instance=obj)
    retorno = reverse("financeiro:despesa", args=[obj.pk])
    if _salvar(request, form,
               lambda: atualizar_despesa(obj, form.cleaned_data, request.user, form.cleaned_data["versao_anterior"]),
               "financeiro.despesa.revisao"):
        return redirect(retorno)
    return _formulario(request, "Editar despesa", form, retorno, obj.processo)


FONTES_SOCIAIS = {
    "beneficio": ("beneficios.ver", "Benefício eventual", "programas:beneficio_detalhe"),
    "material": ("materiais.ver", "Pedido de material", "programas:pedido_detalhe"),
    "vale": ("vale.ver", "Vale-Alimentação", "programas:vale_detalhe"),
}


def _fontes_sociais(request):
    return {k: valor for k, valor in FONTES_SOCIAIS.items() if tem_permissao(request.vinculo, valor[0])}


def _origens(despesa, fontes):
    linhas = []
    for campo, (_, nome, url) in fontes.items():
        registros = despesa.origens_sociais.filter(**{campo + "__isnull": False}).select_related(campo)
        for vinculo in registros:
            reg = getattr(vinculo, campo)
            if campo == "beneficio":
                dados = f"Solicitado {reais(reg.valor_solicitado)} · aprovado {reais(reg.valor_aprovado)}"
                if reg.concedido_em:
                    dados += f" · concedido {reais(reg.valor_aprovado)}"
            elif campo == "material":
                dados = f"Solicitado {reg.quantidade_solicitada} · aprovado {reg.quantidade_aprovada} · entregue {reg.entregue}"
            else:
                dados = f"Valor do benefício {reais(reg.valor)} · {reg.get_periodicidade_display()}"
            linhas.append({"nome": nome, "situacao": reg.get_situacao_display(), "dados": dados,
                           "url": reverse(url, args=[reg.pk])})
    return linhas


@municipal("financeiro.ver")
@require_GET
def despesa(request, pk):
    obj = _despesa(request, pk)
    tem_docs = tem_permissao(request.vinculo, "documentos.ver")
    fontes = _fontes_sociais(request)
    etapas = obj.lancamentos.select_related("anterior", "responsavel", "compromisso").order_by("data", "criado_em", "pk")
    conciliacoes = obj.conciliacoes.select_related("responsavel").order_by("data", "criado_em", "pk")
    documentos = None
    if tem_docs:
        from documentos.servicos import documentos_autorizados
        documentos = documentos_autorizados(request)
    linha_tempo = linha_do_tempo(obj, documentos, request.GET.get('pagina'))
    registrar_evento(request, "financeiro.despesa.consulta", pk)
    return render(request, "financeiro/despesa.html", {
        "titulo": "Detalhe da despesa", "despesa": obj, "etapas": _pagina(request, etapas, parametro="pagina_etapas"), "resumo": resumo_despesa(obj),
        "linha_tempo": linha_tempo, "conciliacoes": _pagina(request, conciliacoes, parametro="pagina_conciliacoes"),
        "origens": _origens(obj, fontes), "permite_origens": bool(fontes),
        "tem_docs": tem_docs, "anexa": tem_permissao(request.vinculo, "documentos.editar"), "edita": _edita(request),
        "tipos": Lancamento.Tipo.choices,
    })


@edicao_financeira
@require_http_methods(["GET", "POST"])
def etapa(request, pk, tipo):
    if tipo not in Lancamento.Tipo.values:
        raise Http404
    obj = _despesa(request, pk)
    form = FormEtapa(request.POST if request.method == "POST" else None, municipio=request.municipio, despesa=obj, tipo=tipo)
    retorno = reverse("financeiro:despesa", args=[pk])
    if _salvar(request, form, lambda: executar_etapa(form.save(commit=False), request.municipio, request.user),
               f"financeiro.{tipo}"):
        return redirect(retorno)
    return _formulario(request, "Registrar " + Lancamento.Tipo(tipo).label.lower(), form, retorno, str(obj))


@edicao_financeira
@require_http_methods(["GET", "POST"])
def conciliacao(request, pk):
    obj = _despesa(request, pk)
    form = FormConciliacao(request.POST if request.method == "POST" else None, municipio=request.municipio,
                           instance=Conciliacao(despesa=obj))
    retorno = reverse("financeiro:despesa", args=[pk])
    if _salvar(request, form, lambda: cadastrar(form.save(commit=False), request.municipio, request.user),
               "financeiro.conciliacao"):
        return redirect(retorno)
    return _formulario(request, "Conferir com a contabilidade", form, retorno, str(obj))


@edicao_financeira
@require_http_methods(["GET", "POST"])
def vincular(request, pk):
    obj = _despesa(request, pk)
    fontes = _fontes_sociais(request)
    if not fontes:
        return HttpResponseForbidden("Acesso a programas sociais indisponível.")
    form = FormOrigem(request.POST if request.method == "POST" else None)
    form.fields["tipo"].choices = [(k, v[1]) for k, v in fontes.items()]
    retorno = reverse("financeiro:despesa", args=[pk])

    def gravar():
        tipo = form.cleaned_data["tipo"]
        classe = VinculoSocial._meta.get_field(tipo).related_model
        origem = classe.objects.filter(municipio=request.municipio, pk=form.cleaned_data["protocolo"]).first()
        if not origem:
            raise ValidationError("Registro social indisponível neste município.")
        vinculo = VinculoSocial(despesa=obj, **{tipo: origem})
        return cadastrar(vinculo, request.municipio, request.user)

    if _salvar(request, form, gravar, "financeiro.vinculo_social"):
        return redirect(retorno)
    return _formulario(request, "Vincular origem social", form, retorno, str(obj))


@municipal("gestao.ver")
@require_GET
def auditoria(request):
    if request.vinculo.perfil != "gestor" or not tem_permissao(request.vinculo, "financeiro.ver"):
        return HttpResponseForbidden("Acesso financeiro do gestor indisponível.")
    eventos = Historico.objects.filter(municipio=request.municipio).select_related("responsavel")
    registrar_evento(request, "gestao.auditoria.financeira")
    return render(request, "financeiro/auditoria.html", {"titulo": "Auditoria financeira", "pagina": _pagina(request, eventos)})
