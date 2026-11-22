from django.urls import path

from . import views

app_name = "financeiro"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("gestor/", views.gestor, name="gestor"),
    path("gestor/auditoria/", views.auditoria, name="auditoria"),
    path("cadastros/<slug:tipo>/", views.cadastro, name="cadastro"),
    path("receitas/<uuid:pk>/", views.receita, name="receita"),
    path("compromissos/<uuid:pk>/situacao/", views.situacao_compromisso, name="situacao_compromisso"),
    path("despesas/", views.central, name="central"),
    path("despesas/nova/", views.nova_despesa, name="nova_despesa"),
    path("despesas/<uuid:pk>/", views.despesa, name="despesa"),
    path("despesas/<uuid:pk>/editar/", views.editar_despesa, name="editar_despesa"),
    path("despesas/<uuid:pk>/etapas/<slug:tipo>/", views.etapa, name="etapa"),
    path("despesas/<uuid:pk>/conciliacao/", views.conciliacao, name="conciliacao"),
    path("despesas/<uuid:pk>/origem/", views.vincular, name="vincular"),
]
