"""Acervo local de textos oficiais fornecidos pelo operador, sem certificação jurídica.

Use --diretorio-dados apontando para armazenamento persistente fora do deploy.
As datas de consulta identificam coletas. Nunca representam publicação ou vigência.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


SITUACOES = ("pendente", "vigencia-indicada-na-fonte", "revogacao-indicada-na-fonte")
UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
AVISO = "Acervo de textos fornecidos. Autenticidade, completude e vigência exigem conferência na fonte oficial."


def https_url(value):
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError("A origem deve ser uma URL HTTPS sem credenciais ou fragmento.")
    return value


def consulta_iso(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Informe consulta como data/hora ISO 8601 com fuso.") from exc
    if parsed.tzinfo is None:
        raise ValueError("A data/hora de consulta exige fuso explícito.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def conectar(diretorio):
    pasta = Path(diretorio).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[1]
    if pasta == checkout or checkout in pasta.parents:
        raise ValueError("O diretório de dados deve ficar fora do checkout/deploy.")
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    banco = pasta / "base-legal.sqlite3"
    conn = sqlite3.connect(banco, timeout=30)
    banco.chmod(0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        conn.close()
        raise ValueError("Versão do banco incompatível com este utilitário.")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS normas (
            id TEXT PRIMARY KEY, ente TEXT NOT NULL, uf TEXT NOT NULL,
            municipio_ibge TEXT NOT NULL, municipio_nome TEXT NOT NULL,
            identificador TEXT NOT NULL, UNIQUE(ente, uf, municipio_ibge, identificador)
        );
        CREATE TABLE IF NOT EXISTS versoes (
            id TEXT PRIMARY KEY, norma_id TEXT NOT NULL REFERENCES normas(id),
            sha256 TEXT NOT NULL, texto TEXT NOT NULL,
            UNIQUE(norma_id, sha256)
        );
        CREATE TABLE IF NOT EXISTS coletas (
            id TEXT PRIMARY KEY, versao_id TEXT NOT NULL REFERENCES versoes(id),
            origem TEXT NOT NULL, consultado_em TEXT NOT NULL,
            situacao TEXT NOT NULL, evidencia_situacao TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS coletas_versao ON coletas(versao_id, consultado_em);
        CREATE VIRTUAL TABLE IF NOT EXISTS textos_fts USING fts5(
            versao_id UNINDEXED, texto, tokenize='unicode61 remove_diacritics 2'
        );
        PRAGMA user_version = 1;
    """)
    return conn


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def importar(conn, args):
    uf = (args.uf or "").upper()
    codigo = args.municipio_ibge or ""
    nome = (args.municipio_nome or "").strip()
    if args.ente == "federal" and (uf or codigo or nome):
        raise ValueError("Norma federal não recebe UF ou município.")
    if args.ente in ("estadual", "municipal") and uf not in UFS:
        raise ValueError("Informe uma UF válida para o ente.")
    if args.ente == "estadual" and (codigo or nome):
        raise ValueError("Norma estadual não recebe município.")
    if args.ente == "municipal" and (not re.fullmatch(r"[0-9]{7}", codigo) or not nome):
        raise ValueError("Norma municipal exige UF, código IBGE de sete dígitos e nome.")
    identificador = args.identificador.strip()
    if not identificador:
        raise ValueError("Identificador da norma não pode estar vazio.")
    origem = https_url(args.origem)
    instante = consulta_iso(args.consultado_em)
    evidencia = (args.evidencia_situacao or "").strip()
    if args.situacao != "pendente" and not evidencia:
        raise ValueError("Situação declarada exige evidência textual e verificável na fonte.")
    # Bytes originais são preservados, inclusive quebras de linha e BOM, para o hash.
    texto = Path(args.arquivo).read_bytes().decode("utf-8", errors="strict")
    if not texto.strip():
        raise ValueError("Texto vazio.")
    norma_id = digest(json.dumps([args.ente, uf, codigo, identificador], ensure_ascii=False))
    content_hash = digest(texto)
    versao_id = digest(norma_id + content_hash)
    coleta_id = digest(json.dumps([versao_id, origem, instante, args.situacao, evidencia], ensure_ascii=False))
    with conn:
        existente = conn.execute("SELECT municipio_nome FROM normas WHERE id = ?", (norma_id,)).fetchone()
        if existente and existente["municipio_nome"] != nome:
            raise ValueError("Código municipal já registrado com outro nome. Confira os metadados.")
        conflito = conn.execute("""
            SELECT 1 FROM coletas c JOIN versoes v ON v.id = c.versao_id
            WHERE v.norma_id = ? AND c.consultado_em = ?
              AND (v.id <> ? OR c.situacao <> ?)
        """, (norma_id, instante, versao_id, args.situacao)).fetchone()
        if conflito:
            raise ValueError("Coletas do mesmo instante têm conteúdo ou situação conflitante. Confira os metadados.")
        conn.execute("INSERT OR IGNORE INTO normas VALUES (?, ?, ?, ?, ?, ?)",
                     (norma_id, args.ente, uf, codigo, nome, identificador))
        criado = conn.execute("INSERT OR IGNORE INTO versoes VALUES (?, ?, ?, ?)",
                              (versao_id, norma_id, content_hash, texto)).rowcount
        if criado:
            conn.execute("INSERT INTO textos_fts(versao_id, texto) VALUES (?, ?)", (versao_id, texto))
        conn.execute("INSERT OR IGNORE INTO coletas VALUES (?, ?, ?, ?, ?, ?)",
                     (coleta_id, versao_id, origem, instante, args.situacao, evidencia))
    return {"norma_id": norma_id, "versao_id": versao_id, "coleta_id": coleta_id,
            "sha256": content_hash, "versao_nova": bool(criado), "aviso": AVISO}


