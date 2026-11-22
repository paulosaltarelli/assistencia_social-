from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone


def dinheiro(rotulo, minimo=Decimal("0.01")):
    return models.DecimalField(rotulo, max_digits=16, decimal_places=2,
                               validators=[MinValueValidator(minimo)])


class RegistroMunicipal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    municipio = models.ForeignKey("atendimentos.Municipio", on_delete=models.PROTECT, editable=False)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Classificacao(RegistroMunicipal):
    codigo = models.CharField("Código", max_length=40)
    nome = models.CharField("Nome", max_length=150)
    ativa = models.BooleanField("Em uso", default=True)

    class Meta:
        abstract = True
        ordering = ["nome", "codigo"]
        constraints = [models.UniqueConstraint("municipio", Lower(Trim("codigo")),
                                               name="fin_%(class)s_codigo_unico")]

    def __str__(self):
        return f"{self.codigo} · {self.nome}"


class Fonte(Classificacao):
    class Origem(models.TextChoices):
        MUNICIPAL = "municipal", "Municipal"
        ESTADUAL = "estadual", "Estadual"
        FEDERAL = "federal", "Federal"
        TRANSFERENCIA = "transferencia", "Transferência"
        CONVENIO = "convenio", "Convênio"
        OUTRA = "outra", "Outra"

    origem = models.CharField("Origem", max_length=20, choices=Origem.choices)
    finalidade = models.CharField("Finalidade", max_length=250)
    restricoes = models.TextField("Restrições de uso", max_length=1500, blank=True)


class Fundo(Classificacao):
    pass


class Programa(Classificacao):
    pass


class Natureza(Classificacao):
    pass


class Exercicio(RegistroMunicipal):
    ano = models.PositiveSmallIntegerField("Ano")

    class Meta:
        ordering = ["-ano"]
        constraints = [
            models.UniqueConstraint(fields=["municipio", "ano"], name="fin_exercicio_unico"),
            models.CheckConstraint(condition=Q(ano__gte=1900, ano__lte=9999), name="fin_exercicio_ano"),
        ]

    def __str__(self):
        return str(self.ano)


class Dotacao(RegistroMunicipal):
    exercicio = models.ForeignKey(Exercicio, verbose_name="Exercício", on_delete=models.PROTECT)
    codigo = models.CharField("Código da dotação", max_length=60)
    fonte = models.ForeignKey(Fonte, on_delete=models.PROTECT)
    fundo = models.ForeignKey(Fundo, on_delete=models.PROTECT)
    programa = models.ForeignKey(Programa, on_delete=models.PROTECT)
    natureza = models.ForeignKey(Natureza, verbose_name="Natureza da despesa", on_delete=models.PROTECT)
    valor_inicial = dinheiro("Orçamento inicial (R$)", minimo=Decimal("0"))
    saldo_inicial = models.DecimalField("Saldo financeiro de abertura atribuído à dotação (R$)", max_digits=16, decimal_places=2, default=0)

    class Meta:
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint("municipio", "exercicio", Lower(Trim("codigo")), name="fin_dotacao_codigo"),
            models.CheckConstraint(condition=Q(valor_inicial__gte=0), name="fin_orcamento_inicial_positivo"),
        ]

    def __str__(self):
        return f"{self.exercicio.ano} · {self.codigo} · {self.programa.nome}"


class RevisaoOrcamento(RegistroMunicipal):
    class Tipo(models.TextChoices):
        CREDITO = "credito", "Crédito adicional"
        ANULACAO = "anulacao", "Anulação"

    dotacao = models.ForeignKey(Dotacao, verbose_name="Dotação", on_delete=models.PROTECT)
    data = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = dinheiro("Valor (R$)")
    documento = models.CharField("Ato ou documento autorizador", max_length=100)
    motivo = models.CharField(max_length=300)

    class Meta:
        constraints = [
            models.UniqueConstraint("dotacao", "tipo", Lower(Trim("documento")), name="fin_revisao_documento"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="fin_revisao_positiva"),
        ]


