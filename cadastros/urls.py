from django.urls import path
from . import views

app_name = 'cadastros'
urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('familias/', views.familias, name='familias'),
    path('familias/nova/', views.familia_form, name='familia_nova'),
    path('familias/<uuid:pk>/', views.familia, name='familia'),
    path('familias/<uuid:pk>/editar/', views.familia_form, name='familia_editar'),
    path('pessoas/nova/', views.pessoa_form, name='pessoa_nova'),
    path('pessoas/<uuid:pk>/', views.pessoa, name='pessoa'),
    path('pessoas/<uuid:pk>/editar/', views.pessoa_form, name='pessoa_editar'),
    path('atendimentos/', views.atendimentos, name='atendimentos'),
    path('atendimentos/novo/', views.atendimento_form, name='atendimento_novo'),
    path('atendimentos/<uuid:pk>/', views.atendimento, name='atendimento'),
    path('atendimentos/<uuid:pk>/editar/', views.atendimento_form, name='atendimento_editar'),
]
