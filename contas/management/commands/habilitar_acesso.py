from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from atendimentos.models import Auditoria, Vinculo
from contas.models import AjustePermissao
from contas.permissoes import PERMISSOES
from contas.services import contexto


class Command(BaseCommand):
    help = "Concede permissões explicitamente aprovadas a uma conta existente, sem alterar senha."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True)
        parser.add_argument("--municipio-id", type=int, required=True)
        parser.add_argument("--conceder", action="append", choices=list(PERMISSOES), required=True)
        parser.add_argument("--confirmar-autorizacao", action="store_true")
        parser.add_argument("--confirmar-piloto", action="store_true")

    @transaction.atomic
    def handle(self, **options):
        if not options["confirmar_autorizacao"]:
            raise CommandError("Informe a confirmação da autorização do responsável municipal.")
        if options["usuario"] == "gestor.vexo" and not options["confirmar_piloto"]:
            raise CommandError("A conta legada exige confirmação explícita do piloto.")
        vinculo = Vinculo.objects.select_for_update().filter(usuario__username=options["usuario"], municipio_id=options["municipio_id"], usuario__is_active=True).first()
        if not vinculo:
            raise CommandError("Vínculo ativo não encontrado no município informado.")
        if "gestao.ver" in options["conceder"] and vinculo.perfil != "gestor":
            raise CommandError("O painel exclusivo exige perfil Gestor.")
        contexto(vinculo.municipio_id)
        for codigo in options["conceder"]:
            AjustePermissao.objects.update_or_create(
                vinculo=vinculo, codigo=codigo,
                defaults={"municipio": vinculo.municipio, "permitido": True, "concedido_por": None},
            )
        Auditoria.objects.create(municipio=vinculo.municipio, usuario=vinculo.usuario, evento="permissao_operacional")
        self.stdout.write(self.style.SUCCESS("Permissões explicitamente autorizadas registradas. A senha foi preservada."))
