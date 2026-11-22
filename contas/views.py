from datetime import timedelta
import secrets
import smtplib
import uuid
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.db import connection, IntegrityError, transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST
from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from atendimentos.models import Vinculo
from .forms import AlterarSenhaForm, ProfissionalForm, SecretariaForm, RecuperarForm, NovaSenhaForm
from .models import EventoAutenticacao, LimiteLogin, Recuperacao, Secretaria
from .permissoes import DELEGACOES, PERMISSOES, permissoes_efetivas
from .services import canal_email_ativo, contexto, emitir_link, enviar_link, revogar, salvar_ajustes, validar_concessoes


def limitar(chave):
    agora = timezone.now()
    limite, _ = LimiteLogin.objects.get_or_create(chave=chave, defaults={"inicio": agora})
    limite = LimiteLogin.objects.select_for_update().get(pk=chave)
    if limite.inicio < agora - timedelta(minutes=15):
        limite.inicio = agora
        limite.tentativas = 0
    if limite.tentativas >= 8:
        return False
    limite.tentativas += 1
    limite.save(update_fields=["inicio", "tentativas"])
    return True


class Entrar(LoginView):
    template_name = "contas/entrar.html"
    redirect_authenticated_user = True

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        nome = request.POST.get("username", "").strip().casefold()
        self.chave_limite = salted_hmac("contas-limite-login", nome).hexdigest()
        if not limitar(self.chave_limite):
            EventoAutenticacao.objects.create(evento="login_limitado", conta_resumo=self.chave_limite)
            resposta = render(request, self.template_name, {"form": self.get_form_class()(request=request), "limitado": True}, status=429)
            resposta["Retry-After"] = "900"
            return resposta
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        resposta = super().form_valid(form)
        LimiteLogin.objects.filter(pk=self.chave_limite).delete()
        return resposta

    def get_success_url(self):
        return super().get_success_url()


class Sair(LogoutView):
    next_page = reverse_lazy("contas:entrar")


class Senha(PasswordChangeView):
    form_class = AlterarSenhaForm
    template_name = "contas/senha.html"
    success_url = reverse_lazy("contas:inicio")

    def form_valid(self, form):
        with transaction.atomic():
            resposta = super().form_valid(form)
            vinculo = Vinculo.objects.filter(usuario=self.request.user).first()
            if vinculo:
                contexto(vinculo.municipio_id)
                Recuperacao.objects.filter(usuario=self.request.user, utilizada__isnull=True).update(utilizada=timezone.now())
            revogar(self.request.user)
            update_session_auth_hash(self.request, self.request.user)
            EventoAutenticacao.objects.create(usuario=self.request.user, autor=self.request.user, evento="senha_alterada")
        messages.success(self.request, "Senha alterada. As demais sessões foram encerradas.")
        return resposta


@login_required
@never_cache
@require_http_methods(["GET"])
@transaction.atomic
def inicio(request):
    vinculo = Vinculo.objects.select_related("usuario", "municipio").filter(usuario=request.user).first()
    if not vinculo:
        return HttpResponseForbidden("Conta sem vínculo municipal ativo.")
    contexto(vinculo.municipio_id)
    request.vinculo, request.municipio = vinculo, vinculo.municipio
    pode_gerir = tem_permissao(vinculo, "contas.gerir")
    profissionais = []
    if pode_gerir:
        profissionais = Vinculo.objects.select_related("usuario").filter(municipio=vinculo.municipio).order_by("usuario__first_name", "usuario__username")
    return render(request, "contas/inicio.html", {
        "vinculo": vinculo, "profissionais": profissionais, "pode_gerir": pode_gerir,
        "pode_configurar": tem_permissao(vinculo, "configuracao.editar"),
        "permissoes": [PERMISSOES[codigo] for codigo in sorted(permissoes_efetivas(vinculo)) if codigo in PERMISSOES],
        "secretaria": Secretaria.objects.filter(municipio=request.municipio).first(),
    })


