from decimal import Decimal
from io import BytesIO

from django.test import SimpleTestCase
from openpyxl import load_workbook

from .exportacao import pdf, texto_seguro, xlsx
from .forms import FiltrosRelatorio


class ExportacaoTests(SimpleTestCase):
    def test_excel_preserva_numeros_e_neutraliza_formulas(self):
        tabelas = [{'titulo': 'Famílias', 'colunas': ['Referência', 'Quantidade'],
                    'linhas': [['=HYPERLINK("http://exemplo")', 2], [' @SUM(1)', Decimal('10.50')]]}]
        resposta = xlsx(tabelas, '=Município')
        folha = load_workbook(BytesIO(resposta.content)).active
        self.assertEqual(folha['A1'].data_type, 's')
        self.assertEqual(folha['A3'].data_type, 's')
        self.assertTrue(folha['A3'].value.startswith("'="))
        self.assertEqual(folha['B3'].value, 2)
        self.assertEqual(folha['B4'].value, 10.5)
        self.assertFalse(any(celula.data_type == 'f' for linha in folha for celula in linha))

    def test_pdf_paginado_escapa_texto_livre(self):
        resposta = pdf([{'titulo': 'Atendimentos', 'colunas': ['Unidade', 'Quantidade'],
                         'linhas': [['<script>Teste & validação</script>', 1]]}], 'Município fictício')
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF-'))
        self.assertGreater(len(resposta.content), 800)

    def test_marcadores_de_formula_incluem_controles(self):
        for texto in ['=A1', '+A1', '-A1', '@A1', '\tA1', '\rA1', '\nA1']:
            with self.subTest(texto=texto):
                self.assertTrue(texto_seguro(texto).startswith("'"))


