from django.db import migrations
from atendimentos.rls import proteger


class Migration(migrations.Migration):
    dependencies = [("contas", "0001_initial")]
    operations = [
        migrations.RunSQL(proteger(tabela, permissoes="SELECT, INSERT, UPDATE, DELETE"))
        for tabela in ["contas_ajustepermissao", "contas_secretaria", "contas_recuperacao"]
    ] + [migrations.RunSQL("""
        REVOKE ALL ON contas_limitelogin, contas_eventoautenticacao FROM PUBLIC, social_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON contas_limitelogin TO social_app;
        GRANT INSERT ON contas_eventoautenticacao TO social_app;
        GRANT SELECT(id) ON contas_eventoautenticacao TO social_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO social_app;
        GRANT INSERT ON auth_user TO social_app;
        GRANT UPDATE(first_name, email, password, is_active) ON auth_user TO social_app;
        GRANT INSERT ON atendimentos_vinculo TO social_app;
        GRANT UPDATE(perfil) ON atendimentos_vinculo TO social_app;
        CREATE FUNCTION contas_validar_recuperacao(seletor uuid, assinatura varchar)
        RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $func$
            SELECT municipio_id FROM public.contas_recuperacao
            WHERE id = seletor AND resumo = assinatura
              AND utilizada IS NULL AND expira > now()
        $func$;
        REVOKE ALL ON FUNCTION contas_validar_recuperacao(uuid, varchar) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION contas_validar_recuperacao(uuid, varchar) TO social_app;
    """)]
