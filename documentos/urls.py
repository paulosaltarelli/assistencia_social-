from django.urls import path

from . import views

app_name = "documentos"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("prestacao-de-contas/", views.prestacao, name="prestacao"),
    path("vinculo/<slug:alvo>/<uuid:pk>/", views.vinculo, name="vinculo"),
    path("vinculo/<slug:alvo>/<uuid:pk>/anexar/", views.anexar, name="anexar"),
    path("item/<uuid:pk>/", views.detalhe, name="detalhe"),
    path("item/<uuid:pk>/nova-versao/", views.substituir, name="substituir"),
    path("versao/<uuid:pk>/conferir/", views.conferir, name="conferir"),
    path("versao/<uuid:pk>/<slug:modo>/", views.arquivo, name="arquivo"),
]
