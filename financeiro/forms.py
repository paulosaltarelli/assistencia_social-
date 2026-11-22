import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (Compromisso, Conciliacao, Despesa, Dotacao, Exercicio, Fonte, Fundo,
                     Lancamento, Natureza, Programa, Receita, RevisaoOrcamento, VinculoSocial)


class FormMunicipal(forms.ModelForm):
    def __init__(self, *args, municipio, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.municipio = municipio
        for campo in self.fields.values():
            if isinstance(campo, forms.ModelChoiceField):
                qs = campo.queryset.filter(municipio=municipio)
                if qs.model in {Fonte, Fundo, Programa, Natureza}:
                    qs = qs.filter(ativa=True)
                if qs.model is Dotacao:
                    qs = qs.select_related("exercicio", "programa")
                campo.queryset = qs
            if isinstance(campo, forms.DateField):
                campo.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class FormDespesa(FormMunicipal):
    class Meta:
        model = Despesa
        fields = ["dotacao", "data", "processo", "documento", "descricao", "categoria",
                  "fornecedor", "cnpj", "valor", "observacoes"]

    def clean_cnpj(self):
        valor = re.sub(r"[\s./-]", "", self.cleaned_data["cnpj"]).upper()
        if not valor:
            return valor
        if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", valor) or len(set(valor)) == 1:
            raise ValidationError("Confira o CNPJ informado.")
        base = [ord(c) - 48 for c in valor[:12]]
        for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                      [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
            resto = sum(a * b for a, b in zip(base, pesos)) % 11
            base.append(0 if resto < 2 else 11 - resto)
        if valor[-2:] != "".join(str(n) for n in base[-2:]):
            raise ValidationError("Confira os dígitos verificadores do CNPJ.")
        return valor


class FormEdicao(FormDespesa):
    versao_anterior = forms.IntegerField(widget=forms.HiddenInput, min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("dotacao")
        self.initial["versao_anterior"] = self.instance.versao


class FormEtapa(FormMunicipal):
    class Meta:
        model = Lancamento
        fields = ["data", "referencia", "valor", "anterior", "compromisso", "documento"]

    def __init__(self, *args, despesa, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.despesa = despesa
        self.instance.tipo = tipo
        if tipo == "empenho":
            self.fields.pop("anterior")
            self.fields["compromisso"].queryset = Compromisso.objects.filter(
                municipio=despesa.municipio, dotacao=despesa.dotacao, finalizado_em__isnull=True)
            self.fields["compromisso"].help_text = "Selecione somente para converter todo o valor de um compromisso em empenho."
        else:
            self.fields.pop("compromisso")
            anterior = "empenho" if tipo == "liquidacao" else "liquidacao"
            campo = self.fields["anterior"]
            campo.required = True
            campo.label = "Empenho de origem" if tipo == "liquidacao" else "Liquidação de origem"
            campo.queryset = Lancamento.objects.filter(municipio=despesa.municipio, despesa=despesa, tipo=anterior)


class FormCompromisso(FormMunicipal):
    class Meta:
        model = Compromisso
        fields = ["referencia", "dotacao", "descricao", "valor", "data", "vencimento", "situacao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["situacao"].choices = Compromisso.Situacao.choices[:3]


class FormConciliacao(FormMunicipal):
    class Meta:
        model = Conciliacao
        fields = ["referencia", "data", "situacao", "observacoes"]


class FormSituacao(forms.Form):
    situacao = forms.ChoiceField(label="Nova situação", choices=[
        choice for choice in Compromisso.Situacao.choices if choice[0] != "empenhado"])
    data = forms.DateField(label="Data da alteração", initial=timezone.localdate,
                           widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))


class FormOrigem(forms.Form):
    tipo = forms.ChoiceField(label="Origem da despesa", choices=[
        ("beneficio", "Benefício eventual"), ("material", "Pedido de material"), ("vale", "Vale-Alimentação")])
    protocolo = forms.UUIDField(label="Código do registro social",
                                help_text="Utilize o identificador da solicitação, do pedido ou da concessão.")


CAMPOS_CLASSIFICACAO = ["codigo", "nome", "ativa"]
CADASTROS = {
    "exercicios": ("Exercícios", Exercicio, ["ano"]),
    "fontes": ("Fontes de recursos", Fonte, [*CAMPOS_CLASSIFICACAO, "origem", "finalidade", "restricoes"]),
    "fundos": ("Fundos", Fundo, CAMPOS_CLASSIFICACAO),
    "programas": ("Programas e ações", Programa, CAMPOS_CLASSIFICACAO),
    "naturezas": ("Naturezas da despesa", Natureza, CAMPOS_CLASSIFICACAO),
    "dotacoes": ("Dotações orçamentárias", Dotacao,
                 ["exercicio", "codigo", "fonte", "fundo", "programa", "natureza", "valor_inicial", "saldo_inicial"]),
    "revisoes": ("Créditos e anulações", RevisaoOrcamento, ["dotacao", "data", "tipo", "valor", "documento", "motivo"]),
    "receitas": ("Receitas e transferências", Receita, ["dotacao", "tipo", "data", "origem", "documento", "valor", "comprovante"]),
    "compromissos": ("Compromissos financeiros", Compromisso, None),
}


def formulario_cadastro(tipo):
    _, modelo, campos = CADASTROS[tipo]
    return FormCompromisso if modelo is Compromisso else forms.modelform_factory(modelo, form=FormMunicipal, fields=campos)
