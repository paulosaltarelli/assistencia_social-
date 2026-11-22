from django.urls import path
from . import views

app_name = "programas"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("beneficios/", views.beneficios, name="beneficios"),
    path("beneficios/novo/", views.beneficio_novo, name="beneficio_novo"),
    path("beneficios/tipos/", views.tipos, name="tipos"),
    path("beneficios/tipos/novo/", views.tipo_novo, name="tipo_novo"),
    path("beneficios/<uuid:pk>/", views.beneficio_detalhe, name="beneficio_detalhe"),
    path("materiais/", views.estoque, name="estoque"),
    path("materiais/novo/", views.material_novo, name="material_novo"),
    path("materiais/pedidos/", views.pedidos, name="pedidos"),
    path("materiais/pedidos/novo/", views.pedido_novo, name="pedido_novo"),
    path("materiais/pedidos/<uuid:pk>/", views.pedido_detalhe, name="pedido_detalhe"),
    path("materiais/<uuid:pk>/", views.material_detalhe, name="material_detalhe"),
    path("vale/", views.vales, name="vales"),
    path("vale/novo/", views.vale_novo, name="vale_novo"),
    path("vale/<uuid:pk>/", views.vale_detalhe, name="vale_detalhe"),
]
