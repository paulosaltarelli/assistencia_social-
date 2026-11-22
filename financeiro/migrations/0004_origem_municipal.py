from django.db import migrations


ORIGENS = """
CREATE FUNCTION financeiro_validar_origem_municipal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.beneficio_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM programas_solicitacaobeneficio WHERE id = NEW.beneficio_id AND municipio_id = NEW.municipio_id
        )) OR (NEW.material_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM programas_pedidomaterial WHERE id = NEW.material_id AND municipio_id = NEW.municipio_id
        )) OR (NEW.vale_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM programas_concessaovale WHERE id = NEW.vale_id AND municipio_id = NEW.municipio_id
        )) THEN
        RAISE EXCEPTION 'A origem social deve pertencer ao município da despesa' USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER fin_origem_municipal BEFORE INSERT OR UPDATE ON financeiro_vinculosocial
    FOR EACH ROW EXECUTE FUNCTION financeiro_validar_origem_municipal();
"""


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0003_controle_municipal")]
    operations = [
        migrations.RunSQL(ORIGENS, reverse_sql="""
            DROP TRIGGER fin_origem_municipal ON financeiro_vinculosocial;
            DROP FUNCTION financeiro_validar_origem_municipal();
        """)
    ]
