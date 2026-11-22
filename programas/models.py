import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


POSITIVO = MinValueValidator(Decimal("0.01"))


class Municipal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        for nome in ("cidadao", "familia", "tipo", "material", "pedido", "solicitacao", "concessao"):
            campo_id = getattr(self, nome + "_id", None)
            if campo_id:
                relacionado = getattr(self, nome)
                if relacionado.municipio_id != self.municipio_id:
                    raise ValidationError({nome: "Registro indisponível para este município."})
        if getattr(self, "cidadao_id", None) and getattr(self, "familia_id", None):
            if self.cidadao.familia_id != self.familia_id:
                raise ValidationError({"familia": "Selecione a família vinculada ao cidadão."})


class TipoBeneficio(Municipal):
    nome = models.CharField(max_length=120)
    regra_local = models.TextField(help_text="Norma municipal e critérios aprovados para este programa.")
    vigencia_inicio = models.DateField()
    vigencia_fim = models.DateField(null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome", "vigencia_inicio", "id"]
        constraints = [models.CheckConstraint(condition=Q(vigencia_fim__isnull=True) | Q(vigencia_fim__gte=models.F("vigencia_inicio")), name="programa_vigencia_valida")]

    def clean(self):
        super().clean()
        if self.vigencia_fim and self.vigencia_fim < self.vigencia_inicio:
            raise ValidationError({"vigencia_fim": "A data final deve ser igual ou posterior à inicial."})

    def __str__(self):
        return f"{self.nome} · {self.vigencia_inicio:%d/%m/%Y}"


class SolicitacaoBeneficio(Municipal):
    SITUACOES = [(v, t) for v, t in [
        ("solicitado", "Solicitado"), ("analise", "Em análise"), ("aprovado", "Aprovado"),
        ("parcial", "Aprovado parcialmente"), ("indeferido", "Indeferido"),
        ("entregue", "Entregue"), ("cancelado", "Cancelado")]]
    cidadao = models.ForeignKey("atendimentos.Cidadao", on_delete=models.PROTECT, null=True, blank=True)
    familia = models.ForeignKey("atendimentos.Familia", on_delete=models.PROTECT)
    tipo = models.ForeignKey(TipoBeneficio, on_delete=models.PROTECT)
    regra_aplicada = models.JSONField(default=dict, editable=False)
    solicitado_em = models.DateField(default=timezone.localdate)
    analisado_em = models.DateTimeField(null=True, editable=False)
    concedido_em = models.DateTimeField(null=True, editable=False)
    entregue_em = models.DateTimeField(null=True, editable=False)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    quantidade_solicitada = models.DecimalField(max_digits=12, decimal_places=2, validators=[POSITIVO])
    quantidade_aprovada = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_solicitado = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    valor_aprovado = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    situacao = models.CharField(max_length=20, choices=SITUACOES, default="solicitado")
    observacoes = models.TextField(blank=True)
    justificativa_tecnica = models.TextField(blank=True)

    class Meta:
        ordering = ["-solicitado_em", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantidade_solicitada__gt=0), name="beneficio_solicitado_positivo"),
            models.CheckConstraint(condition=Q(quantidade_aprovada__gte=0) & Q(quantidade_aprovada__lte=models.F("quantidade_solicitada")), name="beneficio_quantidade_limite"),
            models.CheckConstraint(condition=Q(valor_solicitado__gte=0) & Q(valor_aprovado__gte=0) & Q(valor_aprovado__lte=models.F("valor_solicitado")), name="beneficio_valor_limite"),
        ]


class Material(Municipal):
    nome = models.CharField(max_length=120)
    unidade = models.CharField(max_length=30)
    saldo = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    estoque_minimo = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["nome", "id"]
        constraints = [models.CheckConstraint(condition=Q(saldo__gte=0), name="material_saldo_nao_negativo")]

    def __str__(self):
        return f"{self.nome} ({self.unidade})"


