from django.db import migrations

tables = ["atendimentos_atendimento", "atendimentos_auditoria"]


class Migration(migrations.Migration):
    dependencies = [("atendimentos", "0001_initial")]
    operations = [
        migrations.RunSQL(
            f"""ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
                CREATE POLICY municipio ON {table}
                USING (municipio_id = NULLIF(current_setting('social.municipio', true), '')::bigint)
                WITH CHECK (municipio_id = NULLIF(current_setting('social.municipio', true), '')::bigint);""",
            f"DROP POLICY municipio ON {table}; ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        ) for table in tables
    ]
