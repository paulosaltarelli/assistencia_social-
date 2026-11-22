from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from atendimentos.demonstracao.carga import Contexto, configurar_periodo
from atendimentos.demonstracao.enderecos import atualizar_enderecos
from atendimentos.models import Familia, Municipio, Vinculo
from cadastros.localidades import pares_e_bairros
from cadastros.models import AtualizacaoCadastro, ComplementoFamilia


REFERENCIA = {
    'fontes': [{'id': 'teste'}],
    'bairros': [{'nome': 'Bairro de teste', 'fonte_id': 'teste'}],
    'logradouros': [
        {'logradouro': 'Rua de teste', 'bairro': 'Bairro de teste', 'fonte_id': 'teste'},
        {'logradouro': 'Rua sem bairro', 'bairro': '', 'fonte_id': 'teste'},
        {'logradouro': 'Rua sem fonte', 'bairro': 'Outro bairro', 'fonte_id': 'ausente'},
    ],
}


@override_settings(SOCIAL_HOMOLOGACAO=True)
class LocalidadesTests(TestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(nome='Santa Cruz de Minas')
        self.user = get_user_model().objects.create_user('autor-sintetico')
        Vinculo.objects.create(usuario=self.user, municipio=self.mun, perfil='tecnico')
        self.c = Contexto(self.mun, self.user, date(2026, 11, 22))
        self.client.force_login(self.user)
        configurar_periodo(self.c)

    def legado(self, numero, rua, bairro):
        familia, _ = self.c.criar(Familia, f'familia/{numero}', referencia=f'Família de teste {numero}')
        return self.c.criar(ComplementoFamilia, f'familia/dados/{numero}', familia=familia,
                            cidade='Santa Cruz de Minas', endereco=rua, bairro=bairro, numero=str(numero))[0]

    @patch('cadastros.localidades.catalogo_municipal', return_value=REFERENCIA)
    def test_selecao_em_santa_cruz_e_digitacao_manual(self, _):
        pares, bairros = pares_e_bairros(self.mun)
        self.assertEqual(len(pares), 1)
        self.assertEqual(bairros, ['Bairro de teste'])
        url = reverse('cadastros:familia_nova')
        self.assertContains(self.client.get(url), 'Rua de teste · Bairro de teste')
        resposta = self.client.post(url, {'referencia': 'Ficha sintética', 'endereco_catalogo': next(iter(pares)), 'numero': 'S/N'})
        self.assertEqual(resposta.status_code, 302)
        ficha = ComplementoFamilia.objects.get(municipio=self.mun)
        self.assertEqual((ficha.endereco, ficha.bairro, ficha.cidade), ('Rua de teste', 'Bairro de teste', 'Santa Cruz de Minas'))
        self.assertEqual(self.client.post(reverse('cadastros:familia_editar', args=[ficha.familia_id]), {
            'referencia': 'Ficha sintética', 'endereco': 'Via rural declarada', 'bairro': 'Localidade declarada'}).status_code, 302)
        ficha.refresh_from_db()
        self.assertEqual(ficha.endereco, 'Via rural declarada')
        outro = Municipio.objects.create(nome='Município de teste')
        self.assertEqual(pares_e_bairros(outro), ({}, []))

    @patch('cadastros.localidades.catalogo_municipal', return_value=REFERENCIA)
    def test_enderecos_antigos_so_mudam_com_as_chaves_originais(self, _):
        anterior = self.legado(2, '[SIMULADO] Rua do cenário 002', '[SIMULADO] Setor Amarelo')
        original = self.legado(1, 'Rua do Cedro', 'Jardim das Flores')
        preservado = self.legado(3, 'Rua dos Ipês', 'Alto da Serra')
        AtualizacaoCadastro.objects.create(municipio=self.mun, autor=self.user, objeto=preservado.familia_id, acao='familia_atualizada')
        self.legado(4, 'Rua alterada pela equipe', 'Boa Vista')
        manual = Familia.objects.create(municipio=self.mun, referencia='Família de teste 1')
        ComplementoFamilia.objects.create(familia=manual, municipio=self.mun, endereco='Rua do Cedro', bairro='Jardim das Flores', numero='1')
        self.assertEqual(atualizar_enderecos(self.c, conferir=True)['legadas'], 2)
        self.assertEqual(atualizar_enderecos(self.c)['atualizadas'], 2)
        self.assertEqual(atualizar_enderecos(self.c)['atualizadas'], 0)
        for ficha in (anterior, original):
            ficha.refresh_from_db()
            self.assertEqual(ficha.endereco, 'Rua de teste')
        preservado.refresh_from_db()
        self.assertEqual(preservado.endereco, 'Rua dos Ipês')
        self.assertEqual(manual.complemento.endereco, 'Rua do Cedro')

    @patch('cadastros.localidades.catalogo_municipal', return_value={'fontes': [], 'bairros': [], 'logradouros': []})
    def test_sem_pares_documentados_preserva_o_cadastro(self, _):
        original = self.legado(1, 'Rua do Cedro', 'Jardim das Flores')
        self.assertEqual(atualizar_enderecos(self.c)['atualizadas'], 0)
        original.refresh_from_db()
        self.assertEqual(original.endereco, 'Rua do Cedro')
        self.assertNotContains(self.client.get(reverse('cadastros:familia_nova')), 'id_endereco_catalogo')

    def test_carga_nova_usa_somente_pares_presentes_na_referencia_municipal(self):
        from atendimentos.demonstracao.carga import popular_cadastros
        pares, bairros = pares_e_bairros(self.mun)
        self.assertTrue(pares)
        popular_cadastros(self.c)
        encontrados = list(ComplementoFamilia.objects.filter(municipio=self.mun).values_list('endereco', 'bairro'))
        self.assertEqual(len(encontrados), 80)
        self.assertTrue(set(encontrados) <= {(p['logradouro'], p['bairro']) for p in pares.values()})
        self.assertEqual({bairro for _, bairro in encontrados}, set(bairros))
        self.assertEqual(atualizar_enderecos(self.c)['atualizadas'], 0)
