from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("atendimentos", "0003_cidadao_atendimento_cidadao_familia_cidadao_familia"),
        ("sessions", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [
        migrations.RunSQL(
            f"""ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
                CREATE POLICY municipio ON {table} USING
                (municipio_id = NULLIF(current_setting('social.municipio', true), '')::bigint);"""
        ) for table in ["atendimentos_familia", "atendimentos_cidadao"]
    ] + [migrations.RunSQL("""
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM social_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM social_app;
        GRANT SELECT ON auth_user, atendimentos_municipio, atendimentos_vinculo TO social_app;
        GRANT UPDATE(last_login) ON auth_user TO social_app;
        GRANT SELECT, INSERT ON atendimentos_atendimento, atendimentos_familia, atendimentos_cidadao TO social_app;
        GRANT INSERT ON atendimentos_auditoria TO social_app;
        GRANT SELECT(id) ON atendimentos_auditoria TO social_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO social_app;
    """)]