BASE = """
    WITH observacoes AS (
        SELECT n.*, v.id AS versao_id, v.sha256, v.texto, c.id AS coleta_id,
               c.origem, c.consultado_em, c.situacao, c.evidencia_situacao,
               ROW_NUMBER() OVER (
                   PARTITION BY n.id ORDER BY c.consultado_em DESC, c.id DESC
               ) AS ordem_norma,
               ROW_NUMBER() OVER (
                   PARTITION BY v.id ORDER BY c.consultado_em DESC, c.id DESC
               ) AS ordem_versao
        FROM normas n JOIN versoes v ON v.norma_id = n.id
        JOIN coletas c ON c.versao_id = v.id
    )
"""


def metadados(row):
    result = dict(row)
    result.pop("texto", None)
    result["ultima_coleta_da_norma"] = result.pop("ordem_norma") == 1
    result.pop("ordem_versao", None)
    result["citacao"] = "bl:" + row["versao_id"] + ":" + row["coleta_id"]
    result["aviso"] = AVISO
    return result


def pesquisar(conn, args):
    if len(args.texto) > 1000:
        raise ValueError("A pesquisa aceita até 1000 caracteres.")
    tokens = re.findall(r"[^\W_]+", args.texto, flags=re.UNICODE)
    if not tokens:
        raise ValueError("Informe palavras para pesquisar.")
    # Expressão FTS é construída apenas de tokens literais, sem operadores do usuário.
    query = " AND ".join('"' + token + '"' for token in tokens)
    filtros = ["ordem_versao = 1", "versao_id IN (SELECT versao_id FROM textos_fts WHERE textos_fts MATCH ?)"]
    params = [query]
    if not args.historico:
        filtros.append("ordem_norma = 1")
    if not args.incluir_pendentes:
        filtros.append("situacao <> ?")
        params.append("pendente")
    for column, value in [("ente", args.ente), ("uf", args.uf), ("municipio_ibge", args.municipio_ibge)]:
        if value:
            filtros.append(column + " = ?")
            params.append(value.upper() if column == "uf" else value)
    if not 1 <= args.limite <= 100:
        raise ValueError("Limite deve estar entre 1 e 100.")
    rows = conn.execute(BASE + "SELECT * FROM observacoes WHERE " + " AND ".join(filtros)
                        + " ORDER BY ente, uf, municipio_ibge, identificador, consultado_em DESC, versao_id LIMIT ?",
                        [*params, args.limite]).fetchall()
    return {"escopo": "historico" if args.historico else "ultima-coleta-por-norma",
            "inclui_pendentes": args.incluir_pendentes, "aviso": AVISO,
            "resultados": [metadados(row) for row in rows]}


def citar(conn, args):
    match = re.fullmatch(r"bl:([0-9a-f]{64}):([0-9a-f]{64})", args.citacao)
    if not match:
        raise ValueError("Citação deve ser bl:<versao_id>:<coleta_id>.")
    row = conn.execute(BASE + "SELECT * FROM observacoes WHERE versao_id = ? AND coleta_id = ?", match.groups()).fetchone()
    if not row:
        raise ValueError("Citação não encontrada.")
    linhas = row["texto"].splitlines()
    fim = args.fim or len(linhas)
    if not 1 <= args.inicio <= fim <= len(linhas):
        raise ValueError("Intervalo de linhas fora do texto armazenado.")
    return {**metadados(row), "inicio": args.inicio, "fim": fim,
            "linhas": [{"numero": n, "texto": linhas[n - 1]} for n in range(args.inicio, fim + 1)]}


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--diretorio-dados", required=True)
    sub = cli.add_subparsers(dest="comando", required=True)
    imp = sub.add_parser("importar", help="Importa texto UTF-8 oficial fornecido e seus metadados.")
    imp.add_argument("--arquivo", required=True)
    imp.add_argument("--ente", choices=("federal", "estadual", "municipal"), required=True)
    imp.add_argument("--uf")
    imp.add_argument("--municipio-ibge")
    imp.add_argument("--municipio-nome")
    imp.add_argument("--identificador", required=True, help="Identificador estável incluindo tipo, número, ano e órgão emissor quando necessário.")
    imp.add_argument("--origem", required=True, help="URL HTTPS do texto na fonte oficial.")
    imp.add_argument("--consultado-em", required=True, help="Instante da consulta ISO 8601 com fuso, sem inferência de vigência.")
    imp.add_argument("--situacao", choices=SITUACOES, default="pendente")
    imp.add_argument("--evidencia-situacao", help="Referência textual conferível na fonte, para situação indicada.")
    imp.set_defaults(func=importar)
    pes = sub.add_parser("pesquisar", help="Busca literal por palavras; padrão usa última coleta e exclui pendentes.")
    pes.add_argument("--texto", required=True)
    pes.add_argument("--ente", choices=("federal", "estadual", "municipal"))
    pes.add_argument("--uf")
    pes.add_argument("--municipio-ibge")
    pes.add_argument("--historico", action="store_true")
    pes.add_argument("--incluir-pendentes", action="store_true")
    pes.add_argument("--limite", type=int, default=20)
    pes.set_defaults(func=pesquisar)
    cit = sub.add_parser("citar", help="Recupera exatamente uma versão e coleta por linhas numeradas.")
    cit.add_argument("citacao")
    cit.add_argument("--inicio", type=int, default=1)
    cit.add_argument("--fim", type=int)
    cit.set_defaults(func=citar)
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    conn = None
    try:
        conn = conectar(args.diretorio_dados)
        resultado = args.func(conn, args)
    except (ValueError, OSError, sqlite3.Error) as exc:
        cli.exit(2, f"Erro na base legal: {exc}\n")
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
