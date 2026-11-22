from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, SimpleTestCase
from atendimentos.models import Municipio, Vinculo, Familia, Cidadao, Atendimento
from .identificacao import documento, indice
from .models import ComplementoPessoa, ComplementoFamilia, AcompanhamentoAtendimento, NotaTecnica
from . import views


class IdentificacaoTests(SimpleTestCase):
    def test_cpf_valida_digitos_e_normaliza(self):
        self.assertEqual(documento('529.982.247-25', 'cpf'), '52998224725')
        for valor in ['11111111111', '52998224724', 'texto', '123']:
            with self.assertRaises(ValidationError):
                documento(valor, 'cpf')

    def test_indice_separa_municipios_e_documentos(self):
        self.assertNotEqual(indice(1, 'cpf', '52998224725'), indice(2, 'cpf', '52998224725'))
        self.assertNotEqual(indice(1, 'cpf', '52998224725'), indice(1, 'nis', '52998224725'))


class CadastrosTests(TestCase):
    def setUp(self):
        self.municipio = Municipio.objects.create(nome='Município Fictício A')
        self.outro = Municipio.objects.create(nome='Município Fictício B')
        self.user = get_user_model().objects.create_user('profissional-ficticio')
        self.vinculo = Vinculo.objects.create(usuario=self.user, municipio=self.municipio, perfil='tecnico')
        self.familia = Familia.objects.create(municipio=self.municipio, referencia='Família fictícia A')
        self.familia_b = Familia.objects.create(municipio=self.outro, referencia='Família fictícia B')
        self.pessoa = Cidadao.objects.create(municipio=self.municipio, familia=self.familia, nome='Pessoa fictícia')
        self.factory = RequestFactory()
        self.contextos = []
        self.render = patch('cadastros.views.django_render', side_effect=self.capturar_render)
        self.render.start()
        self.addCleanup(self.render.stop)

    def capturar_render(self, request, template, contexto):
        self.contextos.append(contexto)
        return HttpResponse('render')

    def request(self, metodo='get', dados=None):
        request = getattr(self.factory, metodo)('/cadastros/', dados or {})
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_acolhimento_sem_cpf_e_auditoria_sem_valores(self):
        request = self.request('post', {'nome': 'Nome fictício novo', 'familia_id': str(self.familia.pk), 'parentesco': 'Filho'})
        with patch('cadastros.views.redirect', return_value=HttpResponse(status=302)):
            resposta = views.pessoa_form(request)
        self.assertEqual(resposta.status_code, 302)
        nova = Cidadao.objects.get(nome='Nome fictício novo')
        self.assertEqual(nova.complemento.cpf_hash, '')
        self.assertTrue(nova.pk)
        self.assertFalse(nova.complemento.cpf_ultimos)

    def test_edicao_sem_cpf_preserva_documento_inserido_durante_a_edicao(self):
        complemento = ComplementoPessoa.objects.create(municipio=self.municipio, cidadao=self.pessoa)
        novo_indice = indice(self.municipio.pk, 'cpf', '52998224725')
        validar = views.PessoaForm.is_valid

        def validar_apos_preenchimento(form):
            ComplementoPessoa.objects.filter(pk=complemento.pk).update(cpf_hash=novo_indice, cpf_ultimos='4725')
            return validar(form)

        request = self.request('post', {'nome': self.pessoa.nome, 'familia_id': str(self.familia.pk)})
        with patch.object(views.PessoaForm, 'is_valid', validar_apos_preenchimento), patch('cadastros.views.redirect', return_value=HttpResponse(status=302)):
            self.assertEqual(views.pessoa_form(request, pk=self.pessoa.pk).status_code, 302)
        complemento.refresh_from_db()
        self.assertEqual((complemento.cpf_hash, complemento.cpf_ultimos), (novo_indice, '4725'))

    def test_familia_outro_municipio_rejeitada(self):
        response = views.pessoa_form(self.request('post', {'nome': 'Inválido', 'familia_id': str(self.familia_b.pk)}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cidadao.objects.filter(nome='Inválido').exists())
        self.assertTrue(self.contextos[-1]['form'].non_field_errors())

    def test_busca_documento_sem_valor_bruto_na_tela(self):
        ComplementoPessoa.objects.create(municipio=self.municipio, cidadao=self.pessoa, cpf_hash=indice(self.municipio.pk, 'cpf', '52998224725'), cpf_ultimos='4725')
        views.inicio(self.request('post', {'tipo': 'cpf', 'numero': '529.982.247-25'}))
        contexto = self.contextos[-1]
        self.assertEqual(contexto['resultado'].cidadao_id, self.pessoa.pk)
        self.assertFalse(contexto['documento_form'].is_bound)
        self.assertNotIn('52998224725', contexto['resultado'].cpf_mascarado)

    def test_homonimos_ficam_separados(self):
        outra = Cidadao.objects.create(municipio=self.municipio, familia=self.familia, nome=self.pessoa.nome)
        self.assertNotEqual(outra.pk, self.pessoa.pk)
        views.inicio(self.request('get', {'q': self.pessoa.nome}))
        self.assertEqual(self.contextos[-1]['pagina'].paginator.count, 2)

    def test_cpf_duplicado_no_municipio_bloqueado(self):
        ComplementoPessoa.objects.create(municipio=self.municipio, cidadao=self.pessoa, cpf_hash=indice(self.municipio.pk, 'cpf', '52998224725'), cpf_ultimos='4725')
        response = views.pessoa_form(self.request('post', {'nome': 'Tentativa duplicada', 'familia_id': str(self.familia.pk), 'cpf': '52998224725'}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Cidadao.objects.filter(nome='Tentativa duplicada').exists())
        self.assertTrue(self.contextos[-1]['form'].non_field_errors())

    def test_database_rejeita_complemento_com_municipio_errado(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ComplementoPessoa.objects.create(municipio=self.outro, cidadao=self.pessoa)

    def test_sigilo_fora_de_perfil_nao_aparece(self):
        atendimento = Atendimento.objects.create(municipio=self.municipio, cidadao=self.pessoa, unidade='Unidade fictícia', encaminhamento='Resumo')
        AcompanhamentoAtendimento.objects.create(municipio=self.municipio, atendimento=atendimento, sigiloso=True)
        request = self.request()
        request.municipio, request.vinculo = self.municipio, self.vinculo
        self.assertFalse(views.atendimentos_visiveis(request).exists())

    def test_historico_preserva_legados_e_pagina(self):
        Atendimento.objects.bulk_create([Atendimento(municipio=self.municipio, cidadao=self.pessoa, unidade='Unidade fictícia', encaminhamento='Resumo') for _ in range(51)])
        views.atendimentos(self.request('get', {'page': '3'}))
        pagina = self.contextos[-1]['pagina']
        self.assertEqual(pagina.paginator.count, 51)
        self.assertEqual(len(pagina), 1)

    def test_selecao_uuid_invalido_gera_formulario(self):
        response = views.pessoa_form(self.request('get', {'familia': 'invalido'}))
        self.assertEqual(response.status_code, 200)

    def test_role_aplicacao_isola_complementos_e_permite_edicao_minima(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(self.municipio.pk)])
            cursor.execute('SET LOCAL ROLE social_app')
        try:
            complemento = ComplementoPessoa.objects.create(municipio=self.municipio, cidadao=self.pessoa, telefone='Telefone fictício')
            self.assertEqual(ComplementoPessoa.objects.get(pk=complemento.pk).telefone, 'Telefone fictício')
            self.assertFalse(Familia.objects.filter(pk=self.familia_b.pk).exists())
            Cidadao.objects.filter(pk=self.pessoa.pk).update(nome='Nome fictício revisado')
            with self.assertRaises(IntegrityError), transaction.atomic():
                ComplementoPessoa.objects.create(municipio=self.outro, cidadao=self.pessoa)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET ROLE')
