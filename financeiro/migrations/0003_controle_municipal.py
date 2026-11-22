from django.db import migrations

from atendimentos.rls import proteger


TABELAS = ["fonte", "fundo", "programa", "natureza", "exercicio", "dotacao",
           "revisaoorcamento", "receita", "despesa", "compromisso", "lancamento",
           "historico", "conciliacao", "vinculosocial"]


def sql_local():
    instrucoes = []
    for nome in TABELAS:
        tabela = "financeiro_" + nome
        grants = "SELECT, INSERT, UPDATE" if nome in {"despesa", "compromisso"} else "SELECT, INSERT"
        instrucoes.append(proteger(tabela, grants))
    # Chaves compostas também impedem misturar municípios por importações futuras.
    alvos = ["fonte", "fundo", "programa", "natureza", "exercicio", "dotacao", "despesa", "compromisso", "lancamento"]
    for alvo in alvos:
        instrucoes.append(f"ALTER TABLE financeiro_{alvo} ADD CONSTRAINT fin_{alvo}_municipal UNIQUE (id, municipio_id);")
    relacoes = {
        "dotacao": {"fonte": "fonte", "fundo": "fundo", "programa": "programa", "natureza": "natureza", "exercicio": "exercicio"},
        "revisaoorcamento": {"dotacao": "dotacao"}, "receita": {"dotacao": "dotacao"},
        "despesa": {"dotacao": "dotacao"}, "compromisso": {"dotacao": "dotacao"},
        "lancamento": {"despesa": "despesa", "compromisso": "compromisso", "anterior": "lancamento"},
        "conciliacao": {"despesa": "despesa"}, "vinculosocial": {"despesa": "despesa"},
    }
    for origem, campos in relacoes.items():
        for campo, alvo in campos.items():
            instrucoes.append(
                f"ALTER TABLE financeiro_{origem} ADD CONSTRAINT fin_{origem}_{campo}_mun "
                f"FOREIGN KEY ({campo}_id,municipio_id) REFERENCES financeiro_{alvo}(id,municipio_id);"
            )
    return "\n".join(instrucoes)


class Migration(migrations.Migration):
    dependencies = [("financeiro", "0002_initial")]
    operations = [migrations.RunSQL(sql_local())]
