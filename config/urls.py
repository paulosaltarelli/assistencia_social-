from django.contrib.auth.views import LogoutView
from django.urls import path
from atendimentos.views import Entrada, health, painel

urlpatterns = [
    path("", painel, name="painel"),
    path("entrar/", Entrada.as_view(), name="login"),
    path("sair/", LogoutView.as_view(), name="logout"),
    path("health/", health),
]
