from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase
from contas.models import Secretaria
from .models import Municipio, Vinculo
from .navegacao import contexto


class IdentidadeMunicipalTests(TestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(nome='Município fictício para teste de identidade')
        self.user = get_user_model().objects.create_user('interface-ficticia')
        self.vinculo = Vinculo.objects.create(municipio=self.municipio, usuario=self.user, perfil='tecnico')
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(self.municipio.pk)])
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.request.vinculo = self.vinculo
        self.request.municipio = self.municipio

    def test_sem_configuracao_nao_anuncia_brasao(self):
        self.assertIsNone(contexto(self.request)['brasao_municipal_url'])

    def test_brasao_vazio_nao_cria_imagem_quebrada(self):
        Secretaria.objects.create(municipio=self.municipio, nome='Secretaria fictícia', brasao=b'')
        self.assertIsNone(contexto(self.request)['brasao_municipal_url'])

    def test_brasao_configurado_e_sempre_do_municipio_ativo(self):
        Secretaria.objects.create(municipio=self.municipio, nome='Secretaria fictícia', brasao=b'imagem-sintetica-somente-para-teste')
        dados = contexto(self.request)
        self.assertEqual(dados['brasao_municipal_url'], '/contas/brasao/')
        self.assertEqual(dados['orgao_municipal'], 'Secretaria fictícia')
