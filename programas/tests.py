from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from atendimentos.models import Cidadao, Familia, Municipio, Vinculo
from .forms import BeneficioForm, PedidoForm
from .models import ConcessaoVale, HistoricoBeneficio, Material, MovimentoEstoque, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio
from .services import alterar_vale, decidir_beneficio, decidir_pedido, movimentar_estoque, solicitar_beneficio


class FluxosProgramasTests(TransactionTestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(nome="Município fictício A")
        self.outro = Municipio.objects.create(nome="Município fictício B")
        self.usuario = get_user_model().objects.create_user("operador-ficticio")
        self.familia = Familia.objects.create(municipio=self.municipio, referencia="Família fictícia A")
        self.cidadao = Cidadao.objects.create(municipio=self.municipio, familia=self.familia, nome="Cidadão fictício A")
        self.tipo = TipoBeneficio.objects.create(municipio=self.municipio, nome="Tipo fictício", regra_local="Critério de teste, sem teor normativo.", vigencia_inicio=timezone.localdate())
        self.material = Material.objects.create(municipio=self.municipio, nome="Material fictício", unidade="un")

    def pedido(self, quantidade="5"):
        return PedidoMaterial.objects.create(
            municipio=self.municipio, familia=self.familia, cidadao=self.cidadao,
            material=self.material, quantidade_solicitada=Decimal(quantidade), responsavel=self.usuario,
            justificativa="Solicitação fictícia",
        )

    def aprovar_pedido(self, pedido):
        decidir_pedido(pedido.pk, self.municipio, self.usuario, "analise", "Início da avaliação.")
        return decidir_pedido(pedido.pk, self.municipio, self.usuario, "aprovado", "Critérios conferidos.", pedido.quantidade_solicitada)

    def test_beneficio_regra_preservada_e_decisoes_motivadas(self):
        objeto = solicitar_beneficio(SolicitacaoBeneficio(
            municipio=self.municipio, familia=self.familia, cidadao=self.cidadao, tipo=self.tipo,
            quantidade_solicitada=Decimal("3"), valor_solicitado=Decimal("90")), self.usuario)
        self.tipo.regra_local = "Novo texto fictício"
        self.tipo.save()
        self.assertNotEqual(objeto.regra_aplicada["regra_local"], self.tipo.regra_local)
        with self.assertRaises(ValidationError):
            decidir_beneficio(objeto.pk, self.municipio, self.usuario, "analise", "")
        decidir_beneficio(objeto.pk, self.municipio, self.usuario, "analise", "Recebido pela equipe.")
        with self.assertRaises(ValidationError):
            decidir_beneficio(objeto.pk, self.municipio, self.usuario, "aprovado", "Teste", Decimal("2"), Decimal("60"))
        decidir_beneficio(objeto.pk, self.municipio, self.usuario, "parcial", "Análise fictícia fundamentada.", Decimal("2"), Decimal("60"))
        objeto = decidir_beneficio(objeto.pk, self.municipio, self.usuario, "entregue", "Recibo fictício 001")
        self.assertIsNotNone(objeto.entregue_em)
        self.assertEqual(objeto.quantidade_aprovada, Decimal("2"))
        self.assertEqual(objeto.historico.count(), 4)
        with self.assertRaises(ValidationError):
            decidir_beneficio(objeto.pk, self.municipio, self.usuario, "entregue", "Repetição")

    def test_tipo_fora_de_vigencia_nao_gera_solicitacao(self):
        self.tipo.ativo = False
        self.tipo.save()
        with self.assertRaises(ValidationError):
            solicitar_beneficio(SolicitacaoBeneficio(municipio=self.municipio, familia=self.familia, tipo=self.tipo, quantidade_solicitada=1), self.usuario)
        self.assertEqual(SolicitacaoBeneficio.objects.count(), 0)

    def test_estoque_limites_entrega_e_repeticao(self):
        chave = uuid.uuid4()
        movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("6"), "Nota fictícia", chave=chave)
        repetida = movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("6"), "Nota fictícia", chave=chave)
        self.assertEqual(repetida.pk, chave)
        pedido = self.aprovar_pedido(self.pedido())
        entrega = uuid.uuid4()
        movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("5"), "Recibo fictício", tipo="saida", pedido_id=pedido.pk, chave=entrega)
        movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("5"), "Recibo fictício", tipo="saida", pedido_id=pedido.pk, chave=entrega)
        self.material.refresh_from_db()
        pedido.refresh_from_db()
        self.assertEqual(self.material.saldo, Decimal("1"))
        self.assertEqual(pedido.entregue, Decimal("5"))
        self.assertEqual(pedido.situacao, "entregue")
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        outro_pedido = self.aprovar_pedido(self.pedido())
        with self.assertRaises(ValidationError):
            movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("5"), "Recibo 2", tipo="saida", pedido_id=outro_pedido.pk)
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        outro_pedido.refresh_from_db()
        self.assertEqual(outro_pedido.entregue, 0)

    def test_entregas_concorrentes_nao_geram_saldo_negativo(self):
        if connection.vendor != "postgresql":
            self.skipTest("A garantia concorrente é testada no PostgreSQL.")
        movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("5"), "Entrada concorrente")
        pedidos = [self.aprovar_pedido(self.pedido()) for _ in range(2)]
        barreira = Barrier(2)

        def entregar(pk):
            close_old_connections()
            try:
                barreira.wait(timeout=10)
                movimentar_estoque(self.municipio, self.usuario, self.material.pk, Decimal("5"), "Entrega concorrente", tipo="saida", pedido_id=pk)
                return "entregue"
            except ValidationError:
                return "sem_saldo"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(entregar, [p.pk for p in pedidos]))
        self.assertCountEqual(resultados, ["entregue", "sem_saldo"])
        self.material.refresh_from_db()
        self.assertEqual(self.material.saldo, 0)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 1)

    def test_vale_ativacao_suspensao_historico(self):
        concessao = ConcessaoVale.objects.create(municipio=self.municipio, familia=self.familia, cidadao=self.cidadao, valor=Decimal("100"), periodicidade="mensal", responsavel=self.usuario)
        alterar_vale(concessao.pk, self.municipio, self.usuario, "ativo", Decimal("100"), "mensal", "Análise fictícia concluída.")
        atualizado = alterar_vale(concessao.pk, self.municipio, self.usuario, "suspenso", Decimal("100"), "mensal", "Reavaliação fictícia.")
        self.assertEqual(atualizado.situacao, "suspenso")
        self.assertIsNotNone(atualizado.incluido_em)
        self.assertEqual(atualizado.historico.count(), 2)

    def test_formulario_recusa_familia_e_tipo_de_outro_municipio(self):
        familia_b = Familia.objects.create(municipio=self.outro, referencia="Família fictícia B")
        form = BeneficioForm({"familia": str(familia_b.pk), "tipo": str(self.tipo.pk), "solicitado_em": timezone.localdate().isoformat(), "quantidade_solicitada": "1", "valor_solicitado": "0"}, municipio=self.municipio)
        self.assertFalse(form.is_valid())
        self.assertIn("familia", form.errors)

    @override_settings(TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": False,
        "OPTIONS": {"loaders": [
            ("django.template.loaders.locmem.Loader", {"app_shell.html": "{% block conteudo %}{% endblock %}"}),
            "django.template.loaders.app_directories.Loader",
        ]},
    }])
    def test_listas_e_formularios_renderizam_e_gravam(self):
        from . import views
        fabrica = RequestFactory()
        vinculo = Vinculo.objects.create(usuario=self.usuario, municipio=self.municipio, perfil="tecnico")

        def request(path, dados=None):
            req = fabrica.post(path, dados) if dados is not None else fabrica.get(path)
            req.user, req.vinculo, req.municipio = self.usuario, vinculo, self.municipio
            return req

        with patch("programas.views.registrar_evento"), patch("programas.views.messages.success"), patch("programas.views.tem_permissao", return_value=True):
            resposta = views.beneficio_novo.__wrapped__(request("/", {
                "familia": self.familia.pk, "cidadao": self.cidadao.pk, "tipo": self.tipo.pk,
                "solicitado_em": timezone.localdate().isoformat(), "quantidade_solicitada": "2", "valor_solicitado": "0",
            }))
            self.assertEqual(resposta.status_code, 302)
            self.assertEqual(SolicitacaoBeneficio.objects.count(), 1)
            for view in [views.beneficios, views.pedidos, views.vales, views.estoque, views.tipos,
                         views.beneficio_novo, views.pedido_novo, views.vale_novo, views.material_novo, views.tipo_novo]:
                self.assertEqual(view.__wrapped__(request("/")).status_code, 200)

    def test_formulario_cidadao_de_familia_diferente_recusado(self):
        outra_familia = Familia.objects.create(municipio=self.municipio, referencia="Outra família fictícia")
        form = PedidoForm({"familia": str(outra_familia.pk), "cidadao": str(self.cidadao.pk),
            "material": str(self.material.pk), "solicitado_em": timezone.localdate().isoformat(),
            "quantidade_solicitada": "2", "justificativa": "Teste"}, municipio=self.municipio)
        self.assertFalse(form.is_valid())
        self.assertIn("familia", form.errors)

    def test_rls_na_role_aplicacao(self):
        if connection.vendor != "postgresql":
            self.skipTest("RLS exige PostgreSQL.")
        Material.objects.create(municipio=self.outro, nome="Outro município", unidade="un")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(self.municipio.pk)])
                cursor.execute("SET LOCAL ROLE social_app")
            try:
                self.assertEqual(Material.objects.count(), 1)
                self.assertFalse(Material.objects.filter(municipio=self.outro).exists())
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")

    def test_lista_projeta_campos_exibidos_sem_parecer_ou_consulta_por_linha(self):
        from django.test.utils import CaptureQueriesContext
        from django.urls import reverse

        Vinculo.objects.create(usuario=self.usuario, municipio=self.municipio, perfil='gestor')
        SolicitacaoBeneficio.objects.bulk_create([SolicitacaoBeneficio(municipio=self.municipio, familia=self.familia,
            cidadao=self.cidadao, tipo=self.tipo, quantidade_solicitada=1, responsavel=self.usuario,
            justificativa_tecnica='Parecer que só deve ser lido na ficha') for _ in range(35)])
        self.client.force_login(self.usuario)
        with CaptureQueriesContext(connection) as consultas:
            resposta = self.client.get(reverse('programas:beneficios'))
        self.assertContains(resposta, self.familia.referencia, count=30)
        self.assertNotContains(resposta, 'Parecer que só deve ser lido na ficha')
        operacionais = [q['sql'] for q in consultas if 'FROM "programas_solicitacaobeneficio"' in q['sql'] and 'COUNT(' not in q['sql']]
        self.assertEqual(len(operacionais), 1)
        self.assertIn('LIMIT 30', operacionais[0])
        for campo in ('regra_local', 'regra_aplicada', 'justificativa_tecnica', 'observacoes'):
            self.assertNotIn(f'"{campo}"', operacionais[0])
