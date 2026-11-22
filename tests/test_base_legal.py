"""Testes com texto sintético sem conteúdo normativo ou alegação de fonte real."""

import tempfile
import unittest
from pathlib import Path

from ferramentas.base_legal import citar, conectar, importar, parser, pesquisar


class BaseLegalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conn = conectar(self.root / "persistente")
        self.addCleanup(self.conn.close)
        self.cli = parser()

    def args(self, *params):
        return self.cli.parse_args(["--diretorio-dados", str(self.root / "persistente"), *params])

    def inserir(self, texto="Teste de integração\nAção demonstrativa.", codigo="0000001",
                instante="2026-11-22T10:00:00-03:00", situacao="vigencia-indicada-na-fonte"):
        arquivo = self.root / "entrada.txt"
        arquivo.write_bytes(texto.encode("utf-8"))
        return importar(self.conn, self.args(
            "importar", "--arquivo", str(arquivo), "--ente", "municipal", "--uf", "MG",
            "--municipio-ibge", codigo, "--municipio-nome", "Município sintético",
            "--identificador", "Documento sintético para teste", "--origem", "https://example.invalid/texto",
            "--consultado-em", instante, "--situacao", situacao,
            "--evidencia-situacao", "Metadado sintético de teste",
        ))

    def buscar(self, *flags, texto="acao"):
        return pesquisar(self.conn, self.args("pesquisar", "--texto", texto, *flags))["resultados"]

    def test_unicode_homonimos_e_citacao(self):
        primeiro = self.inserir()
        self.inserir(codigo="0000002")
        encontrados = self.buscar()
        self.assertEqual(len(encontrados), 2)
        self.assertEqual([r["municipio_ibge"] for r in encontrados], ["0000001", "0000002"])
        filtrado = self.buscar("--municipio-ibge", "0000001")
        self.assertEqual(len(filtrado), 1)
        citacao = citar(self.conn, self.args("citar", filtrado[0]["citacao"], "--inicio", "2", "--fim", "2"))
        self.assertEqual(citacao["linhas"], [{"numero": 2, "texto": "Ação demonstrativa."}])
        self.assertEqual(citacao["sha256"], primeiro["sha256"])

    def test_versao_pendente_nao_reapresenta_anterior_como_atual(self):
        primeira = self.inserir()
        anterior = self.buscar()[0]["citacao"]
        segunda = self.inserir("Texto alterado.\nAção pendente.", instante="2026-11-23T13:00:00Z", situacao="pendente")
        self.assertNotEqual(primeira["versao_id"], segunda["versao_id"])
        self.assertEqual(self.buscar(), [])
        self.assertEqual(self.buscar("--incluir-pendentes")[0]["situacao"], "pendente")
        historico = self.buscar("--historico")
        self.assertEqual(len(historico), 1)
        self.assertFalse(historico[0]["ultima_coleta_da_norma"])
        self.assertFalse(citar(self.conn, self.args("citar", anterior))["ultima_coleta_da_norma"])

    def test_recoleta_idempotente_e_revogacao_indicada(self):
        primeira = self.inserir()
        repetida = self.inserir()
        self.assertEqual(primeira["coleta_id"], repetida["coleta_id"])
        nova = self.inserir(instante="2026-11-23T13:00:00Z", situacao="revogacao-indicada-na-fonte")
        self.assertFalse(nova["versao_nova"])
        self.assertEqual(primeira["versao_id"], nova["versao_id"])
        resultado = self.buscar()[0]
        self.assertEqual(resultado["situacao"], "revogacao-indicada-na-fonte")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM coletas").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM textos_fts").fetchone()[0], 1)

    def test_consulta_por_data_nao_por_ordem_importacao(self):
        self.inserir("Ação recente.", instante="2026-11-23T13:00:00Z")
        self.inserir("Ação antiga.", instante="2026-11-22T13:00:00Z")
        self.assertIn("recente", citar(self.conn, self.args("citar", self.buscar()[0]["citacao"]))["linhas"][0]["texto"])
        self.assertEqual(len(self.buscar("--historico")), 2)

    def test_conflito_no_mesmo_instante_rejeitado_atomicamente(self):
        self.inserir()
        with self.assertRaises(ValueError):
            self.inserir("Conteúdo incompatível no mesmo instante.")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM versoes").fetchone()[0], 1)

    def test_sql_e_operadores_fts_sao_texto_literal(self):
        self.inserir()
        self.assertEqual(self.buscar(texto="' OR 1=1 --"), [])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM normas").fetchone()[0], 1)
        self.assertEqual(self.buscar("--municipio-ibge", "' OR 1=1 --"), [])

    def test_metadados_invalidos_nao_importam(self):
        entrada = self.root / "teste.txt"
        entrada.write_text("Teste sintético", encoding="utf-8")
        base = ["importar", "--arquivo", str(entrada), "--ente", "municipal", "--uf", "MG",
                "--municipio-ibge", "0000001", "--municipio-nome", "Sintético", "--identificador", "Teste",
                "--origem", "http://example.invalid/", "--consultado-em", "2026-11-22T12:00:00Z"]
        with self.assertRaises(ValueError):
            importar(self.conn, self.args(*base))
        base[base.index("http://example.invalid/")] = "https://example.invalid/"
        base[base.index("2026-11-22T12:00:00Z")] = "2026-11-22"
        with self.assertRaises(ValueError):
            importar(self.conn, self.args(*base))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM normas").fetchone()[0], 0)

    def test_reabrir_preserva_coletas_e_indice(self):
        self.inserir()
        outra = conectar(self.root / "persistente")
        self.addCleanup(outra.close)
        encontrado = pesquisar(outra, self.args("pesquisar", "--texto", "integração"))
        self.assertEqual(len(encontrado["resultados"]), 1)

    def test_tres_niveis_com_identificadores_iguais(self):
        self.inserir()
        arquivo = self.root / "entrada.txt"
        for ente in ("federal", "estadual"):
            flags = ["importar", "--arquivo", str(arquivo), "--ente", ente,
                     "--identificador", "Documento sintético para teste",
                     "--origem", "https://example.invalid/texto",
                     "--consultado-em", "2026-11-22T13:00:00Z",
                     "--situacao", "vigencia-indicada-na-fonte",
                     "--evidencia-situacao", "Metadado sintético de teste"]
            if ente == "estadual":
                flags.extend(["--uf", "MG"])
            importar(self.conn, self.args(*flags))
        self.assertEqual(len(self.buscar()), 3)
        self.assertEqual(len(self.buscar("--ente", "estadual", "--uf", "mg")), 1)
        self.assertEqual(len(self.buscar("--ente", "federal")), 1)


if __name__ == "__main__":
    unittest.main()
