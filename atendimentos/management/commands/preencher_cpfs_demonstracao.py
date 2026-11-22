import json
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from atendimentos.demonstracao.carga import Contexto
from atendimentos.demonstracao.cpfs import complementar_cpfs
from atendimentos.models import Municipio, Vinculo


class Command(BaseCommand):
    help = "Complementa somente CPFs vazios dos UUIDs da demonstração. O padrão apenas simula e informa contagens."

    def add_arguments(self, parser):
        parser.add_argument("--municipio-id", required=True, type=int)
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--confirmar-homologacao", action="store_true")
        modo = parser.add_mutually_exclusive_group()
        modo.add_argument("--aplicar", action="store_true")
        modo.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        if not options["confirmar_homologacao"] or getattr(settings, "SOCIAL_HOMOLOGACAO", False) is not True:
            raise CommandError("Exige confirmação explícita e SOCIAL_HOMOLOGACAO=True.")
        if connection.vendor != "postgresql":
            raise CommandError("A operação exige PostgreSQL e isolamento municipal.")
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_user")
                    if cursor.fetchone()[0] != "social_app":
                        raise CommandError("Execute com a role social_app.")
                    cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", [173946, options["municipio_id"]])
                    if not cursor.fetchone()[0]:
                        raise CommandError("Outra operação de demonstração está em andamento neste município.")
                    cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(options["municipio_id"])])
                municipio = Municipio.objects.filter(pk=options["municipio_id"], nome="Santa Cruz de Minas").first()
                if not municipio:
                    raise CommandError("O município do piloto não foi confirmado pelo ID e nome.")
                vinculo = Vinculo.objects.select_related("usuario").filter(municipio=municipio, usuario__username=options["usuario"]).first()
                if not vinculo:
                    raise CommandError("O autor informado não possui vínculo neste município.")
                contexto = Contexto(municipio, vinculo.usuario, date.today())
                resultado = complementar_cpfs(contexto, aplicar=options["aplicar"])
        except ValidationError as exc:
            raise CommandError("Operação recusada: " + "; ".join(exc.messages)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, indent=2))