@never_cache
@municipal("contas.gerir", post="contas.gerir")
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters()
@sensitive_variables()
def profissional(request, pk=None):
    # Serializa as alterações de contas do município, inclusive desativações.
    vinculos = Vinculo.objects.select_for_update().filter(municipio=request.municipio)
    list(vinculos.values_list("id", flat=True))
    destino = get_object_or_404(vinculos.select_related("usuario"), pk=pk) if pk else None
    inicial = {}
    if destino:
        ajustes = list(destino.ajustes_permissao.all())
        inicial = {"nome": destino.usuario.first_name, "username": destino.usuario.username,
                   "email": destino.usuario.email, "perfil": destino.perfil,
                   "permitir": [a.codigo for a in ajustes if a.permitido],
                   "negar": [a.codigo for a in ajustes if not a.permitido]}
    form = ProfissionalForm(request.POST if request.method == "POST" else None, initial=inicial)
    if destino:
        form.fields["username"].disabled = True
    link = None
    if request.method == "POST" and form.is_valid():
        dados = form.cleaned_data
        erro = validar_concessoes(request.vinculo, destino, dados["perfil"], dados["permitir"], dados["negar"])
        if erro:
            form.add_error(None, erro)
        else:
            try:
                with transaction.atomic():
                    usuario = destino.usuario if destino else get_user_model()(username=dados["username"])
                    usuario.first_name = dados["nome"]
                    usuario.email = dados["email"]
                    if not destino:
                        usuario.set_unusable_password()
                    if destino:
                        usuario.save(update_fields=["first_name", "email"])
                    else:
                        usuario.save()
                    if destino:
                        destino.perfil = dados["perfil"]
                        destino.save(update_fields=["perfil"])
                    else:
                        destino = Vinculo.objects.create(usuario=usuario, municipio=request.municipio, perfil=dados["perfil"])
                    salvar_ajustes(destino, dados["permitir"], dados["negar"], request.user)
                    if usuario.pk != request.user.pk:
                        revogar(usuario)
                    registrar_evento(request, "conta_atualizada")
                    EventoAutenticacao.objects.create(usuario=usuario, autor=request.user, municipio=request.municipio, evento="conta_atualizada")
                    link = emitir_link(request, usuario, request.municipio) if not usuario.has_usable_password() else None
            except IntegrityError:
                form.add_error(None, "Não foi possível salvar. Verifique o identificador de acesso.")
            else:
                if link:
                    return render(request, "contas/link.html", {"link": link, "profissional": destino})
                messages.success(request, "Conta atualizada. As sessões anteriores foram revogadas.")
                return redirect("contas:inicio")
    return render(request, "contas/profissional.html", {"form": form, "profissional": destino, "vinculo": request.vinculo})


@never_cache
@municipal("contas.gerir", post="contas.gerir")
@require_POST
@sensitive_post_parameters()
@sensitive_variables()
def acao(request, pk):
    vinculos = Vinculo.objects.select_for_update().filter(municipio=request.municipio)
    list(vinculos.values_list("id", flat=True))
    destino = get_object_or_404(vinculos.select_related("usuario"), pk=pk)
    if destino.usuario_id == request.user.pk:
        return HttpResponseForbidden("Solicite a ação a outro responsável autorizado.")
    operacao = request.POST.get("acao")
    if operacao in {"revogar", "desativar", "ativar"}:
        Recuperacao.objects.filter(usuario=destino.usuario, utilizada__isnull=True).update(utilizada=timezone.now())
    if operacao == "revogar":
        revogar(destino.usuario)
        registrar_evento(request, "sessoes_revogadas")
    elif operacao in {"desativar", "ativar"}:
        destino.usuario.is_active = operacao == "ativar"
        destino.usuario.save(update_fields=["is_active"])
        revogar(destino.usuario)
        registrar_evento(request, "conta_" + operacao)
    elif operacao == "redefinir":
        link = emitir_link(request, destino.usuario, request.municipio)
        registrar_evento(request, "redefinicao_emitida")
        EventoAutenticacao.objects.create(usuario=destino.usuario, autor=request.user, municipio=request.municipio, evento="redefinicao_emitida")
        try:
            entregue = enviar_link(destino.usuario, link)
        except (smtplib.SMTPException, OSError):
            entregue = False
        return render(request, "contas/link.html", {"link": link, "profissional": destino, "entregue": entregue})
    else:
        return HttpResponse(status=400)
    EventoAutenticacao.objects.create(usuario=destino.usuario, autor=request.user, municipio=request.municipio, evento="conta_" + operacao)
    messages.success(request, "Ação concluída.")
    return redirect("contas:inicio")


