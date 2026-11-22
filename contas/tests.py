import io
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from atendimentos.acesso import tem_permissao
from atendimentos.models import Municipio, Vinculo
from .models import AjustePermissao, EventoAutenticacao, LimiteLogin, Recuperacao
from .permissoes import MATRIZ, permissoes_efetivas
from .services import contexto, validar_concessoes


class PerfisTests(SimpleTestCase):
    def vinculo(self, perfil, ajustes=()):
        return SimpleNamespace(perfil=perfil, usuario=SimpleNamespace(is_active=True), ajustes_permissao=SimpleNamespace(all=lambda: list(ajustes)), pk=1)

    def test_administrador_sem_conteudo_financeiro_sigilo_ou_gestao(self):
        vinculo = self.vinculo("administrador")
        for codigo in ("financeiro.ver", "sigilo.ver", "gestao.ver", "documentos.ver"):
            self.assertFalse(tem_permissao(vinculo, codigo))
        self.assertTrue(tem_permissao(vinculo, "contas.gerir"))
        self.assertTrue(tem_permissao(vinculo, "configuracao.editar"))

    def test_painel_comum_e_gestao_expressa(self):
        for perfil in MATRIZ:
            self.assertTrue(tem_permissao(self.vinculo(perfil), "painel.ver"))
            self.assertFalse(tem_permissao(self.vinculo(perfil), "gestao.ver"))
        ajuste = SimpleNamespace(codigo="gestao.ver", permitido=True)
        self.assertTrue(tem_permissao(self.vinculo("gestor", [ajuste]), "gestao.ver"))
        self.assertFalse(tem_permissao(self.vinculo("administrador", [ajuste]), "gestao.ver"))

    def test_rebaixamento_de_perfil_invalida_cache_do_painel_exclusivo(self):
        ajuste = SimpleNamespace(codigo="gestao.ver", permitido=True)
        vinculo = self.vinculo("gestor", [ajuste])
        self.assertTrue(tem_permissao(vinculo, "gestao.ver"))
        vinculo.perfil = "consulta"
        self.assertFalse(tem_permissao(vinculo, "gestao.ver"))

    def test_conteudo_tecnico_depende_de_sigilo(self):
        negacao = SimpleNamespace(codigo="sigilo.ver", permitido=False)
        self.assertTrue(tem_permissao(self.vinculo("assistente"), "beneficios.tecnico"))
        self.assertFalse(tem_permissao(self.vinculo("assistente", [negacao]), "beneficios.tecnico"))

    def test_negacao_de_consulta_remove_edicao_efetiva(self):
        negacao = SimpleNamespace(codigo="financeiro.ver", permitido=False)
        vinculo = self.vinculo("financeiro", [negacao])
        self.assertFalse(tem_permissao(vinculo, "financeiro.ver"))
        self.assertFalse(tem_permissao(vinculo, "financeiro.editar"))

    def test_permissoes_cacheadas_por_vinculo(self):
        vinculo = self.vinculo("consulta")
        with patch.object(vinculo.ajustes_permissao, "all", wraps=vinculo.ajustes_permissao.all) as consulta:
            tem_permissao(vinculo, "cadastros.ver")
            tem_permissao(vinculo, "atendimentos.ver")
            consulta.assert_called_once()

    def test_administrador_nao_concede_financeiro_ou_sigilo(self):
        admin = self.vinculo("administrador")
        self.assertIsNotNone(validar_concessoes(admin, None, "financeiro", [], []))
        self.assertIsNotNone(validar_concessoes(admin, None, "assistente", [], []))
        self.assertIsNone(validar_concessoes(admin, None, "atendente", [], []))
        self.assertIsNotNone(validar_concessoes(admin, admin, "financeiro", [], []))