class FiltrosTests(SimpleTestCase):
    def test_intervalo_invertido_e_rejeitado(self):
        form = FiltrosRelatorio({'inicio': '2025-02-10', 'fim': '2025-02-01'})
        self.assertFalse(form.is_valid())
        self.assertIn('fim', form.errors)

    def test_filtros_vazios_permitidos(self):
        form = FiltrosRelatorio({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['fim'], timezone.localdate())


from datetime import datetime
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from atendimentos.models import Atendimento, Auditoria, Cidadao, Familia, Municipio, Vinculo
from cadastros.models import AcompanhamentoAtendimento, ComplementoFamilia
from contas.models import AjustePermissao


@override_settings(SECURE_SSL_REDIRECT=False)
class RelatoriosIntegracaoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.municipio = Municipio.objects.create(nome='Município A fictício')
        cls.outro = Municipio.objects.create(nome='Município B fictício')
        cls.usuario = get_user_model().objects.create_user(username='coordenador-relatorios', password='ficticia')
        cls.vinculo = Vinculo.objects.create(usuario=cls.usuario, municipio=cls.municipio, perfil='coordenador')
        cls.familia = Familia.objects.create(municipio=cls.municipio, referencia='Família Norte A')
        cls.pessoa = Cidadao.objects.create(municipio=cls.municipio, familia=cls.familia, nome='Pessoa A autorizada')
        ComplementoFamilia.objects.create(municipio=cls.municipio, familia=cls.familia, bairro='Norte')
        familia_b = Familia.objects.create(municipio=cls.outro, referencia='Família B restrita')
        pessoa_b = Cidadao.objects.create(municipio=cls.outro, familia=familia_b, nome='Pessoa B de outro município')
        cls.atendimento = Atendimento.objects.create(municipio=cls.municipio, cidadao=cls.pessoa, unidade='Unidade A', encaminhamento='Fictício')
        data = timezone.make_aware(datetime(2025, 4, 12, 10))
        AcompanhamentoAtendimento.objects.create(municipio=cls.municipio, atendimento=cls.atendimento, data_efetiva=data, sigiloso=False)
        sigiloso = Atendimento.objects.create(municipio=cls.municipio, cidadao=cls.pessoa, unidade='Unidade restrita', encaminhamento='Fictício')
        AcompanhamentoAtendimento.objects.create(municipio=cls.municipio, atendimento=sigiloso, data_efetiva=data, sigiloso=True)
        Atendimento.objects.create(municipio=cls.outro, cidadao=pessoa_b, unidade='Unidade B restrita', encaminhamento='Fictício')

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_relatorio_filtra_municipio_sigilo_e_periodo(self):
        resposta = self.client.get(reverse('relatorios:inicio'), {'inicio': '2025-04-01', 'fim': '2025-04-30', 'nominal': 'on', 'bairro': 'Norte'})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Pessoa A autorizada')
        self.assertNotContains(resposta, 'Pessoa B de outro município')
        self.assertNotContains(resposta, 'Unidade restrita')
        tabelas = {item['titulo']: item for item in resposta.context['tabelas']}
        serie = tabelas['Atendimentos por mês — data efetiva ou registro legado']['linhas']
        self.assertEqual(serie, [('04/2025', 1)])
        vazio = self.client.get(reverse('relatorios:inicio'), {'inicio': '2025-05-01', 'fim': '2025-05-31'})
        tabela = next(item for item in vazio.context['tabelas'] if item['titulo'].startswith('Atendimentos por mês'))
        self.assertEqual(tabela['linhas'], [])

    def test_perfil_sem_financeiro_nao_executa_consulta_financeira(self):
        self.vinculo.perfil = 'gestor'
        self.vinculo.save(update_fields=['perfil'])
        AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo,
                                      codigo='gestao.ver', permitido=True)
        with patch('relatorios.views.relatorio_financeiro') as consulta:
            resposta = self.client.get(reverse('relatorios:inicio'))
        self.assertEqual(resposta.status_code, 200)
        consulta.assert_not_called()
        self.assertNotContains(resposta, 'Saldo financeiro')

    def test_exportacao_nominal_e_auditada_e_nao_inclui_outro_municipio(self):
        resposta = self.client.get(reverse('relatorios:inicio'), {'formato': 'xlsx', 'nominal': 'on'})
        self.assertEqual(resposta.status_code, 200)
        livro = load_workbook(BytesIO(resposta.content))
        valores = [str(c.value) for folha in livro for linha in folha for c in linha]
        self.assertIn('Pessoa A autorizada', valores)
        self.assertNotIn('Pessoa B de outro município', valores)
        self.assertTrue(Auditoria.objects.filter(municipio=self.municipio, usuario=self.usuario,
                                                evento='exportacao_relatorios_xlsx_nominal').exists())

    def test_exportacao_recusada_sem_direito(self):
        AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo,
                                      codigo='relatorios.exportar', permitido=False)
        self.assertEqual(self.client.get(reverse('relatorios:inicio'), {'formato': 'pdf'}).status_code, 403)

    def test_dados_nominais_recusados_sem_cadastros(self):
        AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo,
                                      codigo='cadastros.ver', permitido=False)
        resposta = self.client.get(reverse('relatorios:inicio'), {'formato': 'xlsx', 'nominal': 'on'})
        self.assertEqual(resposta.status_code, 403)

    def test_alertas_reais_e_restritos(self):
        resposta = self.client.get(reverse('relatorios:alertas'))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Cidadãos sem complemento')
        self.assertNotContains(resposta, 'Empenhos com liquidação pendente')
        self.assertTrue(Auditoria.objects.filter(municipio=self.municipio, usuario=self.usuario,
                                                evento='consulta_alertas').exists())

    def test_relatorio_financeiro_reutiliza_saldos_do_modulo(self):
        from financeiro.consultas import resumo_financeiro
        from financeiro.models import Dotacao, Exercicio, Fonte, Fundo, Natureza, Programa, Receita
        AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo,
                                      codigo='financeiro.ver', permitido=True)
        base = {'municipio': self.municipio, 'responsavel': self.usuario}
        fonte = Fonte.objects.create(**base, codigo='F1', nome='Fonte de teste', origem='municipal', finalidade='Fictícia')
        fundo = Fundo.objects.create(**base, codigo='FM', nome='Fundo fictício')
        programa = Programa.objects.create(**base, codigo='P1', nome='Programa fictício')
        natureza = Natureza.objects.create(**base, codigo='N1', nome='Natureza fictícia')
        exercicio = Exercicio.objects.create(**base, ano=2025)
        dotacao = Dotacao.objects.create(**base, codigo='D1', fonte=fonte, fundo=fundo, programa=programa,
                                         natureza=natureza, exercicio=exercicio, valor_inicial=1000, saldo_inicial=100)
        Receita.objects.create(**base, dotacao=dotacao, data='2025-02-10', tipo='recebida', valor=200,
                               origem='Origem fictícia', documento='REC1')
        resposta = self.client.get(reverse('relatorios:inicio'), {'ano': '2025', 'mes': '2', 'fonte': str(fonte.pk)})
        self.assertEqual(resposta.status_code, 200)
        resumo = resumo_financeiro(self.municipio, {'ano': 2025, 'mes': 2, 'fonte': fonte})
        financeiro = next(item for item in resposta.context['tabelas'] if item['titulo'] == 'Execução financeira no corte selecionado')
        self.assertEqual(dict(financeiro['linhas'])['Saldo financeiro'], resumo['saldo_financeiro'])
        self.assertEqual(dict(financeiro['linhas'])['Saldo financeiro'], Decimal('300'))
        self.assertContains(resposta, 'Fonte de teste')

    def test_alertas_de_programas_sao_calculados_com_pendencias(self):
        from programas.models import Material, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio
        tipo = TipoBeneficio.objects.create(municipio=self.municipio, nome='Benefício fictício',
                                           regra_local='Norma fictícia para teste', vigencia_inicio='2025-01-01')
        SolicitacaoBeneficio.objects.create(municipio=self.municipio, familia=self.familia, cidadao=self.pessoa,
                                           tipo=tipo, responsavel=self.usuario, quantidade_solicitada=1,
                                           situacao='analise', solicitado_em='2025-04-01')
        material = Material.objects.create(municipio=self.municipio, nome='Material fictício', unidade='un',
                                            saldo=2, estoque_minimo=5)
        PedidoMaterial.objects.create(municipio=self.municipio, familia=self.familia, cidadao=self.pessoa,
                                      material=material, responsavel=self.usuario, quantidade_solicitada=4,
                                      quantidade_aprovada=3, entregue=1, justificativa='Fictícia', situacao='parcial')
        resposta = self.client.get(reverse('relatorios:alertas'))
        self.assertEqual(resposta.status_code, 200)
        quantidades = {titulo: valor for titulo, valor, destino in resposta.context['alertas']}
        self.assertEqual(quantidades['Benefícios aguardando análise'], 1)
        self.assertEqual(quantidades['Entregas de material pendentes'], 1)
        self.assertEqual(quantidades['Materiais no limite mínimo ou sem saldo'], 1)

    def test_series_compactas_preenchem_meses_e_ocultam_sigilo(self):
        from relatorios.consultas import series_resumidas
        for sigiloso in [False, True]:
            item = Atendimento.objects.create(municipio=self.municipio, cidadao=self.pessoa,
                                               unidade='Teste da série', encaminhamento='Fictício')
            AcompanhamentoAtendimento.objects.create(municipio=self.municipio, atendimento=item,
                                                      data_efetiva=timezone.now(), sigiloso=sigiloso)
        series = series_resumidas(self.municipio, self.vinculo)
        mensal = next(serie for serie in series if serie['titulo'] == 'Atendimentos por mês')
        self.assertEqual(len(mensal['linhas']), 6)
        self.assertEqual(mensal['linhas'][-1][1], 1)
        self.assertNotIn('Despesas pagas por programa', [serie['titulo'] for serie in series])
        bairros = next(serie for serie in series if serie['titulo'] == 'Distribuição territorial dos atendimentos')
        self.assertEqual(bairros['linhas'], [('Norte', 1)])

    def test_contagem_documental_exclui_documentos_sigilosos(self):
        from uuid import uuid4
        from documentos.models import Documento, Versao
        from programas.models import SolicitacaoBeneficio, TipoBeneficio
        from relatorios.documentais import alertas_documentais
        tipo = TipoBeneficio.objects.create(municipio=self.municipio, nome='Teste documental',
                                           regra_local='Norma fictícia', vigencia_inicio='2025-01-01')
        beneficio = SolicitacaoBeneficio.objects.create(municipio=self.municipio, familia=self.familia,
                                                       tipo=tipo, responsavel=self.usuario, quantidade_solicitada=1)
        for sigiloso in [False, True]:
            documento = Documento.objects.create(municipio=self.municipio, beneficio=beneficio,
                                                  categoria='outro', sigilo_tecnico=sigiloso)
            Versao.objects.create(municipio=self.municipio, documento=documento, sequencia=1,
                                  operacao=uuid4(), nome='Arquivo fictício.pdf', mime='application/pdf',
                                  tamanho=1, sha256='a' * 64, conteudo=b'x', responsavel=self.usuario)
        itens = alertas_documentais(self.municipio, self.vinculo)
        contagens = {titulo: quantidade for titulo, quantidade, destino in itens}
        self.assertEqual(contagens['Documentos aguardando conferência ou regularização'], 1)

    def test_custo_social_nao_duplica_pagamento_por_multiplos_vinculos(self):
        from financeiro.models import Despesa, Dotacao, Exercicio, Fonte, Fundo, Lancamento, Natureza, Programa, VinculoSocial
        from programas.models import ConcessaoVale, SolicitacaoBeneficio, TipoBeneficio
        from relatorios.financeiro import custos_sociais
        base = {'municipio': self.municipio, 'responsavel': self.usuario}
        fonte = Fonte.objects.create(**base, codigo='CF', nome='Fonte fictícia', origem='municipal', finalidade='Teste')
        fundo = Fundo.objects.create(**base, codigo='FM', nome='Fundo fictício')
        programa = Programa.objects.create(**base, codigo='PR', nome='Programa fictício')
        natureza = Natureza.objects.create(**base, codigo='NA', nome='Natureza fictícia')
        exercicio = Exercicio.objects.create(**base, ano=2025)
        dotacao = Dotacao.objects.create(**base, codigo='DC', fonte=fonte, fundo=fundo, programa=programa,
                                         natureza=natureza, exercicio=exercicio, valor_inicial=1000)
        despesa = Despesa.objects.create(**base, dotacao=dotacao, data='2025-04-01', descricao='Teste',
                                         fornecedor='Fictício', categoria='Social', valor=100, documento='D1', processo='P1')
        etapa_anterior = None
        for tipo in ['empenho', 'liquidacao', 'pagamento']:
            etapa_anterior = Lancamento.objects.create(**base, despesa=despesa, tipo=tipo,
                                                       anterior=etapa_anterior, valor=100, data='2025-04-02',
                                                       referencia=tipo, documento='Teste')
        for indice in range(2):
            vale = ConcessaoVale.objects.create(**base, cidadao=self.pessoa, familia=self.familia,
                                                valor=50, periodicidade='mensal')
            VinculoSocial.objects.create(**base, despesa=despesa, vale=vale)
        valores = dict(custos_sociais(self.municipio, {'ano': 2025}))
        self.assertEqual(valores['Vale-Alimentação'], Decimal('100'))
        self.assertEqual(sum(valores.values()), Decimal('100'))
        modalidade = TipoBeneficio.objects.create(municipio=self.municipio, nome='Tipo fictício',
                                                   regra_local='Norma fictícia', vigencia_inicio='2025-01-01')
        beneficio = SolicitacaoBeneficio.objects.create(**base, familia=self.familia, tipo=modalidade, quantidade_solicitada=1)
        VinculoSocial.objects.create(**base, despesa=despesa, beneficio=beneficio)
        valores = dict(custos_sociais(self.municipio, {'ano': 2025}))
        self.assertEqual(valores['Vale-Alimentação'], Decimal('0'))
        self.assertEqual(valores['Compartilhadas entre origens sociais'], Decimal('100'))
        self.assertEqual(sum(valores.values()), Decimal('100'))

    def test_filtro_de_modalidade_de_outro_municipio_e_recusado(self):
        from programas.models import TipoBeneficio
        tipo = TipoBeneficio.objects.create(municipio=self.outro, nome='Tipo externo restrito',
                                           regra_local='Norma fictícia', vigencia_inicio='2025-01-01')
        resposta = self.client.get(reverse('relatorios:inicio'), {'modalidade': str(tipo.pk), 'formato': 'xlsx'})
        self.assertEqual(resposta.status_code, 400)
        self.assertNotContains(resposta, 'Tipo externo restrito', status_code=400)

    def test_home_fornece_os_seis_graficos_do_escopo_por_permissao(self):
        from relatorios.consultas import series_resumidas
        AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo,
                                      codigo='financeiro.ver', permitido=True)
        series = series_resumidas(self.municipio, self.vinculo)
        self.assertEqual({serie['titulo'] for serie in series}, {
            'Atendimentos por mês', 'Distribuição territorial dos atendimentos',
            'Benefícios concedidos por modalidade', 'Evolução das solicitações',
            'Beneficiários do Vale-Alimentação por bairro', 'Despesas pagas por programa',
        })
        for serie in series:
            self.assertGreaterEqual(serie['maximo'], 1)
            self.assertTrue(serie['descricao'])

    def test_distribuicao_inclui_familias_legadas_sem_bairro(self):
        from relatorios.consultas import relatorio_social
        Familia.objects.create(municipio=self.municipio, referencia='Família sem complemento')
        tabelas = relatorio_social(self.municipio, self.vinculo, {'fim': timezone.localdate()})
        distribuicao = next(item for item in tabelas if item['titulo'] == 'Famílias por bairro')
        self.assertEqual(dict(distribuicao['linhas'])['Bairro não informado'], 1)
        self.assertEqual(sum(valor for nome, valor in distribuicao['linhas']), 2)