@never_cache
@municipal("configuracao.editar", post="configuracao.editar")
@require_http_methods(["GET", "POST"])
def configurar(request):
    secretaria = Secretaria.objects.filter(municipio=request.municipio).first()
    form = SecretariaForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=secretaria)
    if request.method == "POST" and form.is_valid():
        secretaria = form.save(commit=False)
        secretaria.municipio = request.municipio
        if form.cleaned_data["remover_brasao"]:
            secretaria.brasao = None
            secretaria.brasao_tipo = ""
        if form.cleaned_data["imagem_brasao"]:
            secretaria.brasao = form.cleaned_data["imagem_brasao"]
            secretaria.brasao_tipo = "image/png"
        secretaria.save()
        registrar_evento(request, "secretaria_atualizada")
        messages.success(request, "Identidade e contatos atualizados.")
        return redirect("contas:inicio")
    return render(request, "contas/configurar.html", {"form": form, "vinculo": request.vinculo})


@login_required
@never_cache
@require_http_methods(["GET"])
@transaction.atomic
def brasao(request):
    vinculo = get_object_or_404(Vinculo, usuario=request.user)
    contexto(vinculo.municipio_id)
    secretaria = get_object_or_404(Secretaria, municipio_id=vinculo.municipio_id)
    if not secretaria.brasao:
        return HttpResponse(status=404)
    resposta = HttpResponse(bytes(secretaria.brasao), content_type="image/png")
    resposta["X-Content-Type-Options"] = "nosniff"
    return resposta


@never_cache
@require_http_methods(["GET", "POST"])
@transaction.atomic
@sensitive_post_parameters()
@sensitive_variables()
def recuperar(request):
    form = RecuperarForm(request.POST if request.method == "POST" else None)
    enviado = False
    if request.method == "POST" and form.is_valid():
        nome = form.cleaned_data["username"].strip()
        chave = salted_hmac("contas-limite-recuperacao", nome.casefold()).hexdigest()
        permitido = limitar(chave)
        if permitido:
            vinculo = Vinculo.objects.select_related("usuario", "municipio").filter(usuario__username=nome, usuario__is_active=True).first()
            if vinculo and canal_email_ativo(vinculo.usuario):
                contexto(vinculo.municipio_id)
                link = emitir_link(request, vinculo.usuario, vinculo.municipio)
                try:
                    enviar_link(vinculo.usuario, link)
                except (smtplib.SMTPException, OSError):
                    pass
        enviado = True
    return render(request, "contas/recuperar.html", {"form": form, "enviado": enviado})


@never_cache
@require_http_methods(["GET", "POST"])
@transaction.atomic
@sensitive_post_parameters()
@sensitive_variables()
def acesso(request):
    comprovante = request.POST.get("comprovante", "")
    usuario = get_user_model()()
    token = None
    if request.method == "POST":
        try:
            seletor, segredo = comprovante.split(".", 1)
            seletor = uuid.UUID(seletor)
        except (ValueError, TypeError):
            seletor, segredo = None, ""
        if seletor:
            resumo = salted_hmac("recuperacao", segredo).hexdigest()
            with connection.cursor() as cursor:
                cursor.execute("SELECT contas_validar_recuperacao(%s::uuid, %s)", [str(seletor), resumo])
                registro = cursor.fetchone()
            if registro and registro[0]:
                contexto(registro[0])
                token = Recuperacao.objects.select_for_update().select_related("usuario").filter(pk=seletor, utilizada__isnull=True, expira__gt=timezone.now(), usuario__is_active=True).first()
                if token and secrets.compare_digest(token.resumo, resumo):
                    usuario = token.usuario
                else:
                    token = None
    form = NovaSenhaForm(usuario, request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not token:
            form.add_error(None, "Link indisponível ou expirado. Solicite uma nova redefinição.")
        elif form.is_valid():
            form.save()
            token.utilizada = timezone.now()
            token.save(update_fields=["utilizada"])
            Recuperacao.objects.filter(usuario=usuario, utilizada__isnull=True).update(utilizada=timezone.now())
            revogar(usuario)
            EventoAutenticacao.objects.create(usuario=usuario, autor=usuario, municipio=token.municipio, evento="senha_redefinida")
            messages.success(request, "Senha definida. Entre com seu identificador de acesso.")
            return redirect("contas:entrar")
    return render(request, "contas/acesso.html", {"form": form})
