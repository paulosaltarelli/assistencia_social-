from django.test import SimpleTestCase
from .forms import ProfissionalForm
from .permissoes import DELEGACOES, PERMISSOES
from .templatetags.contas_ui import grupos_acesso


class ApresentacaoPermissoesTests(SimpleTestCase):
    def test_grupos_preservam_todos_codigos_editaveis_sem_delegacao(self):
        grupos = grupos_acesso(ProfissionalForm())
        codigos = [linha['codigo'] for grupo in grupos for linha in grupo['linhas']]
        esperados = set(PERMISSOES) - DELEGACOES - {'painel.ver'}
        self.assertEqual(set(codigos), esperados)
        self.assertEqual(len(codigos), len(esperados))

    def test_matriz_mostra_base_do_perfil_e_ajustes_sem_conceder_acessos(self):
        form = ProfissionalForm(initial={
            'perfil': 'administrador',
            'permitir': ['cadastros.ver'],
            'negar': ['configuracao.editar'],
        })
        linhas = {linha['codigo']: linha for grupo in grupos_acesso(form) for linha in grupo['linhas']}
        self.assertFalse(linhas['financeiro.ver']['incluido'])
        self.assertTrue(linhas['contas.gerir']['incluido'])
        self.assertTrue(linhas['cadastros.ver']['permitido'])
        self.assertTrue(linhas['configuracao.editar']['negado'])
        self.assertFalse(linhas['cadastros.ver']['incluido'])
