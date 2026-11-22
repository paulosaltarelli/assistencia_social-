"""Executar pelo manage.py shell com as contas fictícias e a credencial da aplicação."""
import os
import uuid
from django.test import Client
from django.db import connection
from atendimentos.models import Familia, Cidadao

senha = os.environ["SOCIAL_DEMO_PASSWORD"]
marcador = str(uuid.uuid4())
cliente = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
assert cliente.get("/health/").content == b"ok"
assert cliente.get("/").status_code == 302


def entrar(nome):
    cliente.get("/entrar/")
    resposta = cliente.post("/entrar/", {
        "username": nome, "password": senha, "csrfmiddlewaretoken": cliente.cookies["csrftoken"].value,
    })
    assert resposta.status_code == 302 and cliente.get("/").status_code == 200


def postar(**campos):
    return cliente.post("/", {**campos, "csrfmiddlewaretoken": cliente.cookies["csrftoken"].value})


entrar("tecnico-a")
assert cliente.post("/", {}).status_code == 403
assert postar(tipo="familia", referencia=marcador).status_code == 302
import re
pagina = cliente.get("/").content.decode()
familia = re.search(r'<option value="([a-f0-9-]+)">' + marcador, pagina)[1]
assert postar(tipo="cidadao", familia=familia, nome="Pessoa fictícia " + marcador).status_code == 302
pagina = cliente.get("/").content.decode()
cidadao = re.search(r'<option value="([a-f0-9-]+)">Pessoa fictícia ' + marcador, pagina)[1]
assert postar(cidadao=cidadao, unidade="CRAS fictício", encaminhamento=marcador).status_code == 302
assert marcador in cliente.get("/").content.decode()
assert not Familia.objects.filter(pk=familia).exists()  # Banco nega acesso sem contexto.
cliente.logout()
entrar("tecnico-b")
assert marcador not in cliente.get("/").content.decode()
assert postar(tipo="cidadao", familia=familia, nome="Teste").status_code == 200
assert postar(cidadao=cidadao, unidade="Teste", encaminhamento="Teste").status_code == 200
cliente.logout()
entrar("auditor-a")
assert marcador in cliente.get("/").content.decode()
assert postar(tipo="familia", referencia="Proibido").status_code == 403
print("OK: login, sessão, CSRF, família, cidadão, atendimento, isolamento e perfil auditor")
