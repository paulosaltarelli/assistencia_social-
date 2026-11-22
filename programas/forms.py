import uuid
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from atendimentos.models import Cidadao, Familia, Vinculo
from .models import ConcessaoVale, Material, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio


class MunicipalForm(forms.ModelForm):
    def __init__(self, *args, municipio, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.municipio = municipio
        for nome, modelo in [("cidadao", Cidadao), ("familia", Familia), ("tipo", TipoBeneficio), ("material", Material)]:
            if nome in self.fields:
                self.fields[nome].queryset = modelo.objects.filter(municipio=municipio)
        for nome in ("solicitado_em", "vigencia_inicio", "vigencia_fim"):
            if nome in self.fields:
                self.fields[nome].widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class TipoForm(MunicipalForm):
    class Meta:
        model = TipoBeneficio
        fields = ["nome", "regra_local", "vigencia_inicio", "vigencia_fim", "ativo"]


class BeneficioForm(MunicipalForm):
    class Meta:
        model = SolicitacaoBeneficio
        fields = ["familia", "cidadao", "tipo", "solicitado_em", "quantidade_solicitada", "valor_solicitado", "observacoes", "justificativa_tecnica"]

    def __init__(self, *args, permite_tecnica=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not permite_tecnica:
            self.fields.pop("justificativa_tecnica")


class PedidoForm(MunicipalForm):
    class Meta:
        model = PedidoMaterial
        fields = ["familia", "cidadao", "material", "solicitado_em", "quantidade_solicitada", "justificativa"]


class MaterialForm(MunicipalForm):
    class Meta:
        model = Material
        fields = ["nome", "unidade", "custo_unitario", "estoque_minimo"]


class ValeForm(MunicipalForm):
    class Meta:
        model = ConcessaoVale
        fields = ["familia", "cidadao", "solicitado_em", "valor", "periodicidade"]


class DecisaoForm(forms.Form):
    situacao = forms.ChoiceField()
    quantidade = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, label="Quantidade aprovada")
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, label="Valor aprovado (R$)")
    motivo = forms.CharField(widget=forms.Textarea, label="Fundamentação ou comprovante de entrega")

    def __init__(self, *args, choices, material=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["situacao"].choices = choices
        if material:
            self.fields.pop("valor")

    def clean(self):
        dados = super().clean()
        for nome in ("quantidade", "valor"):
            if nome in self.fields and dados.get(nome) is None:
                dados[nome] = Decimal("0")
        return dados


class MovimentoForm(forms.Form):
    chave = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    quantidade = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    custo_unitario = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, label="Custo unitário (R$)")
    comprovante = forms.CharField(max_length=200, label="Referência do comprovante de recebimento/entrada")

    def __init__(self, *args, entrega=False, **kwargs):
        super().__init__(*args, **kwargs)
        if entrega:
            self.fields.pop("custo_unitario")


class AtualizacaoValeForm(forms.Form):
    situacao = forms.ChoiceField(choices=ConcessaoVale.SITUACOES)
    valor = forms.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    periodicidade = forms.ChoiceField(choices=ConcessaoVale._meta.get_field("periodicidade").choices)
    motivo = forms.CharField(widget=forms.Textarea)


class FiltroForm(forms.Form):
    busca = forms.CharField(required=False, max_length=100, label="Nome ou referência familiar")
    cpf = forms.CharField(required=False, max_length=14, label="CPF do cidadão", widget=forms.TextInput(attrs={"autocomplete": "off"}))
    bairro = forms.CharField(required=False, max_length=100)
    responsavel = forms.ModelChoiceField(queryset=None, required=False, label="Profissional responsável")
    situacao = forms.ChoiceField(required=False)
    inicio = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    fim = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    tipo = forms.ModelChoiceField(queryset=TipoBeneficio.objects.none(), required=False)

    def __init__(self, *args, municipio, choices, beneficio=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["situacao"].choices = [("", "Todas as situações"), *choices]
        usuarios = Vinculo.objects.filter(municipio=municipio).values("usuario_id")
        self.fields["responsavel"].queryset = get_user_model().objects.filter(pk__in=usuarios).order_by("username")
        if beneficio:
            self.fields["tipo"].queryset = TipoBeneficio.objects.filter(municipio=municipio)
        else:
            self.fields.pop("tipo")

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            raise forms.ValidationError("O período final deve ser igual ou posterior ao inicial.")
        return dados

    def clean_cpf(self):
        valor = self.cleaned_data.get("cpf", "")
        if not valor:
            return ""
        from cadastros.identificacao import documento
        return documento(valor, "cpf")
