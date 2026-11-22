from django.db import migrations
from atendimentos.rls import proteger


class Migration(migrations.Migration):
    dependencies = [("documentos", "0001_initial")]
    # A role de execução consulta e acrescenta versões e conferências. Todo o
    # histórico e o original permanecem imutáveis sob suas permissões.
    operations = [
        migrations.RunSQL(proteger(tabela, permissoes="SELECT, INSERT"))
        for tabela in ("documentos_documento", "documentos_versao", "documentos_conferencia")
    ] + [
        migrations.RunSQL(f"""
            CREATE UNIQUE INDEX doc_ref_{campo}_municipio ON {pai} (id, municipio_id);
            ALTER TABLE {filho}
            ADD CONSTRAINT doc_fk_{campo}_municipio FOREIGN KEY ({campo}_id, municipio_id)
            REFERENCES {pai} (id, municipio_id) DEFERRABLE INITIALLY DEFERRED;
        """)
        for filho, campo, pai in (
            ("documentos_documento", "despesa", "financeiro_despesa"),
            ("documentos_documento", "beneficio", "programas_solicitacaobeneficio"),
            ("documentos_documento", "material", "programas_pedidomaterial"),
            ("documentos_documento", "vale", "programas_concessaovale"),
            ("documentos_versao", "documento", "documentos_documento"),
            ("documentos_conferencia", "versao", "documentos_versao"),
        )
    ]
