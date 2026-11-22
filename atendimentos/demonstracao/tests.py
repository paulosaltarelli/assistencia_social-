import io
import json
import os
from contextlib import contextmanager
from datetime import date
from threading import Event, Thread

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from atendimentos.models import Atendimento, Cidadao, Familia, Municipio, Vinculo
from cadastros.models import AcompanhamentoAtendimento, ComplementoPessoa
from documentos.models import Documento, Versao
from financeiro.models import Despesa
from programas.models import ConcessaoVale, Material, MovimentoEstoque, PedidoMaterial, SolicitacaoBeneficio


@override_settings(SOCIAL_HOMOLOGACAO=True)
class DemonstracaoIntegradaTests(TransactionTestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(nome="Santa Cruz de Minas")
        self.outro = Municipio.objects.create(nome="Outro município fictício")
        self.autor = get_user_model().objects.create_user("autor-simulado", password=None)
        Vinculo.objects.create(usuario=self.autor, municipio=self.municipio, perfil="gestor")
        self.anterior = Familia.objects.create(municipio=self.municipio, referencia="Linha anterior do teste, preservar")
        self.fora = Familia.objects.create(municipio=self.outro, referencia="Linha de outro tenant, preservar")
        self.senha_original = self.autor.password

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

    def executar(self, **options):
        saida = io.StringIO()
        with self.role_app():
            call_command("popular_demonstracao", municipio_id=self.municipio.pk,
                usuario=self.autor.username, confirmar_homologacao=True, stdout=saida, **options)
        return json.loads(saida.getvalue())

    def test_carga_integrada_idempotente_com_scanner_real(self):
        resultado = self.executar(data_referencia=date(2026, 11, 22))
        self.assertEqual(resultado["cenario"], {"familias": 80, "pessoas": 280, "beneficios": 72, "pedidos": 36, "vales": 60})
        self.assertEqual(Cidadao.objects.filter(municipio=self.municipio).count(), 280)
        self.assertEqual(Atendimento.objects.filter(municipio=self.municipio).count(), 348)
        self.assertEqual(len(list(AcompanhamentoAtendimento.objects.dates("data_efetiva", "month"))), 12)
        self.assertEqual(ComplementoPessoa.objects.exclude(cpf_hash="").count(), 0)
        self.assertEqual(ComplementoPessoa.objects.exclude(nis_hash="").count(), 0)
        self.assertEqual(ComplementoPessoa.objects.exclude(telefone="").count(), 0)
        self.assertEqual(SolicitacaoBeneficio.objects.values("situacao").distinct().count(), 7)
        self.assertEqual(ConcessaoVale.objects.values("situacao").distinct().count(), 5)
        self.assertFalse(Material.objects.filter(saldo__lt=0).exists())
        self.assertTrue(Material.objects.filter(saldo=0).exists())
        self.assertTrue(PedidoMaterial.objects.filter(situacao="entregue").exists())
        self.assertEqual(Despesa.objects.count(), 36)
        self.assertGreater(Documento.objects.count(), 50)
        self.assertGreater(Versao.objects.count(), Documento.objects.count())
        modelos = [Familia, Cidadao, Atendimento, AcompanhamentoAtendimento, SolicitacaoBeneficio,
                   Material, MovimentoEstoque, PedidoMaterial, ConcessaoVale, Despesa, Documento, Versao]
        antes = {m._meta.label: m.objects.count() for m in modelos}
        saldos = list(Material.objects.order_by("id").values_list("id", "saldo"))
        segunda = self.executar()
        self.assertEqual(segunda["data_referencia"], "2026-11-22")
        self.assertEqual(segunda["criados"], {})
        self.assertEqual(segunda["financeiro"], {})
        self.assertEqual({m._meta.label: m.objects.count() for m in modelos}, antes)
        self.assertEqual(list(Material.objects.order_by("id").values_list("id", "saldo")), saldos)
        self.anterior.refresh_from_db()
        self.fora.refresh_from_db()
        self.autor.refresh_from_db()
        self.assertEqual(self.anterior.referencia, "Linha anterior do teste, preservar")
        self.assertEqual(self.fora.referencia, "Linha de outro tenant, preservar")
        self.assertEqual(self.autor.password, self.senha_original)
        self.assertEqual(get_user_model().objects.count(), 1)
        with self.assertRaises(CommandError):
            self.executar(data_referencia=date(2026, 10, 22))

    def test_exige_homologacao_e_role_sem_privilegio(self):
        with self.assertRaises(CommandError):
            call_command("popular_demonstracao", municipio_id=self.municipio.pk, usuario=self.autor.username)
        with override_settings(SOCIAL_HOMOLOGACAO=False), self.assertRaises(CommandError):
            self.executar()
        with self.assertRaises(CommandError):
            call_command("popular_demonstracao", municipio_id=self.municipio.pk, usuario=self.autor.username, confirmar_homologacao=True)
        self.assertEqual(Cidadao.objects.count(), 0)

    def test_falha_de_arquivo_reverte_toda_carga(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"SOCIAL_CLAMAV_HOST": "127.0.0.1", "SOCIAL_CLAMAV_PORT": "1", "SOCIAL_CLAMAV_TIMEOUT": "1"}):
            with self.assertRaises(CommandError):
                self.executar(data_referencia=date(2026, 11, 22))
        self.assertEqual(Cidadao.objects.count(), 0)
        self.assertEqual(Atendimento.objects.count(), 0)
        self.assertEqual(SolicitacaoBeneficio.objects.count(), 0)
        self.assertEqual(Despesa.objects.count(), 0)
        self.assertEqual(Familia.objects.count(), 2)

    def test_lock_impede_duas_cargas_concorrentes(self):
        bloqueado = Event()
        liberar = Event()

        def segurar():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [173946, self.municipio.pk])
                    bloqueado.set()
                    liberar.wait(timeout=10)
            finally:
                close_old_connections()

        thread = Thread(target=segurar)
        thread.start()
        try:
            self.assertTrue(bloqueado.wait(timeout=5))
            with self.assertRaisesMessage(CommandError, "Já existe carga"):
                self.executar()
        finally:
            liberar.set()
            thread.join(timeout=10)
        self.assertEqual(Cidadao.objects.count(), 0)
