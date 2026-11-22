import hashlib
import io
import json
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader, PdfWriter

from atendimentos.models import Municipio, Vinculo
from financeiro.models import Despesa, Dotacao, Exercicio, Fonte, Fundo, Lancamento, Natureza, Programa, Receita
from contas.models import AjustePermissao
from .arquivos import LIMITE, Original, ScannerIndisponivel, receber, verificar_antivirus, verificar_assinaturas
from .exportacao import lotes_de_versoes, preparar
from .forms import ConferenciaForm, DocumentoForm
from .links import link_original
from .models import Documento, Versao
from .servicos import conferir, documentos_filtrados, duplicidades, guardar_versao, metricas_despesas


def pdf_ficticio():
    buf = io.BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=595, height=842)
    pdf.write(buf)
    return buf.getvalue()


class VerificacaoDeArquivo(SimpleTestCase):
    def test_lotes_de_exportacao_respeitam_bytes_e_quantidade(self):
        tamanhos = [1] * 36 + [LIMITE, LIMITE // 2, LIMITE // 2]
        versoes = [SimpleNamespace(tamanho=tamanho) for tamanho in tamanhos]
        lotes = list(lotes_de_versoes(versoes))
        self.assertEqual([len(lote) for lote in lotes], [32, 4, 1, 2])
        self.assertEqual([v for lote in lotes for v in lote], versoes)
        self.assertTrue(all(sum(v.tamanho for v in lote) <= LIMITE for lote in lotes))

    @patch("documentos.arquivos.verificar_antivirus")
    def test_formatos_preservam_bytes_e_digest(self, scan):
        foto = io.BytesIO()
        Image.new("RGB", (12, 9), color="teal").save(foto, format="PNG")
        for nome, dados, mime in [("nota.pdf", pdf_ficticio(), "application/pdf"),
                                  ("registro.xml", b"<documento>Teste</documento>", "application/xml"),
                                  ("registro.png", foto.getvalue(), "image/png")]:
            with self.subTest(nome=nome):
                original = receber(SimpleUploadedFile(nome, dados))
                self.assertEqual(original.dados, dados)
                self.assertEqual(original.mime, mime)
                self.assertEqual(original.sha256, hashlib.sha256(dados).hexdigest())

    @patch("documentos.arquivos.verificar_antivirus")
    def test_incompleto_nao_chega_ao_acervo(self, scan):
        for nome, dados in [("notas.pdf", b"texto simples"), ("outro.exe", b"texto"),
                            ("foto.png", b"arquivo incompleto"), ("vazio.xml", b"")]:
            with self.subTest(nome=nome), self.assertRaises(ValidationError):
                receber(SimpleUploadedFile(nome, dados))

    def test_dados_av_e_conferencia(self):
        with patch("documentos.arquivos.socket.create_connection", side_effect=TimeoutError):
            with self.assertRaises(ScannerIndisponivel):
                verificar_antivirus(b"dados de teste")
        self.assertFalse(ConferenciaForm({"situacao": "pendencia"}).is_valid())
        self.assertTrue(ConferenciaForm({"situacao": "pendencia", "motivo": "Solicitada uma imagem legível."}).is_valid())

    def test_antivirus_recusa_assinatura_antiga_ou_ilegivel(self):
        for versao in [b"ClamAV 1.4.7/14000/Thu Jan 1 00:00:00 2015\0", b"resposta incompleta\0"]:
            consulta = MagicMock()
            consulta.__enter__.return_value.recv.return_value = versao
            with self.subTest(versao=versao), patch("documentos.arquivos.socket.create_connection", return_value=consulta):
                with self.assertRaises(ScannerIndisponivel):
                    verificar_assinaturas(("local", 3310), 1)

class AcervoMunicipal(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.municipio = Municipio.objects.create(nome="Prefeitura fictícia")
        cls.outra = Municipio.objects.create(nome="Segunda prefeitura fictícia")
        cls.user = get_user_model().objects.create_user(username="financeiro-teste")
        cls.vinculo = Vinculo.objects.create(usuario=cls.user, municipio=cls.municipio, perfil="financeiro")
        cls.outro_user = get_user_model().objects.create_user(username="financeiro-outro")
        cls.outro_vinculo = Vinculo.objects.create(usuario=cls.outro_user, municipio=cls.outra, perfil="financeiro")
        comum = {"municipio": cls.municipio, "responsavel": cls.user}
        classificacao = {"codigo": "FC", "nome": "Fundo de teste", **comum}
        dot = Dotacao.objects.create(
            exercicio=Exercicio.objects.create(ano=2026, **comum), codigo="001",
            fonte=Fonte.objects.create(origem="municipal", finalidade="Homologação", **classificacao),
            fundo=Fundo.objects.create(**classificacao), programa=Programa.objects.create(**classificacao),
            natureza=Natureza.objects.create(**classificacao), valor_inicial=Decimal("100"), **comum,
        )
        cls.despesa = Despesa.objects.create(dotacao=dot, data=date(2026, 5, 9), descricao="Compra de teste",
            fornecedor="Entidade fictícia", cnpj="00000000000000", valor=Decimal("10"), processo="TESTE", documento="101", **comum)

    def setUp(self):
        self.req = RequestFactory().get("/")
        self.req.user, self.req.vinculo, self.req.municipio = self.user, self.vinculo, self.municipio
        self.xml = b"<documento>Arquivo ficticio</documento>"

    def envio(self, dados=None, doc=None, base=0, operacao=None):
        bruto = dados or self.xml
        orig = Original("nota.xml", "application/xml", bruto, hashlib.sha256(bruto).hexdigest())
        dados = {"categoria": "nota", "numero_nota": "77", "serie_nota": "1", "data_emissao": "2026-05-09",
                 "razao_social": "Entidade fictícia", "cnpj_emissor": "00000000000000", "valor_nota": "10.00",
                 "base": base, "operacao": operacao or uuid.uuid4()}
        f = DocumentoForm(dados, {"arquivo": SimpleUploadedFile("nota.xml", bruto)})
        self.assertTrue(f.is_valid(), f.errors)
        return guardar_versao(self.req, "despesa", self.despesa, f.cleaned_data, orig, doc)

    def test_versoes_exportacao_e_conferencia(self):
        v1 = self.envio()
        conferir(self.req, v1, {"situacao": "pendencia", "motivo": "Documento complementar pendente.", "providencia": "", "observacao": ""})
        novo = b"<comprovante>Complementado</comprovante>"
        v2 = self.envio(novo, v1.documento, 1)
        conferir(self.req, v2, {"situacao": "regularizado", "motivo": "", "providencia": "Conferido com o processo.", "observacao": ""})
        self.assertEqual(metricas_despesas(Despesa.objects.filter(pk=self.despesa.pk)),
                         {"notas": 1, "documentos_pendentes": 0, "despesas_sem_documentos": 0})
        docs = documentos_filtrados(self.municipio, {"exercicio": 2026, "fundo": self.despesa.dotacao.fundo_id})
        with preparar(self.municipio, docs, ["Exercício = 2026"], True) as arquivo, zipfile.ZipFile(arquivo) as pacote:
            pdf = PdfReader(io.BytesIO(pacote.read("indice.pdf")))
            self.assertIn(self.despesa.processo, "".join(p.extract_text() for p in pdf.pages))
            m = json.loads(pacote.read("manifesto.json"))
            self.assertEqual([item["versao"] for item in m], [1,2])
            for item, esperado in zip(m, [self.xml, novo]):
                self.assertEqual(pacote.read(item["arquivo"]), esperado)
                self.assertEqual(hashlib.sha256(esperado).hexdigest(), item["sha256"])
        self.assertFalse(self.despesa.lancamentos.exists())

    def test_reenvio_substituicao_concorrente_e_alerta_de_duplicidade(self):
        op = uuid.uuid4()
        v = self.envio(operacao=op)
        self.assertEqual(self.envio(operacao=op).pk, v.pk)
        outro = self.envio()
        self.assertEqual(list(duplicidades(outro, Documento.objects.all()).values_list("pk", flat=True)), [v.pk])
        self.envio(b"<revisado/>", v.documento, 1)
        with self.assertRaises(ValidationError):
            self.envio(b"<anterior/>", v.documento, 1)
        self.assertEqual(Versao.objects.filter(documento=v.documento).count(), 2)

    def test_indice_de_despesa_sem_anexos_preserva_empenho(self):
        lancamento = Lancamento.objects.create(municipio=self.municipio, despesa=self.despesa, responsavel=self.user,
            tipo="empenho", referencia="EMP-FICTICIO", documento="DOC-FICTICIO", data=self.despesa.data, valor=self.despesa.valor)
        despesas = Despesa.objects.filter(pk=self.despesa.pk)
        with preparar(self.municipio, Documento.objects.none(), [], True, despesas=despesas) as buffer, zipfile.ZipFile(buffer) as pacote:
            quadro = json.loads(pacote.read("quadro-financeiro.json"))
            self.assertEqual(quadro[0]["movimentos"][0]["id"], str(lancamento.pk))
            self.assertEqual(quadro[0]["documentos"], 0)
            pdf = PdfReader(io.BytesIO(pacote.read("indice.pdf")))
            texto = "".join(p.extract_text() for p in pdf.pages)
            self.assertIn("EMP-FICTICIO", texto)
            self.assertIn("Sem documentos", texto)

    @patch("documentos.arquivos.verificar_antivirus")
    def test_receita_e_carga_reexecutavel(self, scan):
        from .demonstracao import popular
        receita = Receita.objects.create(municipio=self.municipio, dotacao=self.despesa.dotacao, responsavel=self.user,
            tipo="recebida", origem="[SIMULADO] Repasse", documento="RECEBIMENTO-FICTICIO",
            data=self.despesa.data, valor=self.despesa.valor)
        contexto = SimpleNamespace(municipio=self.municipio, usuario=self.user, ano=self.despesa.data.year,
            data_referencia=self.despesa.data, homologacao=True, financeiro={"despesas":[self.despesa], "receitas":[receita]},
            beneficios=[], pedidos=[], vales=[], identificador=lambda chave: uuid.uuid5(uuid.NAMESPACE_DNS, chave))
        self.assertEqual(popular(contexto)["contagens"]["documentos"], 2)
        self.assertEqual(popular(contexto)["contagens"]["documentos"], 0)
        self.assertEqual(scan.call_count, 2)
        self.client.force_login(self.user)
        resposta = self.client.get(reverse("documentos:vinculo", args=["receita", receita.pk]), secure=True, HTTP_HOST="localhost")
        self.assertContains(resposta, "SIMULADO-RECEITA")
    def test_download_exige_vinculo_e_assinatura(self):
        v = self.envio()
        url = link_original(self.req, v.pk, "baixar")
        self.client.force_login(self.user)
        resposta = self.client.get(url, HTTP_HOST="localhost", secure=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(b"".join(resposta.streaming_content), self.xml)
        self.assertEqual(resposta["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client.get(url.split("?")[0], HTTP_HOST="localhost", secure=True).status_code, 403)
        self.client.force_login(self.outro_user)
        self.assertEqual(self.client.get(url, HTTP_HOST="localhost", secure=True).status_code, 403)
        self.assertFalse(documentos_filtrados(self.outra, {}).exists())

    def test_arquivo_financeiro_requer_grant_de_gestor(self):
        self.client.force_login(self.user)
        resposta = self.client.get(reverse("documentos:prestacao"), HTTP_HOST="localhost", secure=True)
        self.assertEqual(resposta.status_code, 403)

    def test_prestacao_busca_descricoes_na_mesma_consulta(self):
        self.vinculo.perfil = "gestor"
        self.vinculo.save(update_fields=["perfil"])
        for codigo in ("financeiro.ver", "gestao.ver", "documentos.ver"):
            AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo, codigo=codigo, permitido=True)
        self.client.force_login(self.user)
        url = reverse("documentos:prestacao")
        self.envio()
        with CaptureQueriesContext(connection) as primeira:
            self.assertContains(self.client.get(url, secure=True, HTTP_HOST="localhost"), self.despesa.descricao)
        for _ in range(5):
            self.envio()
        with CaptureQueriesContext(connection) as varias:
            resposta = self.client.get(url, secure=True, HTTP_HOST="localhost")
            self.assertContains(resposta, self.despesa.descricao, count=6)
        self.assertEqual(len(varias), len(primeira))

    @patch("documentos.arquivos.verificar_antivirus", side_effect=ScannerIndisponivel("Verificação indisponível."))
    def test_scanner_indisponivel_impede_gravacao(self, scan):
        self.client.force_login(self.user)
        resposta = self.client.post(reverse("documentos:anexar", args=["despesa", self.despesa.pk]),
            {"categoria":"recibo","base":0, "operacao":uuid.uuid4(),
             "arquivo":SimpleUploadedFile("teste.xml", self.xml)}, HTTP_HOST="localhost", secure=True)
        self.assertEqual(resposta.status_code, 503)
        self.assertFalse(Documento.objects.exists())


    @patch("documentos.arquivos.verificar_antivirus")
    def test_fluxo_http_indice_e_arquivo_do_gestor(self, scan):
        self.client.force_login(self.user)
        resposta = self.client.post(reverse("documentos:anexar", args=["despesa", self.despesa.pk]),
            {"categoria":"recibo", "base":0, "operacao":uuid.uuid4(),
             "arquivo":SimpleUploadedFile("teste.xml", self.xml)}, HTTP_HOST="localhost", secure=True)
        self.assertEqual(resposta.status_code, 302)
        detalhe = self.client.get(resposta.url, HTTP_HOST="localhost", secure=True)
        self.assertContains(detalhe, "Visualizar original")
        self.assertContains(detalhe, "teste.xml")
        self.assertContains(detalhe, "acesso=")
        self.vinculo.perfil = "gestor"
        self.vinculo.save(update_fields=["perfil"])
        for codigo in ("financeiro.ver","gestao.ver","documentos.ver"):
            AjustePermissao.objects.create(municipio=self.municipio, vinculo=self.vinculo, codigo=codigo, permitido=True)
        pacote = self.client.post(reverse("documentos:prestacao"), {"exercicio":2026, "formato":"zip"}, HTTP_HOST="localhost", secure=True)
        self.assertEqual(pacote.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(b"".join(pacote.streaming_content))) as zip_:
            self.assertIn("indice.pdf", zip_.namelist())

    def test_isolamento_e_imutabilidade_com_role_da_aplicacao(self):
        with connection.cursor() as cur:
            cur.execute("SET LOCAL ROLE social_app")
            cur.execute("SELECT set_config('social.municipio', %s, true)", [str(self.municipio.pk)])
        try:
            versao = self.envio()
            with self.assertRaises(DatabaseError), transaction.atomic():
                Versao.objects.filter(pk=versao.pk).update(nome="alterado.xml")
            with connection.cursor() as cur:
                cur.execute("SELECT set_config('social.municipio', %s, true)", [str(self.outra.pk)])
            self.assertFalse(Documento.objects.filter(pk=versao.documento_id).exists())
            self.assertFalse(Versao.objects.filter(pk=versao.pk).exists())
        finally:
            with connection.cursor() as cur:
                cur.execute("RESET ROLE")
