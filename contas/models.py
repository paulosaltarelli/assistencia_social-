import uuid
from django.conf import settings
from django.db import models
from .permissoes import PERMISSOES


class AjustePermissao(models.Model):
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)
    vinculo = models.ForeignKey("atendimentos.Vinculo", related_name="ajustes_permissao", on_delete=models.CASCADE)
    codigo = models.CharField(max_length=40, choices=[(k, v) for k, v in PERMISSOES.items()])
    permitido = models.BooleanField()
    concedido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    atualizado = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["vinculo", "codigo"], name="contas_permissao_unica")]


class Secretaria(models.Model):
    municipio = models.OneToOneField("atendimentos.Municipio", on_delete=models.PROTECT)
    nome = models.CharField(max_length=150, blank=True)
    email_oficial = models.EmailField(blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    endereco = models.CharField(max_length=250, blank=True)
    site_oficial = models.URLField(blank=True)
    brasao = models.BinaryField(null=True, editable=False)
    brasao_tipo = models.CharField(max_length=30, blank=True, editable=False)
    atualizado = models.DateTimeField(auto_now=True)


class Recuperacao(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    resumo = models.CharField(max_length=64)
    expira = models.DateTimeField()
    utilizada = models.DateTimeField(null=True)
    criada = models.DateTimeField(auto_now_add=True)


class LimiteLogin(models.Model):
    chave = models.CharField(max_length=64, primary_key=True)
    tentativas = models.PositiveIntegerField(default=0)
    inicio = models.DateTimeField()


class EventoAutenticacao(models.Model):
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="eventos_autorizados")
    municipio = models.ForeignKey("atendimentos.Municipio", null=True, on_delete=models.PROTECT)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    evento = models.CharField(max_length=40)
    conta_resumo = models.CharField(max_length=64, blank=True)
    instante = models.DateTimeField(auto_now_add=True)
