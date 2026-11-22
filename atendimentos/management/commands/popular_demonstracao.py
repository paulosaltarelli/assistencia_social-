import json
import unicodedata
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from atendimentos.demonstracao.carga import Contexto, popular
from atendimentos.models import Municipio, Vinculo


class Command(BaseCommand):
    help = "Acrescenta cenário inteiramente simulado de 12 meses na homologação autorizada de Santa Cruz de Minas."

    def add_arguments(self, parser):
        parser.add_argument("--municipio-id", type=int, required=True)
        parser.add_argument("--usuario", required=True, help="Autor existente e vinculado ao tenant; sua conta será preservada.")
        parser.add_argument("--confirmar-homologacao", action="store_true")
        parser.add_argument("--data-referencia", type=date.fromisoformat, help="Data-base YYYY-MM-DD; a primeira execução a fixa para as seguintes.")

    def handle(self, **options):
        if not options["confirmar_homologacao"] or getattr(settings, "SOCIAL_HOMOLOGACAO", False) is not True:
            raise CommandError("Exige --confirmar-homologacao e SOCIAL_HOMOLOGACAO=True configurado explicitamente.")
        if connection.vendor != "postgresql":
            raise CommandError("Esta carga exige PostgreSQL com políticas municipais aplicadas.")
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_user")
                    if cursor.fetchone()[0] != "social_app":
                        raise CommandError("Execute com a role social_app, sem privilégios administrativos, para manter o isolamento RLS.")
                    cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", [173946, options["municipio_id"]])
                    if not cursor.fetchone()[0]:
                        raise CommandError("Já existe carga de demonstração em andamento neste município.")
                    cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(options["municipio_id"])])
                municipio = Municipio.objects.filter(pk=options["municipio_id"]).first()
                if not municipio:
                    raise CommandError("Município não encontrado.")
                nome = "".join(c for c in unicodedata.normalize("NFKD", municipio.nome) if not unicodedata.combining(c)).strip().casefold()
                if nome != "santa cruz de minas":
                    raise CommandError("O ID informado não corresponde ao tenant confirmado Santa Cruz de Minas. Nenhum dado foi alterado.")
                vinculo = Vinculo.objects.select_related("usuario").filter(
                    usuario__username=options["usuario"], municipio=municipio,
                ).first()
                if not vinculo:
                    raise CommandError("O autor informado precisa ter vínculo no município. Nenhuma conta foi modificada.")
                contexto = Contexto(municipio, vinculo.usuario, options["data_referencia"] or timezone.localdate())
                resultado = popular(contexto, data_explicita=options["data_referencia"] is not None)
        except ValidationError as exc:
            raise CommandError("Carga recusada e transação revertida: " + "; ".join(exc.messages)) from exc
        self.stdout.write(json.dumps(resultado, ensure_ascii=False, indent=2))
