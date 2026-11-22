from django.apps import apps
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from .forms import (
    AtualizacaoValeForm, BeneficioForm, DecisaoForm, FiltroForm, MaterialForm,
    MovimentoForm, PedidoForm, TipoForm, ValeForm,
)
from .models import ConcessaoVale, Material, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio
from .services import TRANSICOES_BENEFICIO, alterar_vale, decidir_beneficio, decidir_pedido, historico, movimentar_estoque, solicitar_beneficio


def pode_editar(request, codigo):
    return tem_permissao(request.vinculo, codigo)


def pode_vincular_financeiro(request, origem):
    return all(pode_editar(request, codigo) for codigo in (
        origem, "financeiro.ver", "financeiro.editar",
    ))


def erro(form, exc):
    for mensagem in exc.messages:
        form.add_error(None, mensagem)


@municipal("beneficios.ver")
def inicio(request):
    return redirect("programas:beneficios")


def lista(request, modelo, titulo, detalhe, choices, beneficio=False):
    registros = modelo.objects.filter(municipio=request.municipio).select_related("familia", "cidadao")
    if beneficio:
        registros = registros.select_related("tipo")
    if modelo == PedidoMaterial:
        registros = registros.select_related("material")
    filtros = FiltroForm(request.POST if request.method == "POST" else request.GET or None, municipio=request.municipio, choices=choices, beneficio=beneficio)
    if filtros.is_bound:
        if filtros.is_valid():
            dados = filtros.cleaned_data
            if dados.get("busca"):
                registros = registros.filter(Q(cidadao__nome__icontains=dados["busca"]) | Q(familia__referencia__icontains=dados["busca"]))
            if dados.get("situacao"):
                registros = registros.filter(situacao=dados["situacao"])
            if dados.get("responsavel"):
                registros = registros.filter(responsavel=dados["responsavel"])
            if dados.get("cpf"):
                from cadastros.identificacao import indice
                pessoas = apps.get_model("cadastros", "ComplementoPessoa").objects.filter(
                    municipio=request.municipio, cpf_hash=indice(request.municipio.pk, "cpf", dados["cpf"]),
                ).values("cidadao_id")
                registros = registros.filter(cidadao_id__in=pessoas)
            if dados.get("bairro"):
                familias = apps.get_model("cadastros", "ComplementoFamilia").objects.filter(
                    municipio=request.municipio, bairro__icontains=dados["bairro"],
                ).values("familia_id")
                registros = registros.filter(familia_id__in=familias)
            if dados.get("inicio"):
                registros = registros.filter(solicitado_em__gte=dados["inicio"])
            if dados.get("fim"):
                registros = registros.filter(solicitado_em__lte=dados["fim"])
            if dados.get("tipo"):
                registros = registros.filter(tipo=dados["tipo"])
        else:
            registros = registros.none()
    pagina = Paginator(registros, 30).get_page(request.POST.get("pagina") if request.method == "POST" else request.GET.get("pagina"))
    registrar_evento(request, "programas.consulta")
    return render(request, "programas/lista.html", {
        "titulo": titulo, "pagina": pagina, "filtros": filtros, "detalhe": detalhe,
        "area": "beneficio" if beneficio else "vale" if modelo == ConcessaoVale else "material",
        "pode_beneficios": pode_editar(request, "beneficios.editar"),
        "pode_materiais": pode_editar(request, "materiais.editar"),
        "pode_vale": pode_editar(request, "vale.editar"),
    })


@municipal("beneficios.ver")
def beneficios(request):
    return lista(request, SolicitacaoBeneficio, "Benefícios eventuais", "programas:beneficio_detalhe", SolicitacaoBeneficio.SITUACOES, beneficio=True)


@municipal("materiais.ver")
def pedidos(request):
    return lista(request, PedidoMaterial, "Solicitações de materiais", "programas:pedido_detalhe", PedidoMaterial.SITUACOES)


@municipal("vale.ver")
def vales(request):
    return lista(request, ConcessaoVale, "Vale-Alimentação Municipal", "programas:vale_detalhe", ConcessaoVale.SITUACOES)


