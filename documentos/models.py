import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Categoria(models.TextChoices):
    NOTA = "nota", "Nota fiscal"
    PAGAMENTO = "pagamento", "Comprovante de pagamento"
    RECIBO = "recibo", "Recibo"
    CONTRATO = "contrato", "Contrato"
    ORDEM = "ordem", "Ordem de serviço"
    ENTREGA = "entrega", "Comprovante de entrega"
    EMPENHO = "empenho", "Nota de empenho"
    LIQUIDACAO = "liquidacao", "Comprovante de liquidação"
    RELATORIO = "relatorio", "Relatório"
    OUTRO = "outro", "Outro documento"


class Estado(models.TextChoices):
    ANEXADO = "anexado", "Documento anexado"
    AGUARDANDO = "aguardando", "Aguardando conferência"
    CONFERIDO = "conferido", "Conferido"
    PENDENCIA = "pendencia", "Com pendência"
    REJEITADO = "rejeitado", "Rejeitado"
    REGULARIZADO = "regularizado", "Regularizado"


ALVOS = ("despesa", "beneficio", "material", "vale", "receita")


class Documento(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)
    categoria = models.CharField(max_length=12, choices=Categoria.choices)
    sigilo_tecnico = models.BooleanField(default=False)
    despesa = models.ForeignKey("financeiro.Despesa", null=True, blank=True, on_delete=models.PROTECT, related_name="documentos")
    receita = models.ForeignKey("financeiro.Receita", null=True, blank=True, on_delete=models.PROTECT, related_name="documentos")
    beneficio = models.ForeignKey("programas.SolicitacaoBeneficio", null=True, blank=True, on_delete=models.PROTECT, related_name="documentos")
    material = models.ForeignKey("programas.PedidoMaterial", null=True, blank=True, on_delete=models.PROTECT, related_name="documentos")
    vale = models.ForeignKey("programas.ConcessaoVale", null=True, blank=True, on_delete=models.PROTECT, related_name="documentos")
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(despesa__isnull=False, beneficio__isnull=True, material__isnull=True, vale__isnull=True, receita__isnull=True)
                    | models.Q(despesa__isnull=True, beneficio__isnull=False, material__isnull=True, vale__isnull=True, receita__isnull=True)
                    | models.Q(despesa__isnull=True, beneficio__isnull=True, material__isnull=False, vale__isnull=True, receita__isnull=True)
                    | models.Q(despesa__isnull=True, beneficio__isnull=True, material__isnull=True, vale__isnull=False, receita__isnull=True)
                    | models.Q(despesa__isnull=True, beneficio__isnull=True, material__isnull=True, vale__isnull=True, receita__isnull=False)
                ), name="doc_um_vinculo",
            )
        ]

    @property
    def alvo(self):
        return next(campo for campo in ALVOS if getattr(self, f"{campo}_id") is not None)


class Versao(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)
    documento = models.ForeignKey(Documento, on_delete=models.PROTECT, related_name="versoes")
    sequencia = models.PositiveIntegerField()
    operacao = models.UUIDField()
    nome = models.CharField(max_length=150)
    mime = models.CharField(max_length=40)
    tamanho = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    conteudo = models.BinaryField()
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    observacao = models.CharField(max_length=500, blank=True)
    numero_nota = models.CharField(max_length=40, blank=True)
    serie_nota = models.CharField(max_length=12, blank=True)
    chave_nfe = models.CharField(max_length=44, blank=True)
    data_emissao = models.DateField(null=True, blank=True)
    cnpj_emissor = models.CharField(max_length=14, blank=True)
    razao_social = models.CharField(max_length=160, blank=True)
    valor_nota = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    descricao_itens = models.CharField(max_length=500, blank=True)
    processo_referencia = models.CharField(max_length=80, blank=True)
    empenho_referencia = models.CharField(max_length=80, blank=True)
    vencimento = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["documento", "sequencia"], name="doc_numero_versao_unico"),
            models.UniqueConstraint(fields=["municipio", "operacao"], name="doc_operacao_unica"),
            models.CheckConstraint(condition=models.Q(sequencia__gt=0), name="doc_sequencia_positiva"),
            models.CheckConstraint(condition=models.Q(tamanho__gt=0, tamanho__lte=8388608), name="doc_limite_original"),
        ]
        indexes = [
            models.Index(fields=["municipio", "chave_nfe"], name="doc_busca_chave"),
            models.Index(fields=["municipio", "cnpj_emissor", "numero_nota", "serie_nota", "valor_nota"], name="doc_busca_combinacao"),
        ]


class Conferencia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)
    versao = models.ForeignKey(Versao, on_delete=models.PROTECT, related_name="conferencias")
    situacao = models.CharField(max_length=14, choices=Estado.choices)
    motivo = models.CharField(max_length=500, blank=True)
    providencia = models.CharField(max_length=500, blank=True)
    observacao = models.CharField(max_length=500, blank=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)
