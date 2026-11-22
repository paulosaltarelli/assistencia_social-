from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.utils.crypto import salted_hmac
from .models import Atendimento, Auditoria, Cidadao, Familia, Vinculo


class Entrada(LoginView):
    def post(self, request, *args, **kwargs):
        key = salted_hmac("login", request.POST.get("username", "").strip().casefold()).hexdigest()
        cache.add(key, 0, 300)
        if cache.incr(key) > 8:
            return HttpResponse("Tente novamente em alguns minutos.", status=429)
        return super().post(request, *args, **kwargs)


class Formulario(forms.ModelForm):
    class Meta:
        model = Atendimento
        fields = ["cidadao", "unidade", "encaminhamento"]
        labels = {"cidadao": "Cidadão", "unidade": "Unidade responsável", "encaminhamento": "Encaminhamento"}
        help_texts = {"encaminhamento": "Descreva o encaminhamento de forma objetiva."}


class FormFamilia(forms.ModelForm):
    class Meta:
        model = Familia
        fields = ["referencia"]
        labels = {"referencia": "Referência da família"}
        help_texts = {"referencia": "Use uma referência que ajude a equipe a localizar a família."}


class FormCidadao(forms.ModelForm):
    class Meta:
        model = Cidadao
        fields = ["familia", "nome"]
        labels = {"familia": "Família", "nome": "Nome completo"}


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def painel(request, cadastro=None):
    vinculo = Vinculo.objects.filter(usuario=request.user).select_related("municipio").first()
    if not vinculo or vinculo.perfil not in {"gestor", "auditor", "tecnico"}:
        return HttpResponseForbidden()
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(vinculo.municipio_id)])
    tipos = {"atendimento": Formulario, "familia": FormFamilia, "cidadao": FormCidadao}
    tipo = cadastro or request.POST.get("tipo", "atendimento")
    if cadastro and vinculo.perfil == "auditor":
        return HttpResponseForbidden()
    if tipo not in tipos:
        return HttpResponse(status=400)
    formularios = {nome: classe(request.POST if request.method == "POST" and tipo == nome else None)
                   for nome, classe in tipos.items()}
    formularios["cidadao"].fields["familia"].queryset = Familia.objects.filter(municipio=vinculo.municipio).order_by("referencia")
    campo = formularios["atendimento"].fields["cidadao"]
    campo.queryset = Cidadao.objects.filter(municipio=vinculo.municipio).order_by("nome")
    campo.required = True
    form = formularios[tipo]
    evento, objeto = "consulta", None
    if request.method == "POST":
        if vinculo.perfil == "auditor":
            return HttpResponseForbidden()
        if form.is_valid():
            registro = form.save(commit=False)
            registro.municipio = vinculo.municipio
            registro.save()
            evento, objeto = f"cadastro_{tipo}", registro.pk
            confirmacoes = {
                "familia": "Família cadastrada.",
                "cidadao": "Cidadão cadastrado.",
                "atendimento": "Atendimento registrado.",
            }
            messages.success(request, confirmacoes[tipo])
        else:
            messages.error(request, "Revise os campos indicados para concluir o registro.")
    Auditoria.objects.create(municipio=vinculo.municipio, usuario=request.user, evento=evento, objeto=objeto)
    if objeto:
        if cadastro:
            return redirect("cadastro", cadastro=cadastro)
        return redirect("painel")
    atendimentos = Atendimento.objects.filter(municipio=vinculo.municipio)
    resumo = {
        "familias": Familia.objects.filter(municipio=vinculo.municipio).count(),
        "cidadaos": Cidadao.objects.filter(municipio=vinculo.municipio).count(),
        "atendimentos": atendimentos.count(),
        "atendimentos_hoje": atendimentos.filter(criado__date=timezone.localdate()).count(),
    }
    busca = request.GET.get("q", "").strip()[:100]
    if busca:
        atendimentos = atendimentos.filter(
            Q(unidade__icontains=busca)
            | Q(encaminhamento__icontains=busca)
            | Q(cidadao__nome__icontains=busca)
        )
    total_registros = atendimentos.count()
    registros = atendimentos.select_related("cidadao").order_by("-criado", "-id")[:50]
    return render(request, "painel.html", {
        "cadastro": cadastro,
        "titulo": {"familia": "Famílias", "cidadao": "Cidadãos", "atendimento": "Novo atendimento"}.get(cadastro, "Visão geral"),
        "vinculo": vinculo,
        "formularios": formularios,
        "registros": registros,
        "resumo": resumo,
        "busca": busca,
        "total_registros": total_registros,
    })


def health(request):
    try:
        with connection.cursor() as cursor:
            # PostgreSQL resolves the tables and privileges without reading municipal records.
            cursor.execute("""
                SELECT 1 FROM atendimentos_municipio, contas_secretaria, cadastros_complementopessoa,
                              programas_concessaovale, financeiro_despesa, documentos_documento
                WHERE false
            """)
    except DatabaseError:
        return HttpResponse("indisponível", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
