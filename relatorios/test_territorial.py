import hashlib
import json
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from django.contrib.auth import get_user_model
from django.db import connection
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from atendimentos.models import Atendimento, Cidadao, Familia, Municipio, Vinculo
from cadastros.models import AcompanhamentoAtendimento, ComplementoFamilia
from programas.models import ConcessaoVale, Material, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio
from .territorial import associar_localidades, carregar_malha, carregar_satelite, carregar_vias, coordenadas_validas, ponto_no_contorno, resumo_territorial


@override_settings(SOCIAL_MUNICIPIOS_GEOGRAFICOS={})
class TerritorialConsultasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.municipio = Municipio.objects.create(nome="Município do teste territorial")
        cls.outro = Municipio.objects.create(nome="Outro município do teste")
        cls.user = get_user_model().objects.create_user("teste-territorial")
        cls.vinculo = Vinculo.objects.create(usuario=cls.user, municipio=cls.municipio, perfil="coordenador")
        cls.familia = Familia.objects.create(municipio=cls.municipio, referencia="Família de teste")
        cls.pessoa = Cidadao.objects.create(municipio=cls.municipio, familia=cls.familia, nome="Pessoa do teste")
        ComplementoFamilia.objects.create(municipio=cls.municipio, familia=cls.familia, bairro="Bairro do teste", territorio="Território do teste")
        data = timezone.make_aware(datetime(2026, 11, 12, 10))
        for indice, (sigilo, situacao, instante) in enumerate([
            (False, "aberto", data), (False, "concluido", data),
            (True, "aguarda", data), (False, "concluido", timezone.make_aware(datetime(2025, 1, 1, 10))),
        ]):
            registro = Atendimento.objects.create(municipio=cls.municipio, cidadao=cls.pessoa, unidade="Unidade do teste", encaminhamento=str(indice))
            AcompanhamentoAtendimento.objects.create(municipio=cls.municipio, atendimento=registro, data_efetiva=instante, sigiloso=sigilo, situacao=situacao)
        cls.tipo = TipoBeneficio.objects.create(municipio=cls.municipio, nome="Tipo do teste", regra_local="Texto sintético de teste", vigencia_inicio=data.date())
        for situacao in ["solicitado", "analise", "aprovado"]:
            SolicitacaoBeneficio.objects.create(municipio=cls.municipio, familia=cls.familia, tipo=cls.tipo, quantidade_solicitada=1, responsavel=cls.user, situacao=situacao)
        material = Material.objects.create(municipio=cls.municipio, nome="Material do teste", unidade="un")
        for situacao, entregue in [("aprovado", 2), ("disponibilidade", 0), ("entregue", 5), ("indeferido", 0)]:
            PedidoMaterial.objects.create(municipio=cls.municipio, familia=cls.familia, material=material,
                quantidade_solicitada=5, quantidade_aprovada=5, entregue=entregue, situacao=situacao,
                responsavel=cls.user, justificativa="Teste")
        for situacao in ["analise", "ativo"]:
            ConcessaoVale.objects.create(municipio=cls.municipio, familia=cls.familia, cidadao=cls.pessoa,
                valor=Decimal("100"), periodicidade="mensal", situacao=situacao, responsavel=cls.user)
        familia_b = Familia.objects.create(municipio=cls.outro, referencia="Família de outro tenant")
        pessoa_b = Cidadao.objects.create(municipio=cls.outro, familia=familia_b, nome="Pessoa de outro tenant")
        ComplementoFamilia.objects.create(municipio=cls.outro, familia=familia_b, bairro="BAIRRO RESTRITO")
        registro_b = Atendimento.objects.create(municipio=cls.outro, cidadao=pessoa_b, unidade="Outra", encaminhamento="Outro")
        AcompanhamentoAtendimento.objects.create(municipio=cls.outro, atendimento=registro_b, data_efetiva=data, situacao="aberto")

    def resumo(self, direitos):
        return resumo_territorial(self.municipio, self.vinculo, direitos=direitos, hoje=datetime(2026, 11, 22).date())

    def test_totais_distinguem_periodo_situacao_sigilo_e_tenant(self):
        direitos = {"atendimentos.ver", "beneficios.ver", "materiais.ver", "vale.ver"}
        with CaptureQueriesContext(connection) as consultas:
            resultado = self.resumo(direitos)
        self.assertEqual(resultado["totais"], {"atendimentos": 2, "demandas": 6})
        self.assertEqual(len(resultado["linhas"]), 1)
        self.assertEqual(resultado["linhas"][0]["bairro"], "Bairro do teste")
        self.assertEqual(resultado["componentes"]["Acompanhamentos em aberto"], 1)
        self.assertLessEqual(len(consultas), 5)
        self.assertNotIn("BAIRRO RESTRITO", str(resultado))
        com_sigilo = self.resumo(direitos | {"sigilo.ver"})
        self.assertEqual(com_sigilo["totais"], {"atendimentos": 3, "demandas": 7})

    def test_perfil_material_nao_recebe_contagens_dos_outros_dominios(self):
        resultado = self.resumo({"materiais.ver"})
        self.assertIsNone(resultado["totais"]["atendimentos"])
        self.assertEqual(resultado["totais"]["demandas"], 2)
        self.assertEqual(list(resultado["componentes"]), ["Solicitações de material pendentes"])
        html = render_to_string("relatorios/territorial.html", {"territorial": resultado})
        self.assertNotIn("Atendimentos registrados", html)
        self.assertNotIn("Benefícios aguardando análise", html)

    def test_ausencia_localidade_conta_na_tabela_sem_posicionar(self):
        ComplementoFamilia.objects.filter(familia=self.familia).delete()
        resultado = self.resumo({"atendimentos.ver"})
        self.assertEqual(resultado["linhas"][0]["bairro"], "Bairro não informado")
        self.assertIsNone(resultado["geometria"])
        self.assertEqual(resultado["totais"]["atendimentos"], 2)

    def test_vinculo_de_outro_tenant_ou_sem_direitos_nao_faz_consulta(self):
        with CaptureQueriesContext(connection) as consultas:
            resultado = resumo_territorial(self.outro, self.vinculo, direitos={"atendimentos.ver"})
            sem_direitos = self.resumo(set())
        self.assertEqual(resultado, {"disponivel": False})
        self.assertEqual(sem_direitos, {"disponivel": False})
        self.assertEqual(len(consultas), 0)

    def test_pontos_contem_somente_indicadores_autorizados(self):
        referencia = {"nome": "Bairro do teste", "aliases": [], "longitude": .7, "latitude": .2,
            "coordenadas_distintas": 10, "metodo": "centro_amostral", "fonte": {"id": "fixture"}}
        with patch("relatorios.territorial.carregar_malha", return_value={
            "referencias": [referencia], "geometria": None, "fonte": None, "lacuna": "Fixture de teste",
        }):
            resultado = self.resumo({"materiais.ver"})
        self.assertIsNone(resultado["pontos"][0]["atendimentos"])
        self.assertEqual(resultado["pontos"][0]["demandas"], 2)
        self.assertEqual(resultado["mapeados"]["demandas"], 2)
        self.assertEqual(resultado["sem_ponto"]["demandas"], 0)
        self.assertNotIn("Pessoa", str(resultado["pontos"]))


class MalhaTerritorialTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.arquivo = self.pasta / "fixture.geojson"
        # Quadrado sintético serve somente à validação do leitor, nunca ao catálogo real.
        self.geometria = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "fixture",
            "properties": {"nome": "Geometria sintética de teste", "tipo": "municipio", "codigo_ibge": "0000001"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]}
        self.arquivo.write_text(json.dumps(self.geometria), encoding="utf-8")
        self.catalogo = self.pasta / "catalogo.json"
        self.dados = {"municipio": {"codigo_ibge": "0000001"},
            "limite_municipal": {"estado": "verificado", "arquivo": "fixture.geojson", "sha256": hashlib.sha256(self.arquivo.read_bytes()).hexdigest()},
            "proveniencia": {"fonte": "Fixture sintética", "url": "https://example.invalid/fixture", "consultado_em": "2026-11-22", "licenca": "Teste"}}
        self.catalogo.write_text(json.dumps(self.dados), encoding="utf-8")
        self.municipio = type("MunicipioFixture", (), {"pk": 1})()

    @override_settings(SOCIAL_MUNICIPIOS_GEOGRAFICOS={"1": "0000001"})
    def test_so_mapeia_codigo_explicito_hash_e_contorno_validos(self):
        with patch("relatorios.territorial.DADOS", self.pasta), patch("relatorios.territorial.CATALOGO", self.catalogo):
            valido = carregar_malha(self.municipio)
            self.assertIsNotNone(valido["geometria"])
            self.dados["limite_municipal"]["sha256"] = "hash-divergente"
            self.catalogo.write_text(json.dumps(self.dados), encoding="utf-8")
            self.assertIsNone(carregar_malha(self.municipio)["geometria"])

    @override_settings(SOCIAL_MUNICIPIOS_GEOGRAFICOS={})
    def test_nome_homonimo_sem_vinculo_nao_ganha_geometria(self):
        with patch("relatorios.territorial.DADOS", self.pasta), patch("relatorios.territorial.CATALOGO", self.catalogo):
            self.assertIsNone(carregar_malha(self.municipio)["geometria"])

    def test_coordenadas_invalidas_e_ring_aberto_rejeitados(self):
        self.assertFalse(coordenadas_validas({"type": "Point", "coordinates": [0, 0]}))
        self.assertFalse(coordenadas_validas({"type": "Polygon", "coordinates": [[[0, 0], [999, 0], [1, 1], [0, 0]]]}))
        self.assertFalse(coordenadas_validas({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}))

    @override_settings(SOCIAL_MUNICIPIOS_GEOGRAFICOS={"1": "0000001"})
    def test_referencias_exigem_amostra_municipio_fonte_e_contorno(self):
        self.dados["fontes"] = [{"id": "fixture", "url": "https://example.invalid/fixture", "consultado_em": "2026-11-22", "sha256_arquivo_origem": "0" * 64}]
        ponto = {"nome": "Localidade sintética", "aliases": [], "codigo_ibge": "0000001", "longitude": .7, "latitude": .2,
                 "coordenadas_distintas": 10, "metodo": "centro_amostral", "estado": "verificado_agregado", "fonte_id": "fixture"}
        self.dados["referencias_localidades"] = [ponto,
            {**ponto, "nome": "Amostra insuficiente", "coordenadas_distintas": 9},
            {**ponto, "nome": "Outro município", "codigo_ibge": "0000002"},
            {**ponto, "nome": "Fora do contorno", "longitude": -1},
            {**ponto, "nome": "Sem fonte", "fonte_id": "ausente"},
        ]
        self.catalogo.write_text(json.dumps(self.dados), encoding="utf-8")
        with patch("relatorios.territorial.DADOS", self.pasta), patch("relatorios.territorial.CATALOGO", self.catalogo):
            malha = carregar_malha(self.municipio)
        self.assertEqual([r["nome"] for r in malha["referencias"]], ["Localidade sintética"])
        self.assertTrue(ponto_no_contorno(.7, .2, self.geometria["features"]))
        self.assertFalse(ponto_no_contorno(-1, .2, self.geometria["features"]))

    def test_associacao_agrega_territorios_preserva_lacunas_e_nao_duplica_alias(self):
        referencia = {"nome": "Localidade sintética", "aliases": ["Sintética"], "longitude": .7, "latitude": .2,
                      "coordenadas_distintas": 10, "metodo": "centro_amostral"}
        linhas = [
            {"bairro": "SINTETICA", "bairro_informado": True, "atendimentos": 3, "demandas": 2},
            {"bairro": "Localidade sintética", "bairro_informado": True, "atendimentos": 4, "demandas": 1},
            {"bairro": "Localidade sem ponto", "bairro_informado": True, "atendimentos": 5, "demandas": 6},
        ]
        pontos = associar_localidades(linhas, [referencia], True)
        self.assertEqual((pontos[0]["atendimentos"], pontos[0]["demandas"]), (7, 3))
        self.assertEqual(linhas[2]["referencia_mapa"], "")
        self.assertEqual(linhas[0]["referencia_mapa"], referencia["nome"])
        duplicada = {**referencia, "nome": "Outro ponto", "aliases": ["SINTÉTICA"]}
        pontos = associar_localidades(linhas, [referencia, duplicada], False)
        self.assertIsNone(pontos[0]["atendimentos"])
        self.assertEqual(pontos[0]["demandas"], 1)
        self.assertEqual(pontos[1]["demandas"], 0)
        self.assertEqual(linhas[0]["referencia_mapa"], "")


class CamadasLocaisTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.limite_hash = "a" * 64

    def test_satelite_exige_codigo_hash_pixels_e_referencia_do_limite(self):
        imagem = self.pasta / "fixture.png"
        Image.new("RGB", (16, 16), color="green").save(imagem)
        metadados = {"codigo_ibge": "0000001", "bounds": [0, 0, 1, 1], "bounds_crs": "EPSG:4326", "crs_imagem": "EPSG:3857",
            "arquivo_static": "fixture/satelite.png", "largura": 16, "altura": 16,
            "sha256": hashlib.sha256(imagem.read_bytes()).hexdigest(), "data_captura": "2026-01-01T00:00:00Z",
            "credito": "Imagem sintética para teste", "fonte": "Fixture", "url": "https://example.invalid/fixture",
            "licenca": "Fixture", "licenca_url": "https://example.invalid/licenca", "resolucao_origem_metros": 10,
            "qualidade": {"cobertura_contorno_referencia": True, "limite_referencia_sha256": self.limite_hash}}
        arquivo_meta = self.pasta / "satelite_santa_cruz_de_minas.json"
        arquivo_meta.write_text(json.dumps(metadados), encoding="utf-8")
        with patch("relatorios.territorial.DADOS", self.pasta), patch("relatorios.territorial.find", return_value=str(imagem)):
            self.assertIsNotNone(carregar_satelite("0000001", self.limite_hash))
            self.assertIsNone(carregar_satelite("0000002", self.limite_hash))
            self.assertIsNone(carregar_satelite("0000001", "b" * 64))
            metadados["bounds"] = [1, 0, 0, 1]
            arquivo_meta.write_text(json.dumps(metadados), encoding="utf-8")
            self.assertIsNone(carregar_satelite("0000001", self.limite_hash))
            metadados["bounds"] = [0, 0, 1, 1]
            arquivo_meta.write_text(json.dumps(metadados), encoding="utf-8")
            imagem.write_bytes(b"conteudo modificado")
            self.assertIsNone(carregar_satelite("0000001", self.limite_hash))

    def test_vias_exigem_codigo_hash_coordenadas_e_properties_publicas(self):
        geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"nome": "Via sintética", "classe": "teste"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]}
        arquivo = self.pasta / "0000001-vias.geojson"
        meta = {"codigo_ibge": "0000001", "sha256_limite": self.limite_hash,
                "credito": "Fixture", "url": "https://example.invalid/vias"}
        arquivo_meta = self.pasta / "0000001-vias.origem.json"

        def salvar():
            arquivo.write_text(json.dumps(geojson), encoding="utf-8")
            meta["sha256_geojson"] = hashlib.sha256(arquivo.read_bytes()).hexdigest()
            arquivo_meta.write_text(json.dumps(meta), encoding="utf-8")

        salvar()
        with patch("relatorios.territorial.VIAS_DADOS", self.pasta), patch("relatorios.territorial.static", side_effect=lambda nome: "/static/" + nome):
            self.assertEqual(carregar_vias("0000001", self.limite_hash)["vias_url"], "/static/relatorios/geografia/0000001-vias.geojson")
            self.assertEqual(carregar_vias("0000002", self.limite_hash), {})
            self.assertEqual(carregar_vias("0000001", "b" * 64), {})
            geojson["features"][0]["geometry"]["coordinates"][0] = [999, 0]
            salvar()
            self.assertEqual(carregar_vias("0000001", self.limite_hash), {})
            geojson["features"][0]["geometry"]["coordinates"][0] = [0, 0]
            geojson["features"][0]["properties"]["campo_inesperado"] = "Fora do contrato de vias públicas"
            salvar()
            self.assertEqual(carregar_vias("0000001", self.limite_hash), {})
