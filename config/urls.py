from django.urls import include, path
from contas.views import Entrar, Sair
from atendimentos.inicio import cadastro_legado, inicio
from atendimentos.views import health

urlpatterns = [
    path("", inicio, name="painel"),
    path("entrar/", Entrar.as_view(), name="login"),
    path("sair/", Sair.as_view(), name="logout"),
    path("contas/", include("contas.urls")),
    path("cadastros/", include("cadastros.urls")),
    path("cadastros/<slug:cadastro>/", cadastro_legado, name="cadastro"),
    path("programas/", include("programas.urls")),
    path("financeiro/", include("financeiro.urls")),
    path("documentos/", include("documentos.urls")),
    path("relatorios/", include("relatorios.urls")),
    path("health/", health),
]
