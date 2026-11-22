from datetime import timedelta
import secrets
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables
from .models import AjustePermissao, Recuperacao
from .permissoes import PERMISSOES, DELEGACOES, FINANCEIRAS, SIGILOSAS, GESTAO, MATRIZ, permissoes_efetivas


def contexto(municipio_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(municipio_id)])


def validar_concessoes(autor, destino, perfil, permitir, negar):
    atuais = permissoes_efetivas(destino) if destino else set()
    futuras = ((set(MATRIZ[perfil]) | set(permitir)) - set(negar)) | {"painel.ver"}
    if "gestao.ver" in futuras and perfil != "gestor":
        return "O painel exclusivo exige vínculo com perfil Gestor e autorização expressa."
    for codigo in futuras:
        consulta = codigo.removesuffix(".editar") + ".ver"
        if codigo.endswith(".editar") and consulta in PERMISSOES and consulta not in futuras:
            return "A permissão de edição exige também a consulta ao mesmo módulo."
    if "beneficios.tecnico" in futuras and not {"beneficios.ver", "sigilo.ver"}.issubset(futuras):
        return "O parecer técnico exige consulta de benefícios e acesso ao conteúdo sigiloso."
    adicionadas = futuras - atuais
    poderes = permissoes_efetivas(autor)
    if set(permitir) & DELEGACOES:
        return "Poderes de delegação exigem procedimento operacional autorizado."
    if destino and autor.pk == destino.pk and (futuras - DELEGACOES) != (atuais - DELEGACOES):
        return "Solicite a outro responsável autorizado a alteração de seu perfil ou permissões."
    for grupo, autoridade in [
        (FINANCEIRAS, "contas.conceder_financeiro"),
        (SIGILOSAS, "contas.conceder_sigilo"),
        (GESTAO, "contas.conceder_gestao"),
    ]:
        if adicionadas & grupo and autoridade not in poderes:
            return "Esta concessão exige autorização específica de um responsável habilitado."
    return None


def salvar_ajustes(vinculo, permitir, negar, autor):
    if hasattr(vinculo, "_permissoes_efetivas"):
        del vinculo._permissoes_efetivas
    # As delegações operacionais são preservadas e não são editáveis no formulário.
    AjustePermissao.objects.filter(vinculo=vinculo).exclude(codigo__in=DELEGACOES).delete()
    for permitido, codigos in [(True, permitir), (False, negar)]:
        for codigo in codigos:
            AjustePermissao.objects.create(municipio=vinculo.municipio, vinculo=vinculo, codigo=codigo, permitido=permitido, concedido_por=autor)


def revogar(usuario):
    for sessao in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if sessao.get_decoded().get("_auth_user_id") == str(usuario.pk):
            sessao.delete()


@sensitive_variables()
def emitir_link(request, usuario, municipio):
    Recuperacao.objects.filter(usuario=usuario, utilizada__isnull=True).update(utilizada=timezone.now())
    segredo = secrets.token_urlsafe(32)
    token = Recuperacao.objects.create(
        municipio=municipio, usuario=usuario,
        resumo=salted_hmac("recuperacao", segredo).hexdigest(),
        expira=timezone.now() + timedelta(hours=1),
    )
    # O fragmento é processado no navegador e nunca integra a URL enviada ao servidor.
    base = request.build_absolute_uri(reverse("contas:acesso"))
    return f"{base}#{token.pk}.{segredo}"


def canal_email_ativo(usuario):
    return bool(
        getattr(settings, "CONTAS_SMTP_ATIVO", False) and usuario.email
        and settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    )


@sensitive_variables()
def enviar_link(usuario, link):
    if not canal_email_ativo(usuario):
        return False
    send_mail(
        "Definição de senha — Gestão Social Municipal",
        "Use este link pessoal em até uma hora para definir sua senha. "
        "Se você não solicitou acesso, contate a Secretaria por seu canal oficial.\n\n" + link,
        settings.DEFAULT_FROM_EMAIL, [usuario.email], fail_silently=False,
    )
    return True
