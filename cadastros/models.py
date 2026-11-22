import uuid
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Municipal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    municipio = models.ForeignKey('atendimentos.Municipio', on_delete=models.PROTECT)
    atualizado = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ComplementoFamilia(Municipal):
    familia = models.OneToOneField('atendimentos.Familia', on_delete=models.PROTECT, related_name='complemento')
    endereco = models.CharField('Logradouro', max_length=150, blank=True)
    numero = models.CharField('Número', max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True, db_index=True)
    territorio = models.CharField('Território', max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    renda_mensal = models.DecimalField('Renda mensal familiar (R$)', max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    moradia = models.CharField('Situação de moradia', max_length=100, blank=True)
    responsavel = models.ForeignKey('atendimentos.Cidadao', null=True, blank=True, on_delete=models.PROTECT, related_name='+')


class ComplementoPessoa(Municipal):
    cidadao = models.OneToOneField('atendimentos.Cidadao', on_delete=models.PROTECT, related_name='complemento')
    cpf_hash = models.CharField(max_length=64, blank=True, editable=False)
    cpf_ultimos = models.CharField(max_length=4, blank=True, editable=False)
    nis_hash = models.CharField(max_length=64, blank=True, editable=False)
    nis_ultimos = models.CharField(max_length=4, blank=True, editable=False)
    nascimento = models.DateField('Data de nascimento', null=True, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    parentesco = models.CharField('Parentesco com a referência familiar', max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['municipio', 'cpf_hash'], condition=~models.Q(cpf_hash=''), name='cadastros_cpf_unico_municipal'),
            models.UniqueConstraint(fields=['municipio', 'nis_hash'], condition=~models.Q(nis_hash=''), name='cadastros_nis_unico_municipal'),
        ]

    @property
    def cpf_mascarado(self):
        return f'***.***.*{self.cpf_ultimos[:2]}-{self.cpf_ultimos[2:]}' if self.cpf_ultimos else 'Não informado'

    @property
    def nis_mascarado(self):
        return f'*******{self.nis_ultimos}' if self.nis_ultimos else 'Não informado'


class AcompanhamentoAtendimento(Municipal):
    atendimento = models.OneToOneField('atendimentos.Atendimento', on_delete=models.PROTECT, related_name='acompanhamento')
    data_efetiva = models.DateTimeField(default=timezone.now)
    situacao = models.CharField('Situação', max_length=20, choices=[('aberto', 'Em acompanhamento'), ('aguarda', 'Aguardando retorno'), ('concluido', 'Concluído')], default='aberto')
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    proxima_acao = models.CharField('Próxima ação', max_length=200, blank=True)
    retorno = models.DateField('Retorno previsto', null=True, blank=True)
    sigiloso = models.BooleanField('Atendimento técnico de acesso restrito', default=False)


class NotaTecnica(Municipal):
    acompanhamento = models.OneToOneField(AcompanhamentoAtendimento, on_delete=models.PROTECT, related_name='nota')
    texto = models.TextField('Registro técnico sigiloso', blank=True)


class AtualizacaoCadastro(Municipal):
    objeto = models.UUIDField(db_index=True)
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    acao = models.CharField(max_length=30)
    campos = models.CharField(max_length=300, blank=True)
    criado = models.DateTimeField(auto_now_add=True)
