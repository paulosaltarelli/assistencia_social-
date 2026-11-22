from django.urls import path
from . import views

app_name = "contas"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("senha/", views.Senha.as_view(), name="senha"),
    path("recuperar/", views.recuperar, name="recuperar"),
    path("definir-senha/", views.acesso, name="acesso"),
    path("profissionais/novo/", views.profissional, name="novo"),
    path("profissionais/<int:pk>/", views.profissional, name="profissional"),
    path("profissionais/<int:pk>/acao/", views.acao, name="acao"),
    path("secretaria/", views.configurar, name="configurar"),
    path("brasao/", views.brasao, name="brasao"),
]