@override_settings(
    ROOT_URLCONF="contas.urls", LOGIN_REDIRECT_URL="/", SECURE_SSL_REDIRECT=False,
    TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": False,
        "OPTIONS": {"loaders": [
            ("django.template.loaders.locmem.Loader", {"app_shell.html": "{% block conteudo %}{% endblock %}"}),
            "django.template.loaders.app_directories.Loader"],
            "context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}],
)
class ContasBancoTests(TransactionTestCase):
    reset_sequences = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.urls import include, path
        cls.urls = ModuleType("contas_test_urls")
        cls.urls.urlpatterns = [path("contas/", include("contas.urls"))]

    def setUp(self):
        self.urls_override = override_settings(ROOT_URLCONF=self.urls)
        self.urls_override.enable()
        self.addCleanup(self.urls_override.disable)
        self.municipio = Municipio.objects.create(nome="Município fictício A")
        self.outro = Municipio.objects.create(nome="Município fictício B")
        self.admin = get_user_model().objects.create_user("admin-ficticio", password="SenhaFicticia123!")
        self.vinculo = Vinculo.objects.create(usuario=self.admin, municipio=self.municipio, perfil="administrador")
        self.alvo = get_user_model().objects.create_user("alvo-ficticio", password="SenhaFicticia123!")
        self.alvo_vinculo = Vinculo.objects.create(usuario=self.alvo, municipio=self.municipio, perfil="atendente")
        self.externo = get_user_model().objects.create_user("externo-ficticio", password="SenhaFicticia123!")
        self.externo_vinculo = Vinculo.objects.create(usuario=self.externo, municipio=self.outro, perfil="atendente")
        self.client.force_login(self.admin)

    def app_role(self):
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE social_app")
        self.addCleanup(self.reset_role)

    def reset_role(self):
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")

    def test_login_sem_next_respeita_pagina_inicial_configurada(self):
        self.client.logout()
        self.app_role()
        resposta = self.client.post(reverse("contas:entrar"), {"username": self.admin.username, "password": "SenhaFicticia123!"})
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta["Location"], "/")

    def test_login_preserva_next_local_e_recusa_destino_externo(self):
        self.client.logout()
        self.app_role()
        resposta = self.client.post(reverse("contas:entrar") + "?next=/contas/senha/", {"username": self.admin.username, "password": "SenhaFicticia123!"})
        self.assertEqual(resposta["Location"], "/contas/senha/")
        self.client.logout()
        resposta = self.client.post(reverse("contas:entrar") + "?next=https://example.invalid/", {"username": self.admin.username, "password": "SenhaFicticia123!"})
        self.assertEqual(resposta["Location"], "/")

    def test_criacao_conta_nominal_sem_senha_admin_e_link_pessoal(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:novo"), {
            "username": "novo-ficticio", "nome": "Profissional fictício", "email": "profissional@example.invalid", "perfil": "atendente",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "#")
        usuario = get_user_model().objects.get(username="novo-ficticio")
        self.assertFalse(usuario.has_usable_password())

    def test_conta_outro_municipio_indisponivel(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:acao", args=[self.externo_vinculo.pk]), {"acao": "desativar"})
        self.assertEqual(resposta.status_code, 404)
        self.externo.refresh_from_db()
        self.assertTrue(self.externo.is_active)

    def test_leitura_de_profissional_sem_travar_equipe(self):
        self.app_role()
        with CaptureQueriesContext(connection) as consultas:
            resposta = self.client.get(reverse("contas:profissional", args=[self.alvo_vinculo.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(any("FOR UPDATE" in consulta["sql"] for consulta in consultas))

    def test_delegacao_sensivel_negada_mesmo_com_contas_gerir(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:novo"), {"username": "novo-ficticio", "nome": "Profissional fictício", "perfil": "financeiro"})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="novo-ficticio").exists())

    def test_desativacao_revoga_sessao(self):
        outro_cliente = Client()
        outro_cliente.force_login(self.alvo)
        self.app_role()
        resposta = self.client.post(reverse("contas:acao", args=[self.alvo_vinculo.pk]), {"acao": "desativar"})
        self.assertEqual(resposta.status_code, 302)
        self.alvo.refresh_from_db()
        self.assertFalse(self.alvo.is_active)
        self.assertEqual(outro_cliente.get(reverse("contas:inicio")).status_code, 302)

    def test_troca_senha_com_permissao_minima_banco(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:senha"), {"old_password": "SenhaFicticia123!", "new_password1": "OutraSenhaFicticia123!", "new_password2": "OutraSenhaFicticia123!"})
        self.assertEqual(resposta.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("OutraSenhaFicticia123!"))
        self.assertEqual(self.client.get(reverse("contas:inicio")).status_code, 200)

    def test_limite_login_persistente_e_eventos_sem_nome(self):
        self.client.logout()
        self.app_role()
        for _ in range(8):
            self.client.post(reverse("contas:entrar"), {"username": "nome-inexistente-ficticio", "password": "incorreta"})
        resposta = self.client.post(reverse("contas:entrar"), {"username": "nome-inexistente-ficticio", "password": "incorreta"})
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(LimiteLogin.objects.count(), 1)
        self.reset_role()
        eventos = EventoAutenticacao.objects.filter(evento="login_falhou")
        self.assertEqual(eventos.count(), 8)
        self.assertTrue(all(len(e.conta_resumo) == 40 for e in eventos))

    def test_link_reset_uso_unico_funciona_sem_expor_segredo_na_url_servidor(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:acao", args=[self.alvo_vinculo.pk]), {"acao": "redefinir"})
        self.assertEqual(resposta.status_code, 200)
        comprovante = resposta.context["link"].split("#", 1)[1]
        publico = Client()
        payload = {"comprovante": comprovante, "new_password1": "SenhaNovaFicticia123!", "new_password2": "SenhaNovaFicticia123!"}
        self.assertEqual(publico.post(reverse("contas:acesso"), payload).status_code, 302)
        self.alvo.refresh_from_db()
        self.assertTrue(self.alvo.check_password("SenhaNovaFicticia123!"))
        self.assertEqual(publico.post(reverse("contas:acesso"), payload).status_code, 200)
        self.assertContains(publico.post(reverse("contas:acesso"), payload), "Link indisponível")

    def test_brasao_rejeita_svg_e_isola_imagem_reencodada(self):
        from PIL import Image
        self.app_role()
        svg = SimpleUploadedFile("brasao.svg", b"<svg><script>alert(1)</script></svg>", content_type="image/svg+xml")
        resposta = self.client.post(reverse("contas:configurar"), {"nome": "Secretaria fictícia", "imagem_brasao": svg})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "imagem PNG ou JPEG válida")
        arquivo = io.BytesIO()
        Image.new("RGB", (20, 20), "blue").save(arquivo, format="PNG")
        imagem = SimpleUploadedFile("brasao.png", arquivo.getvalue(), content_type="image/png")
        self.assertEqual(self.client.post(reverse("contas:configurar"), {"nome": "Secretaria fictícia", "imagem_brasao": imagem}).status_code, 302)
        resposta = self.client.get(reverse("contas:brasao"))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "image/png")
        self.assertIn("no-store", resposta["Cache-Control"])
        original = resposta.content
        configuracao = reverse("contas:configurar")
        self.assertContains(self.client.get(configuracao), "Remover o brasão atual")
        self.assertEqual(self.client.post(configuracao, {"nome": "Secretaria Renomeada"}).status_code, 302)
        self.assertEqual(self.client.get(reverse("contas:brasao")).content, original)
        self.client.force_login(self.externo)
        self.assertEqual(self.client.get(reverse("contas:brasao")).status_code, 404)

    @override_settings(CONTAS_SMTP_ATIVO=False)
    def test_recuperacao_publica_sem_smtp_preserva_link_manual(self):
        self.app_role()
        resposta = self.client.post(reverse("contas:acao", args=[self.alvo_vinculo.pk]), {"acao": "redefinir"})
        comprovante = resposta.context["link"].split("#", 1)[1]
        publico = Client()
        self.assertEqual(publico.post(reverse("contas:recuperar"), {"username": self.alvo.username}).status_code, 200)
        self.assertEqual(publico.post(reverse("contas:acesso"), {"comprovante": comprovante, "new_password1": "SenhaNovaFicticia123!", "new_password2": "SenhaNovaFicticia123!"}).status_code, 302)

    def test_gestao_exige_comando_explicito_e_preserva_senha(self):
        usuario = get_user_model().objects.create_user("gestor.vexo", password="SenhaFicticia123!")
        vinculo = Vinculo.objects.create(usuario=usuario, municipio=self.municipio, perfil="gestor")
        senha = usuario.password
        call_command("habilitar_acesso", usuario="gestor.vexo", municipio_id=self.municipio.pk, conceder=["gestao.ver"], confirmar_autorizacao=True, confirmar_piloto=True, stdout=io.StringIO())
        usuario.refresh_from_db()
        self.assertEqual(usuario.password, senha)
        with transaction.atomic():
            contexto(self.municipio.pk)
            self.assertTrue(tem_permissao(vinculo, "gestao.ver"))
