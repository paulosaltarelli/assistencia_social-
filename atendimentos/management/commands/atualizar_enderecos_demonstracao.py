import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from atendimentos.demonstracao.carga import Contexto
from atendimentos.demonstracao.enderecos import atualizar_enderecos
from atendimentos.models import Vinculo


class Command(BaseCommand):
    help = 'Confere ou atualiza somente os pares de endereço do cenário de homologação em Santa Cruz de Minas.'

    def add_arguments(self, parser):
        parser.add_argument('--municipio-id', type=int, required=True)
        parser.add_argument('--usuario', required=True)
        parser.add_argument('--conferir', action='store_true', help='Apresenta os contadores sem alterar endereços.')

    @transaction.atomic
    def handle(self, **opcoes):
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_user')
            if cursor.fetchone()[0] != 'social_app':
                raise CommandError('Execute com a role da aplicação para aplicar o isolamento municipal.')
            cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [173946, opcoes['municipio_id']])
            cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(opcoes['municipio_id'])])
        vinculo = Vinculo.objects.select_related('usuario', 'municipio').filter(municipio_id=opcoes['municipio_id'], usuario__username=opcoes['usuario']).first()
        if not vinculo:
            raise CommandError('A conta precisa ter vínculo com o município informado.')
        try:
            resultado = atualizar_enderecos(Contexto(vinculo.municipio, vinculo.usuario, timezone.localdate()), opcoes['conferir'])
        except (ValueError, ValidationError) as erro:
            raise CommandError(str(erro)) from erro
        self.stdout.write(json.dumps(resultado, ensure_ascii=False))
