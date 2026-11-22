from django.db import migrations
from atendimentos.rls import proteger


class Migration(migrations.Migration):
    dependencies = [("programas", "0002_material_estoque_minimo")]
    operations = [
        migrations.RunSQL(proteger(tabela, permissoes="SELECT, INSERT, UPDATE"))
        for tabela in [
            "programas_tipobeneficio", "programas_solicitacaobeneficio", "programas_material",
            "programas_pedidomaterial", "programas_concessaovale",
        ]
    ] + [
        migrations.RunSQL(proteger(tabela, permissoes="SELECT, INSERT"))
        for tabela in [
            "programas_movimentoestoque", "programas_historicobeneficio",
            "programas_historicopedido", "programas_historicovale",
        ]
    ]
