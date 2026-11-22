import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from atendimentos.models import Municipio, Vinculo


class Command(BaseCommand):
    help = "Prepara três contas fictícias para validação em desenvolvimento."

    @transaction.atomic
    def handle(self, **options):
        if os.environ.get("SOCIAL_DEV") != "1":
            raise CommandError("Exige ambiente de desenvolvimento.")
        password = os.environ["SOCIAL_DEMO_PASSWORD"]
        for login, nome, perfil in [
            ("tecnico-a", "Município Fictício A", "tecnico"),
            ("tecnico-b", "Município Fictício B", "tecnico"),
            ("auditor-a", "Município Fictício A", "auditor"),
        ]:
            municipio, _ = Municipio.objects.get_or_create(nome=nome)
            user, _ = get_user_model().objects.get_or_create(username=login)
            user.set_password(password)
            user.save()
            Vinculo.objects.update_or_create(usuario=user, defaults={"municipio": municipio, "perfil": perfil})
