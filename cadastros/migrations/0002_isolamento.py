from django.db import migrations
from atendimentos.rls import proteger


INTEGRIDADE = """
CREATE FUNCTION cadastros_validar_vinculos() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE municipio_rel bigint; familia_rel uuid;
BEGIN
    IF TG_TABLE_NAME = 'cadastros_complementopessoa' THEN
        SELECT municipio_id INTO municipio_rel FROM atendimentos_cidadao WHERE id=NEW.cidadao_id;
    ELSIF TG_TABLE_NAME = 'cadastros_complementofamilia' THEN
        SELECT municipio_id INTO municipio_rel FROM atendimentos_familia WHERE id=NEW.familia_id;
        IF NEW.responsavel_id IS NOT NULL THEN
            SELECT familia_id INTO familia_rel FROM atendimentos_cidadao WHERE id=NEW.responsavel_id AND municipio_id=NEW.municipio_id;
            IF familia_rel IS DISTINCT FROM NEW.familia_id THEN RAISE EXCEPTION 'Vínculo familiar inválido' USING ERRCODE='23514'; END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'cadastros_acompanhamentoatendimento' THEN
        SELECT municipio_id INTO municipio_rel FROM atendimentos_atendimento WHERE id=NEW.atendimento_id;
        IF NEW.responsavel_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM atendimentos_vinculo WHERE usuario_id=NEW.responsavel_id AND municipio_id=NEW.municipio_id) THEN
            RAISE EXCEPTION 'Responsável inválido' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'cadastros_notatecnica' THEN
        SELECT municipio_id INTO municipio_rel FROM cadastros_acompanhamentoatendimento WHERE id=NEW.acompanhamento_id;
    ELSE
        SELECT municipio_id INTO municipio_rel FROM atendimentos_vinculo WHERE usuario_id=NEW.autor_id;
    END IF;
    IF municipio_rel IS DISTINCT FROM NEW.municipio_id THEN RAISE EXCEPTION 'Vínculo municipal inválido' USING ERRCODE='23514'; END IF;
    RETURN NEW;
END;
$$;
"""
TABELAS = ['cadastros_complementopessoa', 'cadastros_complementofamilia', 'cadastros_acompanhamentoatendimento', 'cadastros_notatecnica', 'cadastros_atualizacaocadastro']


class Migration(migrations.Migration):
    dependencies = [('cadastros', '0001_initial')]
    operations = [migrations.RunSQL(proteger(tabela, permissoes='SELECT, INSERT' if tabela.endswith('atualizacaocadastro') else 'SELECT, INSERT, UPDATE')) for tabela in TABELAS] + [
        migrations.RunSQL('''
            GRANT UPDATE(nome, familia_id) ON atendimentos_cidadao TO social_app;
            GRANT UPDATE(referencia) ON atendimentos_familia TO social_app;
            GRANT UPDATE(cidadao_id, unidade, encaminhamento) ON atendimentos_atendimento TO social_app;
        '''),
        migrations.RunSQL(INTEGRIDADE),
    ] + [migrations.RunSQL(f'CREATE TRIGGER validar_municipio BEFORE INSERT OR UPDATE ON {tabela} FOR EACH ROW EXECUTE FUNCTION cadastros_validar_vinculos();') for tabela in TABELAS]
    operations += [migrations.RunSQL('''
        CREATE FUNCTION cadastros_validar_base() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE municipio_rel bigint;
        BEGIN
            IF TG_TABLE_NAME = 'atendimentos_cidadao' THEN
                SELECT municipio_id INTO municipio_rel FROM atendimentos_familia WHERE id=NEW.familia_id;
                IF EXISTS (SELECT 1 FROM cadastros_complementofamilia WHERE responsavel_id=NEW.id AND familia_id <> NEW.familia_id) THEN
                    RAISE EXCEPTION 'Atualize o responsável familiar antes da transferência' USING ERRCODE='23514';
                END IF;
            ELSIF NEW.cidadao_id IS NULL THEN
                RETURN NEW;
            ELSE
                SELECT municipio_id INTO municipio_rel FROM atendimentos_cidadao WHERE id=NEW.cidadao_id;
            END IF;
            IF municipio_rel IS DISTINCT FROM NEW.municipio_id THEN RAISE EXCEPTION 'Vínculo municipal inválido' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER cadastros_vinculo_base BEFORE INSERT OR UPDATE ON atendimentos_cidadao FOR EACH ROW EXECUTE FUNCTION cadastros_validar_base();
        CREATE TRIGGER cadastros_vinculo_base BEFORE INSERT OR UPDATE ON atendimentos_atendimento FOR EACH ROW EXECUTE FUNCTION cadastros_validar_base();
    ''')]