def cadastro(request, classe, titulo, destino, tipo, permite_tecnica=False):
    kwargs = {"municipio": request.municipio}
    if classe == BeneficioForm:
        kwargs["permite_tecnica"] = permite_tecnica
    form = classe(request.POST if request.method == "POST" else None, **kwargs)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                objeto = form.save(commit=False)
                if hasattr(objeto, "responsavel"):
                    objeto.responsavel = request.user
                if classe == BeneficioForm:
                    solicitar_beneficio(objeto, request.user)
                else:
                    objeto.full_clean()
                    objeto.save()
                    if classe in (PedidoForm, ValeForm):
                        historico(objeto, request.user, "", "Solicitação registrada.")
                registrar_evento(request, "programas.cadastro", objeto.pk)
            messages.success(request, "Registro salvo.")
            return redirect(destino, pk=objeto.pk) if tipo == "detalhe" else redirect(destino)
        except ValidationError as exc:
            erro(form, exc)
    return render(request, "programas/formulario.html", {"form": form, "titulo": titulo})


@municipal("beneficios.ver", post="beneficios.editar")
def beneficio_novo(request):
    return cadastro(request, BeneficioForm, "Solicitar benefício", "programas:beneficio_detalhe", "detalhe", pode_editar(request, "beneficios.tecnico"))


@municipal("beneficios.ver", post="beneficios.editar")
def tipo_novo(request):
    return cadastro(request, TipoForm, "Configurar tipo e regra local", "programas:tipos", "lista")


@municipal("beneficios.ver")
def tipos(request):
    pagina = Paginator(TipoBeneficio.objects.filter(municipio=request.municipio), 30).get_page(request.GET.get("pagina"))
    return render(request, "programas/tipos.html", {"pagina": pagina, "pode_editar": pode_editar(request, "beneficios.editar")})


@municipal("materiais.ver", post="materiais.editar")
def pedido_novo(request):
    return cadastro(request, PedidoForm, "Solicitar materiais", "programas:pedido_detalhe", "detalhe")


@municipal("materiais.ver", post="materiais.editar")
def material_novo(request):
    return cadastro(request, MaterialForm, "Cadastrar material", "programas:estoque", "lista")


@municipal("vale.ver", post="vale.editar")
def vale_novo(request):
    return cadastro(request, ValeForm, "Solicitar Vale-Alimentação", "programas:vale_detalhe", "detalhe")


@municipal("beneficios.ver", post="beneficios.editar")
def beneficio_detalhe(request, pk):
    objeto = get_object_or_404(SolicitacaoBeneficio.objects.select_related("tipo", "familia", "cidadao", "responsavel"), pk=pk, municipio=request.municipio)
    permitidas = TRANSICOES_BENEFICIO.get(objeto.situacao, set())
    escolhas = [(codigo, nome) for codigo, nome in objeto.SITUACOES if codigo in permitidas]
    form = DecisaoForm(request.POST if request.method == "POST" else None, choices=escolhas)
    if request.method == "POST" and form.is_valid():
        try:
            objeto = decidir_beneficio(pk, request.municipio, request.user, **form.cleaned_data)
            registrar_evento(request, "beneficio.decisao", objeto.pk)
            messages.success(request, "Situação do benefício atualizada.")
            return redirect("programas:beneficio_detalhe", pk=pk)
        except ValidationError as exc:
            erro(form, exc)
    registrar_evento(request, "beneficio.consulta", objeto.pk)
    return render(request, "programas/beneficio.html", {
        "objeto": objeto, "form": form, "historico": Paginator(objeto.historico.select_related("autor"), 30).get_page(request.GET.get("historico")),
        "pode_editar": bool(escolhas) and pode_editar(request, "beneficios.editar"), "permite_tecnica": pode_editar(request, "beneficios.tecnico"),
        "pode_vincular_financeiro": pode_vincular_financeiro(request, "beneficios.ver"),
    })


