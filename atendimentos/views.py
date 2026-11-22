from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.db import connection, transaction
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


class FormFamilia(forms.ModelForm):
    class Meta:
        model = Familia
        fields = ["referencia"]


class FormCidadao(forms.ModelForm):
    class Meta:
        model = Cidadao
        fields = ["familia", "nome"]


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def painel(request):
    vinculo = Vinculo.objects.filter(usuario=request.user).select_related("municipio").first()
    if not vinculo or vinculo.perfil not in {"gestor", "auditor", "tecnico"}:
        return HttpResponseForbidden()
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(vinculo.municipio_id)])
    tipos = {"atendimento": Formulario, "familia": FormFamilia, "cidadao": FormCidadao}
    tipo = request.POST.get("tipo", "atendimento")
    if tipo not in tipos:
        return HttpResponse(status=400)
    formularios = {nome: classe(request.POST if request.method == "POST" and tipo == nome else None)
                   for nome, classe in tipos.items()}
    formularios["cidadao"].fields["familia"].queryset = Familia.objects.filter(municipio=vinculo.municipio)
    campo = formularios["atendimento"].fields["cidadao"]
    campo.queryset = Cidadao.objects.filter(municipio=vinculo.municipio)
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
    Auditoria.objects.create(municipio=vinculo.municipio, usuario=request.user, evento=evento, objeto=objeto)
    if objeto:
        return redirect("painel")
    registros = Atendimento.objects.filter(municipio=vinculo.municipio).order_by("-criado")[:50]
    return render(request, "painel.html", {"vinculo": vinculo, "formularios": formularios, "registros": registros})


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM atendimentos_municipio LIMIT 1")
    return HttpResponse("ok")