class PedidoMaterial(Municipal):
    SITUACOES = [(v, t) for v, t in [
        ("solicitado", "Aguardando análise"), ("analise", "Em avaliação"), ("aprovado", "Aprovado"),
        ("parcial", "Aprovado parcialmente"), ("indeferido", "Indeferido"),
        ("disponibilidade", "Aguardando disponibilidade"), ("entregue", "Entregue"), ("cancelado", "Cancelado")]]
    cidadao = models.ForeignKey("atendimentos.Cidadao", on_delete=models.PROTECT, null=True, blank=True)
    familia = models.ForeignKey("atendimentos.Familia", on_delete=models.PROTECT)
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantidade_solicitada = models.DecimalField(max_digits=12, decimal_places=2, validators=[POSITIVO])
    quantidade_aprovada = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    entregue = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    solicitado_em = models.DateField(default=timezone.localdate)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    justificativa = models.TextField()
    situacao = models.CharField(max_length=20, choices=SITUACOES, default="solicitado")

    class Meta:
        ordering = ["-solicitado_em", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantidade_solicitada__gt=0), name="pedido_quantidade_positiva"),
            models.CheckConstraint(condition=Q(quantidade_aprovada__gte=0) & Q(quantidade_aprovada__lte=models.F("quantidade_solicitada")), name="pedido_aprovacao_limite"),
            models.CheckConstraint(condition=Q(entregue__gte=0) & Q(entregue__lte=models.F("quantidade_aprovada")), name="pedido_entrega_limite"),
        ]


class MovimentoEstoque(Municipal):
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    pedido = models.ForeignKey(PedidoMaterial, on_delete=models.PROTECT, null=True, blank=True)
    tipo = models.CharField(max_length=8, choices=[("entrada", "Entrada"), ("saida", "Saída")])
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, validators=[POSITIVO])
    custo_unitario = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    comprovante = models.CharField(max_length=200)
    criado_em = models.DateTimeField(auto_now_add=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-criado_em", "-id"]
        constraints = [models.CheckConstraint(condition=Q(quantidade__gt=0) & Q(custo_unitario__gte=0), name="movimento_valores_validos")]


class ConcessaoVale(Municipal):
    SITUACOES = [("analise", "Aguardando análise"), ("ativo", "Ativo"), ("suspenso", "Suspenso"), ("desligado", "Desligado"), ("indeferido", "Indeferido")]
    cidadao = models.ForeignKey("atendimentos.Cidadao", on_delete=models.PROTECT)
    familia = models.ForeignKey("atendimentos.Familia", on_delete=models.PROTECT)
    valor = models.DecimalField(max_digits=14, decimal_places=2, validators=[POSITIVO])
    periodicidade = models.CharField(max_length=20, choices=[("mensal", "Mensal"), ("quinzenal", "Quinzenal"), ("unico", "Pagamento único")])
    situacao = models.CharField(max_length=20, choices=SITUACOES, default="analise")
    solicitado_em = models.DateField(default=timezone.localdate)
    incluido_em = models.DateTimeField(null=True, editable=False)
    atualizado_em = models.DateTimeField(auto_now=True)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-atualizado_em", "-id"]
        constraints = [models.CheckConstraint(condition=Q(valor__gt=0), name="vale_valor_positivo")]


class HistoricoBase(Municipal):
    anterior = models.CharField(max_length=20, blank=True)
    situacao = models.CharField(max_length=20)
    motivo = models.TextField()
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criado_em = models.DateTimeField(auto_now_add=True)
    dados = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
        ordering = ["-criado_em", "-id"]


class HistoricoBeneficio(HistoricoBase):
    solicitacao = models.ForeignKey(SolicitacaoBeneficio, on_delete=models.PROTECT, related_name="historico")


class HistoricoPedido(HistoricoBase):
    pedido = models.ForeignKey(PedidoMaterial, on_delete=models.PROTECT, related_name="historico")


class HistoricoVale(HistoricoBase):
    concessao = models.ForeignKey(ConcessaoVale, on_delete=models.PROTECT, related_name="historico")