@municipal("materiais.ver", post="materiais.editar")
def pedido_detalhe(request, pk):
    objeto = get_object_or_404(PedidoMaterial.objects.select_related("material", "familia", "cidadao", "responsavel"), pk=pk, municipio=request.municipio)
    entrega = request.method == "POST" and request.POST.get("acao") == "entrega"
    form = DecisaoForm(request.POST if request.method == "POST" and not entrega else None, choices=PedidoMaterial.SITUACOES, material=True)
    form_entrega = MovimentoForm(request.POST if entrega else None, entrega=True)
    atual = form_entrega if entrega else form
    if request.method == "POST" and atual.is_valid():
        try:
            if entrega:
                movimentar_estoque(request.municipio, request.user, objeto.material_id,
                    tipo="saida", pedido_id=objeto.pk, **form_entrega.cleaned_data)
            else:
                decidir_pedido(pk, request.municipio, request.user, **form.cleaned_data)
            registrar_evento(request, "material.entrega" if entrega else "material.decisao", objeto.pk)
            messages.success(request, "Operação registrada.")
            return redirect("programas:pedido_detalhe", pk=pk)
        except ValidationError as exc:
            erro(atual, exc)
    registrar_evento(request, "material.consulta", objeto.pk)
    return render(request, "programas/pedido.html", {
        "objeto": objeto, "form": form, "form_entrega": form_entrega,
        "historico": Paginator(objeto.historico.select_related("autor"), 30).get_page(request.GET.get("historico")), "pode_editar": pode_editar(request, "materiais.editar"),
        "pode_vincular_financeiro": pode_vincular_financeiro(request, "materiais.ver"),
    })


@municipal("materiais.ver")
def estoque(request):
    materiais = Material.objects.filter(municipio=request.municipio)
    pagina = Paginator(materiais, 30).get_page(request.GET.get("pagina"))
    return render(request, "programas/estoque.html", {"pagina": pagina, "pode_editar": pode_editar(request, "materiais.editar")})


@municipal("materiais.ver", post="materiais.editar")
def material_detalhe(request, pk):
    objeto = get_object_or_404(Material, pk=pk, municipio=request.municipio)
    form = MovimentoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            movimentar_estoque(request.municipio, request.user, objeto.pk, **form.cleaned_data)
            registrar_evento(request, "estoque.entrada", objeto.pk)
            messages.success(request, "Entrada de estoque registrada.")
            return redirect("programas:material_detalhe", pk=pk)
        except ValidationError as exc:
            erro(form, exc)
    movimentos = objeto.movimentoestoque_set.select_related("responsavel", "pedido")
    pagina = Paginator(movimentos, 30).get_page(request.GET.get("pagina"))
    return render(request, "programas/material.html", {"objeto": objeto, "form": form, "pagina": pagina, "pode_editar": pode_editar(request, "materiais.editar")})


@municipal("vale.ver", post="vale.editar")
def vale_detalhe(request, pk):
    objeto = get_object_or_404(ConcessaoVale.objects.select_related("familia", "cidadao", "responsavel"), pk=pk, municipio=request.municipio)
    form = AtualizacaoValeForm(request.POST if request.method == "POST" else None, initial={"situacao": objeto.situacao, "valor": objeto.valor, "periodicidade": objeto.periodicidade})
    if request.method == "POST" and form.is_valid():
        try:
            objeto = alterar_vale(pk, request.municipio, request.user, **form.cleaned_data)
            registrar_evento(request, "vale.alteracao", objeto.pk)
            messages.success(request, "Vale-Alimentação atualizado.")
            return redirect("programas:vale_detalhe", pk=pk)
        except ValidationError as exc:
            erro(form, exc)
    registrar_evento(request, "vale.consulta", objeto.pk)
    return render(request, "programas/vale.html", {
        "objeto": objeto, "form": form,
        "historico": Paginator(objeto.historico.select_related("autor"), 30).get_page(request.GET.get("historico")),
        "pode_editar": pode_editar(request, "vale.editar"),
        "pode_vincular_financeiro": pode_vincular_financeiro(request, "vale.ver"),
    })
