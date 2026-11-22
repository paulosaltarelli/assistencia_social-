"""Contratos de migration para tabelas municipais com chave municipio_id."""
import re


def proteger(tabela, permissoes="SELECT, INSERT"):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", tabela):
        raise ValueError("Identificador de tabela inválido.")
    verbos = [verbo.strip() for verbo in permissoes.split(",")]
    if not verbos or any(verbo not in {"SELECT", "INSERT", "UPDATE", "DELETE"} for verbo in verbos):
        raise ValueError("Privilégio inválido para uma tabela municipal.")
    filtro = "municipio_id = nullif(current_setting('social.municipio', true), '')::bigint"
    return f"""
        ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY;
        CREATE POLICY municipio ON {tabela} USING ({filtro}) WITH CHECK ({filtro});
        REVOKE ALL ON {tabela} FROM PUBLIC, social_app;
        GRANT {', '.join(verbos)} ON {tabela} TO social_app;
    """
