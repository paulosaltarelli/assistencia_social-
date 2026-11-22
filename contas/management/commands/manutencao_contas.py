from datetime import timedelta
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone
from contas.models import LimiteLogin


class Command(BaseCommand):
    help = "Remove sessões expiradas e contadores vencidos; preserva eventos de auditoria."

    def handle(self, **options):
        Session.objects.filter(expire_date__lt=timezone.now()).delete()
        LimiteLogin.objects.filter(inicio__lt=timezone.now() - timedelta(days=1)).delete()
        self.stdout.write("Manutenção de sessões e contadores concluída.")
