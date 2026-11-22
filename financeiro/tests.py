from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from atendimentos.models import Cidadao, Familia, Municipio, Vinculo
from contas.models import AjustePermissao
from programas.models import ConcessaoVale
from .consultas import execucao_por_grupo, pendentes_de_conferencia, recursos_por_origem, resumo_financeiro
from .demonstracao import popular
from .models import (Compromisso, Despesa, Dotacao, Exercicio, Fonte, Fundo, Historico, Lancamento,
                     Natureza, Programa, Receita, RevisaoOrcamento, VinculoSocial)
from .servicos import atualizar_despesa, cadastrar, executar_etapa


DIA = date(2026, 3, 10)


class ExecucaoFinanceiraTest(TransactionTestCase):
    def setUp(self):
        self.mun = Municipio.objects.create(nome="Município financeiro fictício")
        self.usuario = get_user_model().objects.create_user("operador.ficticio")
        self.vinculo = Vinculo.objects.create(municipio=self.mun, usuario=self.usuario, perfil="financeiro")
        padrao = {"municipio": self.mun, "responsavel": self.usuario}
        classificacao = {"codigo": "T01", "nome": "Classificação fictícia", **padrao}
        self.dotacao = Dotacao.objects.create(
            codigo="D01", exercicio=Exercicio.objects.create(ano=2026, **padrao),
            fonte=Fonte.objects.create(origem="municipal", finalidade="Teste", **classificacao),
            fundo=Fundo.objects.create(**classificacao), programa=Programa.objects.create(**classificacao),
            natureza=Natureza.objects.create(**classificacao), valor_inicial=Decimal("1000"), saldo_inicial=Decimal("30"), **padrao)
        self.despesa = cadastrar(Despesa(dotacao=self.dotacao, data=DIA, descricao="Fornecimento fictício",
                                         processo="PROC-F", fornecedor="Empresa fictícia", categoria="Teste",
                                         documento="NF-F", valor=Decimal("200")), self.mun, self.usuario)

    def etapa(self, tipo, valor, numero, anterior=None, compromisso=None):
        return executar_etapa(Lancamento(despesa=self.despesa, tipo=tipo, data=DIA, valor=Decimal(valor),
                                         referencia=numero, documento="Comprovante fictício",
                                         anterior=anterior, compromisso=compromisso), self.mun, self.usuario)

    def test_estagios_parciais_caixa_e_conversao_unica(self):
        cadastro = {"dotacao": self.dotacao, "data": DIA}
        for tipo, valor, referencia in (("prevista", 250, "PREV"), ("recebida", 200, "REC")):
            cadastrar(Receita(tipo=tipo, valor=valor, origem="Teste", documento=referencia, comprovante="R-1", **cadastro),
                      self.mun, self.usuario)
        compromisso = cadastrar(Compromisso(descricao="Previsão fictícia", referencia="C-F", valor=100,
                                            vencimento=DIA, **cadastro), self.mun, self.usuario)
        self.assertEqual(resumo_financeiro(self.mun, {})["comprometido"], 100)
        emp = self.etapa("empenho", 100, "E1", compromisso=compromisso)
        with self.assertRaises(ValidationError):
            self.etapa("empenho", 100, "E2", compromisso=compromisso)
        liq = self.etapa("liquidacao", 60, "L1", anterior=emp)
        self.etapa("pagamento", 40, "P1", anterior=liq)
        with self.assertRaises(ValidationError):
            self.etapa("pagamento", 21, "P2", anterior=liq)
        with self.assertRaises(ValidationError):
            self.etapa("liquidacao", 41, "L2", anterior=emp)
        resumo = resumo_financeiro(self.mun, {"ano": 2026, "mes": 3})
        self.assertEqual([resumo[k] for k in ("previsto", "recebido", "comprometido", "empenhado", "liquidado",
                                              "pago", "saldo_orcamentario", "saldo_financeiro")],
                         [250, 200, 0, 100, 60, 40, 900, 190])
        self.assertEqual(resumo_financeiro(self.mun, {"ano": 2026, "mes": 2})["pago"], 0)

    def test_anulacao_nao_retorna_saldo_negativo_em_data_intermediaria(self):
        self.etapa("empenho", 150, "E")
        cadastrar(RevisaoOrcamento(dotacao=self.dotacao, data=date(2026, 5, 1), tipo="credito", valor=500,
                                   documento="Lei fictícia", motivo="Teste"), self.mun, self.usuario)
        with self.assertRaises(ValidationError):
            cadastrar(RevisaoOrcamento(dotacao=self.dotacao, data=date(2026, 2, 1), tipo="anulacao", valor=900,
                                       documento="Ato fictício", motivo="Teste"), self.mun, self.usuario)

    def test_concorrencia_duas_ordens_disputam_mesma_liquidacao(self):
        emp = self.etapa("empenho", 100, "E1")
        liq = self.etapa("liquidacao", 60, "L1", anterior=emp)
        barreira = Barrier(2)
        def pagar(numero):
            close_old_connections()
            try:
                barreira.wait(timeout=8)
                self.etapa("pagamento", 40, numero, anterior=liq)
                return "aceito"
            except ValidationError:
                return "saldo insuficiente"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(pagar, ["PA", "PB"]))
        self.assertCountEqual(resultados, ["aceito", "saldo insuficiente"])
        self.assertEqual(resumo_financeiro(self.mun, {})["pago"], 40)

    def test_rls_e_integridade_relacional_entre_municipios(self):
        outro = Municipio.objects.create(nome="Outro município fictício")
        familia = Familia.objects.create(municipio=outro, referencia="Família de teste")
        cidadao = Cidadao.objects.create(municipio=outro, familia=familia, nome="Pessoa de teste")
        vale = ConcessaoVale.objects.create(municipio=outro, cidadao=cidadao, familia=familia, valor=20,
                                            periodicidade="unico", responsavel=self.usuario)
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE social_app")
            cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(outro.pk)])
            self.assertFalse(Despesa.objects.filter(pk=self.despesa.pk).exists())
            with self.assertRaises(IntegrityError), transaction.atomic():
                Receita.objects.create(municipio=outro, responsavel=self.usuario, dotacao_id=self.dotacao.pk,
                                       data=DIA, tipo="prevista", valor=1, origem="Teste", documento="Fora")
            cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(self.mun.pk)])
            with self.assertRaises(IntegrityError), transaction.atomic():
                VinculoSocial.objects.create(municipio=self.mun, responsavel=self.usuario, despesa=self.despesa, vale_id=vale.pk)

    def test_revisao_auditada_optimista(self):
        valores = {k: getattr(self.despesa, k) for k in
                   ("descricao", "categoria", "valor", "fornecedor", "cnpj", "data", "documento", "processo", "observacoes")}
        valores["descricao"] = "Descrição revisada"
        atualizado = atualizar_despesa(self.despesa, valores, self.usuario, 1)
        self.assertEqual(atualizado.versao, 2)
        with self.assertRaises(ValidationError):
            atualizar_despesa(self.despesa, valores, self.usuario, 1)
        historico = list(Historico.objects.filter(objeto=self.despesa.pk).order_by("criado_em").values_list("estado", flat=True))
        self.assertEqual([h["descricao"] for h in historico], ["Fornecimento fictício", "Descrição revisada"])

    def test_formulario_etapa_e_portal_exclusivo(self):
        self.client.force_login(self.usuario)
        dados = {"data": DIA.isoformat(), "referencia": "E-FORM", "valor": "50", "documento": "Ref. fictícia"}
        endereco = reverse("financeiro:etapa", args=[self.despesa.pk, "empenho"])
        self.assertEqual(self.client.post(endereco, dados).status_code, 302)
        self.assertContains(self.client.get(reverse("financeiro:despesa", args=[self.despesa.pk])), "E-FORM")
        self.assertContains(self.client.get(reverse("financeiro:central")), "Fornecimento fictício")
        self.assertContains(self.client.get(reverse("financeiro:inicio")), "Saldo orçamentário")
        self.assertEqual(self.client.get(reverse("financeiro:gestor")).status_code, 403)
        self.vinculo.perfil = "gestor"
        self.vinculo.save(update_fields=["perfil"])
        self.assertEqual(self.client.get(reverse("financeiro:gestor")).status_code, 403)
        for codigo in ["gestao.ver", "financeiro.ver"]:
            AjustePermissao.objects.create(vinculo=self.vinculo, municipio=self.mun, codigo=codigo, permitido=True)
        self.assertContains(self.client.get(reverse("financeiro:gestor")), "Painel do gestor")

    def test_revogacao_de_consulta_bloqueia_tambem_rotas_de_edicao(self):
        AjustePermissao.objects.create(vinculo=self.vinculo, municipio=self.mun, codigo="financeiro.ver", permitido=False)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("financeiro:editar_despesa", args=[self.despesa.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("financeiro:cadastro", args=["exercicios"]), {"ano": "2024"}).status_code, 403)

    def test_criar_despesa_a_partir_de_concessao_autorizada(self):
        familia = Familia.objects.create(municipio=self.mun, referencia="[SIMULADO] Família")
        cidadao = Cidadao.objects.create(municipio=self.mun, familia=familia, nome="[SIMULADO] Pessoa")
        vale = ConcessaoVale.objects.create(municipio=self.mun, familia=familia, cidadao=cidadao,
                                            valor=120, periodicidade="mensal", responsavel=self.usuario)
        self.client.force_login(self.usuario)
        url = reverse("financeiro:nova_despesa", query={"origem_tipo": "vale", "origem_id": vale.pk})
        self.assertContains(self.client.get(url), str(vale.pk))
        dados = {"dotacao": self.dotacao.pk, "data": DIA, "processo": "P-D", "documento": "D-C", "descricao": "Alimento",
                 "categoria": "Teste", "fornecedor": "Simulado", "valor": "120"}
        self.assertEqual(self.client.post(url, dados).status_code, 302)
        despesa = Despesa.objects.get(municipio=self.mun, processo="P-D")
        self.assertTrue(VinculoSocial.objects.filter(despesa=despesa, vale=vale).exists())
        self.assertFalse(despesa.lancamentos.exists())
        AjustePermissao.objects.create(vinculo=self.vinculo, municipio=self.mun, codigo="vale.ver", permitido=False)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_comprovante_de_receita_tem_origem_privada(self):
        receita = cadastrar(Receita(dotacao=self.dotacao, data=DIA, tipo="recebida", valor=60, origem="Fictícia",
                                    documento="R-1", comprovante="REF-1"), self.mun, self.usuario)
        self.client.force_login(self.usuario)
        url = reverse("financeiro:receita", args=[receita.pk])
        acervo = reverse("documentos:vinculo", args=["receita", receita.pk])
        self.assertContains(self.client.get(url), acervo)
        self.assertContains(self.client.get(acervo), "Documentos comprobatórios")
        AjustePermissao.objects.create(vinculo=self.vinculo, municipio=self.mun, codigo="documentos.ver", permitido=False)
        self.assertNotContains(self.client.get(url), acervo)
        self.assertEqual(self.client.get(acervo).status_code, 403)

    def test_carga_demonstrativa_idempotente_por_fonte_e_mes(self):
        contexto = SimpleNamespace(municipio=self.mun, user=self.usuario, homologacao=True, data_referencia=date(2026, 11, 22),
                                   beneficios=[], pedidos=[], vales=[], identificador=lambda chave: uuid5(NAMESPACE_URL, chave))
        primeiro = popular(contexto)
        self.assertEqual(len(primeiro["despesas"]), 36)
        self.assertEqual(primeiro["contagens"]["lancamento"], 72)
        antes = Historico.objects.filter(municipio=self.mun).count()
        self.assertEqual(popular(contexto)["contagens"], {})
        self.assertEqual(antes, Historico.objects.filter(municipio=self.mun).count())
        grupos = execucao_por_grupo(self.mun, {}, "fonte")
        self.assertEqual(len([g for g in grupos if g["recebido"] and g["pagamento"]]), 3)
        self.assertEqual(len(execucao_por_grupo(self.mun, {}, "mes")), 12)
        self.assertTrue(all(v > 0 for _, v in recursos_por_origem(self.mun, {})))
        conjunto = Despesa.objects.filter(pk__in=[d.pk for d in primeiro["despesas"]])
        self.assertEqual(pendentes_de_conferencia(conjunto, None).count(), 30)
