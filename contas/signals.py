from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.utils.crypto import salted_hmac
from atendimentos.models import Vinculo
from .models import EventoAutenticacao


def registrar(usuario, evento, conta=""):
    municipio_id = None
    if usuario and usuario.pk:
        municipio_id = Vinculo.objects.filter(usuario=usuario).values_list("municipio_id", flat=True).first()
    EventoAutenticacao.objects.create(
        usuario=usuario if usuario and usuario.pk else None,
        autor=usuario if usuario and usuario.pk else None,
        municipio_id=municipio_id, evento=evento,
        conta_resumo=salted_hmac("contas-login", conta.casefold().strip()).hexdigest() if conta else "",
    )


@receiver(user_logged_in, dispatch_uid="contas_login")
def login(sender, request, user, **kwargs):
    registrar(user, "login_sucesso")


@receiver(user_logged_out, dispatch_uid="contas_logout")
def logout(sender, request, user, **kwargs):
    registrar(user, "logout")


@receiver(user_login_failed, dispatch_uid="contas_login_falhou")
def falhou(sender, credentials, request, **kwargs):
    registrar(None, "login_falhou", str(credentials.get("username", "")))
