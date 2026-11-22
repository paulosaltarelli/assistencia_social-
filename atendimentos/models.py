import uuid
from django.conf import settings
from django.db import models


class Municipio(models.Model):
    nome = models.CharField(max_length=120)


class Vinculo(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    municipio = models.ForeignKey(Municipio, on_delete=models.PROTECT)
    perfil = models.CharField(max_length=10, choices=[("tecnico", "Técnico"), ("auditor", "Auditor"), ("gestor", "Gestor")])


class Atendimento(models.Model):
    cidadao = models.ForeignKey("Cidadao", on_delete=models.PROTECT, null=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey(Municipio, on_delete=models.PROTECT)
    unidade = models.CharField(max_length=100)
    encaminhamento = models.CharField(max_length=200)
    criado = models.DateTimeField(auto_now_add=True)


class Auditoria(models.Model):
    municipio = models.ForeignKey(Municipio, on_delete=models.PROTECT)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    evento = models.CharField(max_length=40)
    objeto = models.UUIDField(null=True)
    instante = models.DateTimeField(auto_now_add=True)


class Familia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey(Municipio, on_delete=models.PROTECT)
    referencia = models.CharField(max_length=100)

    def __str__(self):
        return self.referencia


class Cidadao(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey(Municipio, on_delete=models.PROTECT)
    familia = models.ForeignKey(Familia, on_delete=models.PROTECT)
    nome = models.CharField(max_length=120)

    def __str__(self):
        return self.nome
