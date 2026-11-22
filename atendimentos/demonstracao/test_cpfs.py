import io
import json
import re
from contextlib import contextmanager
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from atendimentos.models import Cidadao, Familia, Municipio, Vinculo
from cadastros.identificacao import documento, indice
from cadastros.models import AtualizacaoCadastro, ComplementoPessoa
from .carga import Contexto, configurar_periodo
from .cpfs import campos_cpf, complementar_cpfs, cpf_do_cenario, cpf_sintetico, preparar_cpfs


class CpfSinteticoTests(SimpleTestCase):
    def test_digitos_unicidade_determinismo_e_zeros_iniciais(self):
        gerados = [cpf_sintetico(ordem) for ordem in range(1, 281)]
        self.assertEqual(len(set(gerados)), 280)
        self.assertEqual({cpf[0] for cpf in gerados}, set("0123456789"))
        for ordem, cpf in enumerate(gerados, 1):
            self.assertTrue(documento(cpf, "cpf") == cpf)
            self.assertTrue(cpf_sintetico(ordem) == cpf)
            self.assertEqual(len(cpf), 11)
            self.assertGreater(len(set(cpf[:9])), 1)
        self.assertEqual(len({cpf_do_cenario(n, i) for n in range(1, 81) for i in range(2 + n % 4)}), 280)

    def test_parametros_invalidos(self):
        for ordem in (0, 281, True, "1"):
            with self.assertRaises(ValueError):
                cpf_sintetico(ordem)


@override_settings(SOCIAL_HOMOLOGACAO=True)
class ComplementarCpfsTests(TransactionTestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(nome="Santa Cruz de Minas")
        self.outro = Municipio.objects.create(nome="Outro município fictício")
        self.user = get_user_model().objects.create_user("autor-cpf-simulado", password=None)
        Vinculo.objects.create(usuario=self.user, municipio=self.municipio, perfil="gestor")
        self.contexto = Contexto(self.municipio, self.user, date(2026, 11, 22))
        configurar_periodo(self.contexto)
        familia, _ = self.contexto.criar(Familia, "familia/1", referencia="Família do cenário de teste")
        self.registros = []
        for posicao in range(3):
            pessoa, _ = self.contexto.criar(Cidadao, f"pessoa/1/{posicao}", familia=familia, nome=f"Pessoa sintética {posicao}")
            complemento, _ = self.contexto.criar(ComplementoPessoa, f"pessoa/dados/1/{posicao}", cidadao=pessoa)
            self.registros.append(complemento)
        self.registros[1].cpf_hash = indice(self.municipio.pk, "cpf", cpf_sintetico(100))
        self.registros[1].cpf_ultimos = cpf_sintetico(100)[-4:]
        self.registros[1].save()
        pessoa_manual = Cidadao.objects.create(municipio=self.municipio, familia=familia, nome="Registro fora do namespace")
        self.manual = ComplementoPessoa.objects.create(municipio=self.municipio, cidadao=pessoa_manual,
            cpf_hash=indice(self.municipio.pk, "cpf", cpf_do_cenario(1, 2)), cpf_ultimos=cpf_do_cenario(1, 2)[-4:])
        familia_b = Familia.objects.create(municipio=self.outro, referencia="Outro tenant")
        pessoa_b = Cidadao.objects.create(municipio=self.outro, familia=familia_b, nome="Pessoa de outro tenant")
        self.registro_b = ComplementoPessoa.objects.create(municipio=self.outro, cidadao=pessoa_b)

    @contextmanager
    def role_app(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL ROLE social_app")
            try:
                yield
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")

    def executar(self, aplicar=False):
        saida = io.StringIO()
        with self.role_app():
            call_command("preencher_cpfs_demonstracao", municipio_id=self.municipio.pk,
                usuario=self.user.username, confirmar_homologacao=True, aplicar=aplicar, stdout=saida)
        self.assertFalse(re.search(r"\d{11}", saida.getvalue()))
        return json.loads(saida.getvalue())

    def test_dry_run_aplicacao_idempotencia_e_preservacao(self):
        manual = (self.registros[1].cpf_hash, self.registros[1].cpf_ultimos)
        simulado = self.executar()
        self.assertEqual(simulado["modo"], "simulacao")
        self.assertEqual(simulado["contagens"].get("elegiveis"), 1)
        self.assertEqual(simulado["contagens"].get("manuais_preservados"), 1)
        self.assertEqual(simulado["contagens"].get("colisoes_preservadas"), 1)
        self.registros[0].refresh_from_db()
        self.assertFalse(self.registros[0].cpf_hash)
        aplicado = self.executar(aplicar=True)
        self.assertEqual(aplicado["contagens"].get("preenchidos"), 1)
        self.registros[0].refresh_from_db()
        self.assertTrue(self.registros[0].cpf_hash == indice(self.municipio.pk, "cpf", cpf_do_cenario(1, 0)))
        self.assertTrue(self.registros[0].cpf_ultimos == cpf_do_cenario(1, 0)[-4:])
        self.registros[1].refresh_from_db()
        self.assertTrue((self.registros[1].cpf_hash, self.registros[1].cpf_ultimos) == manual)
        self.registro_b.refresh_from_db()
        self.assertFalse(self.registro_b.cpf_hash)
        self.assertEqual(AtualizacaoCadastro.objects.filter(acao="cpf_simulado").count(), 1)
        repetida = self.executar(aplicar=True)
        self.assertEqual(repetida["contagens"].get("ja_preenchidos"), 1)
        self.assertEqual(repetida["contagens"].get("preenchidos", 0), 0)
        self.assertEqual(AtualizacaoCadastro.objects.filter(acao="cpf_simulado").count(), 1)

    def test_prefetch_unico_e_dry_run_sem_row_lock(self):
        with self.role_app():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(self.municipio.pk)])
            with CaptureQueriesContext(connection) as consultas:
                preparar_cpfs(self.contexto)
                for numero in range(1, 81):
                    for posicao in range(2 + numero % 4):
                        campos_cpf(self.contexto, numero, posicao)
            self.assertEqual(len(consultas), 1)
            with CaptureQueriesContext(connection) as consultas:
                complementar_cpfs(self.contexto, aplicar=False)
            self.assertEqual(len(consultas), 3)
            self.assertFalse(any("FOR UPDATE" in item["sql"].upper() for item in consultas))

    def test_campos_parciais_e_ids_manuais_sao_preservados(self):
        self.registros[0].cpf_ultimos = "0001"
        self.registros[0].save()
        resultado = self.executar(aplicar=True)
        self.assertEqual(resultado["contagens"].get("manuais_preservados"), 2)
        self.assertEqual(resultado["contagens"].get("preenchidos", 0), 0)
        self.registros[0].refresh_from_db()
        self.assertFalse(self.registros[0].cpf_hash)

    def test_exige_ambiente_e_role_sem_privilegio(self):
        with override_settings(SOCIAL_HOMOLOGACAO=False), self.assertRaises(CommandError):
            self.executar()
        with self.assertRaises(CommandError):
            call_command("preencher_cpfs_demonstracao", municipio_id=self.municipio.pk,
                usuario=self.user.username, confirmar_homologacao=True)