class Receita(RegistroMunicipal):
    class Tipo(models.TextChoices):
        PREVISTA = "prevista", "Previsão"
        RECEBIDA = "recebida", "Recebimento efetivo"

    dotacao = models.ForeignKey(Dotacao, verbose_name="Dotação de referência", on_delete=models.PROTECT)
    data = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = dinheiro("Valor (R$)")
    origem = models.CharField("Instituição de origem", max_length=150)
    documento = models.CharField("Referência documental", max_length=100)
    comprovante = models.CharField("Referência do comprovante", max_length=140, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint("dotacao", "tipo", Lower(Trim("documento")), Lower(Trim("origem")),
                                    name="fin_receita_documento"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="fin_receita_positiva"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.documento} · {self.origem}"


class Despesa(RegistroMunicipal):
    dotacao = models.ForeignKey(Dotacao, verbose_name="Dotação", on_delete=models.PROTECT)
    data = models.DateField(default=timezone.localdate)
    descricao = models.CharField("Descrição", max_length=250)
    fornecedor = models.CharField("Fornecedor", max_length=160)
    cnpj = models.CharField("CNPJ, se aplicável", max_length=18, blank=True)
    categoria = models.CharField("Categoria", max_length=80)
    valor = dinheiro("Valor da despesa (R$)")
    documento = models.CharField("Número do documento", max_length=100)
    processo = models.CharField("Processo administrativo", max_length=100)
    observacoes = models.TextField("Observações", max_length=1500, blank=True)
    versao = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["-data", "-criado_em", "-id"]
        constraints = [
            models.UniqueConstraint("municipio", Lower(Trim("processo")), Lower(Trim("documento")),
                                    name="fin_despesa_documento_processo"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="fin_despesa_positiva"),
        ]

    def __str__(self):
        return f"{self.processo} · {self.descricao}"


class Compromisso(RegistroMunicipal):
    class Situacao(models.TextChoices):
        PREVISTO = "previsto", "Previsto"
        RESERVADO = "reservado", "Reservado"
        CONTRATACAO = "contratacao", "Em contratação"
        EMPENHADO = "empenhado", "Empenhado"
        CANCELADO = "cancelado", "Cancelado"

    dotacao = models.ForeignKey(Dotacao, verbose_name="Dotação", on_delete=models.PROTECT)
    referencia = models.CharField("Referência do compromisso", max_length=100)
    descricao = models.CharField("Descrição", max_length=250)
    valor = dinheiro("Valor previsto (R$)")
    data = models.DateField(default=timezone.localdate)
    vencimento = models.DateField()
    situacao = models.CharField("Situação", max_length=15, choices=Situacao.choices, default=Situacao.PREVISTO)
    finalizado_em = models.DateField(null=True, editable=False)

    class Meta:
        ordering = ["vencimento", "referencia"]
        constraints = [
            models.UniqueConstraint("municipio", Lower(Trim("referencia")), name="fin_compromisso_referencia"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="fin_compromisso_positivo"),
            models.CheckConstraint(condition=Q(vencimento__gte=models.F("data")), name="fin_compromisso_datas"),
        ]

    def __str__(self):
        return f"{self.referencia} · {self.descricao}"


class Lancamento(RegistroMunicipal):
    class Tipo(models.TextChoices):
        EMPENHO = "empenho", "Empenho"
        LIQUIDACAO = "liquidacao", "Liquidação"
        PAGAMENTO = "pagamento", "Pagamento"

    despesa = models.ForeignKey(Despesa, related_name="lancamentos", on_delete=models.PROTECT)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    anterior = models.ForeignKey("self", verbose_name="Etapa de origem", related_name="derivados",
                                 null=True, blank=True, on_delete=models.PROTECT)
    compromisso = models.OneToOneField(Compromisso, null=True, blank=True, on_delete=models.PROTECT)
    data = models.DateField(default=timezone.localdate)
    referencia = models.CharField("Número da operação", max_length=100)
    documento = models.CharField("Referência do documento comprobatório", max_length=140)
    valor = dinheiro("Valor (R$)")

    class Meta:
        ordering = ["data", "criado_em"]
        constraints = [
            models.UniqueConstraint("despesa", "tipo", Lower(Trim("referencia")), name="fin_etapa_referencia"),
            models.CheckConstraint(condition=Q(valor__gt=0), name="fin_lancamento_positivo"),
            models.CheckConstraint(condition=(
                Q(tipo="empenho", anterior__isnull=True) |
                Q(tipo__in=["liquidacao", "pagamento"], anterior__isnull=False, compromisso__isnull=True)
            ), name="fin_etapa_estrutura"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.referencia} · R$ {self.valor}"


class Historico(RegistroMunicipal):
    objeto = models.UUIDField(db_index=True)
    entidade = models.CharField(max_length=48)
    evento = models.CharField(max_length=80)
    estado = models.JSONField(default=dict)

    class Meta:
        ordering = ["-criado_em", "-id"]


class Conciliacao(RegistroMunicipal):
    despesa = models.ForeignKey(Despesa, related_name="conciliacoes", on_delete=models.PROTECT)
    referencia = models.CharField("Referência na contabilidade oficial", max_length=120)
    data = models.DateField("Data da conferência", default=timezone.localdate)
    situacao = models.CharField("Resultado", max_length=16, choices=[
        ("conferido", "Conferido"), ("divergente", "Divergente"), ("regularizado", "Regularizado")
    ])
    observacoes = models.CharField("Observações", max_length=300)


class VinculoSocial(RegistroMunicipal):
    despesa = models.ForeignKey(Despesa, related_name="origens_sociais", on_delete=models.PROTECT)
    beneficio = models.ForeignKey("programas.SolicitacaoBeneficio", null=True, blank=True, on_delete=models.PROTECT)
    material = models.ForeignKey("programas.PedidoMaterial", null=True, blank=True, on_delete=models.PROTECT)
    vale = models.ForeignKey("programas.ConcessaoVale", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(
                Q(beneficio__isnull=False, material__isnull=True, vale__isnull=True) |
                Q(beneficio__isnull=True, material__isnull=False, vale__isnull=True) |
                Q(beneficio__isnull=True, material__isnull=True, vale__isnull=False)
            ), name="fin_origem_exclusiva"),
            *[models.UniqueConstraint(fields=["despesa", campo], name=f"fin_despesa_unico_{campo}")
              for campo in ("beneficio", "material", "vale")],
        ]
