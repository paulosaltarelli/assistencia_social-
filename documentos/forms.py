import re
import uuid

from django import forms

from .models import Categoria, Estado


class DocumentoForm(forms.Form):
    categoria = forms.ChoiceField(label="Tipo de documento", choices=Categoria.choices)
    arquivo = forms.FileField(label="Arquivo original", widget=forms.ClearableFileInput(attrs={
        "accept": ".pdf,.xml,.jpg,.jpeg,.png",
    }), help_text="PDF, XML, JPG ou PNG de até 8 MiB.")
    operacao = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    base = forms.IntegerField(widget=forms.HiddenInput, min_value=0, initial=0)
    observacao = forms.CharField(label="Observação sobre o documento", max_length=500, required=False)
    sigilo_tecnico = forms.BooleanField(label="Documento técnico sigiloso", required=False)
    vencimento = forms.DateField(label="Vencimento do documento", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    numero_nota = forms.CharField(label="Número da nota", max_length=40, required=False)
    serie_nota = forms.CharField(label="Série", max_length=12, required=False)
    chave_nfe = forms.CharField(label="Chave de acesso da NF-e", max_length=60, required=False)
    data_emissao = forms.DateField(label="Data de emissão", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    cnpj_emissor = forms.CharField(label="CNPJ do emitente", max_length=20, required=False)
    razao_social = forms.CharField(label="Razão social", max_length=160, required=False)
    valor_nota = forms.DecimalField(label="Valor total da nota (R$)", max_digits=16, decimal_places=2, min_value=0, required=False)
    descricao_itens = forms.CharField(label="Produtos ou serviços", max_length=500, required=False)
    processo_referencia = forms.CharField(label="Processo administrativo", max_length=80, required=False)
    empenho_referencia = forms.CharField(label="Número do empenho", max_length=80, required=False)

    def __init__(self, *args, categoria_fixa=None, permitir_sigilo=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not permitir_sigilo or categoria_fixa is not None:
            self.fields.pop("sigilo_tecnico")
        if categoria_fixa is not None:
            self.fields["categoria"].initial = categoria_fixa
            self.fields["categoria"].disabled = True

    def clean_cnpj_emissor(self):
        valor = re.sub(r"[./\s-]", "", self.cleaned_data["cnpj_emissor"]).upper()
        if valor and not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", valor):
            raise forms.ValidationError("Informe o CNPJ com 14 posições.")
        return valor

    def clean_chave_nfe(self):
        chave = re.sub(r"\s", "", self.cleaned_data["chave_nfe"])
        if chave and not re.fullmatch(r"[0-9]{44}", chave):
            raise forms.ValidationError("A chave de acesso deve ter 44 dígitos.")
        return chave

    def clean(self):
        campos = super().clean()
        if campos.get("categoria") == Categoria.NOTA:
            for nome in ("numero_nota", "data_emissao", "cnpj_emissor", "razao_social", "valor_nota"):
                if campos.get(nome) in ("", None) and nome not in self.errors:
                    self.add_error(nome, "Obrigatório para nota fiscal.")
        return campos


class ConferenciaForm(forms.Form):
    situacao = forms.ChoiceField(label="Resultado da conferência", choices=[
        opcao for opcao in Estado.choices if opcao[0] != Estado.ANEXADO
    ])
    motivo = forms.CharField(label="Motivo da pendência ou rejeição", max_length=500, required=False)
    providencia = forms.CharField(label="Providência realizada", max_length=500, required=False)
    observacao = forms.CharField(label="Observação da conferência", max_length=500, required=False)

    def clean(self):
        dados = super().clean()
        if dados.get("situacao") in (Estado.PENDENCIA, Estado.REJEITADO) and not dados.get("motivo"):
            self.add_error("motivo", "Registre o motivo para o responsável pela regularização.")
        if dados.get("situacao") == Estado.REGULARIZADO and not dados.get("providencia"):
            self.add_error("providencia", "Descreva como a pendência foi resolvida.")
        return dados


class FiltrosForm(forms.Form):
    exercicio = forms.IntegerField(label="Exercício", min_value=1900, max_value=9999, required=False)
    inicio = forms.DateField(label="Despesa a partir de", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    fim = forms.DateField(label="Despesa até", required=False, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    fundo = forms.ChoiceField(label="Fundo", required=False)
    fonte = forms.ChoiceField(label="Fonte", required=False)
    programa = forms.ChoiceField(label="Programa", required=False)

    def __init__(self, *args, municipio, **kwargs):
        from financeiro.models import Despesa
        super().__init__(*args, **kwargs)
        for campo in ("fundo", "fonte", "programa"):
            relacao = f"dotacao__{campo}"
            opcoes = Despesa.objects.filter(municipio=municipio).order_by(f"{relacao}__nome", f"{relacao}__pk").values_list(f"{relacao}__pk", f"{relacao}__nome").distinct()
            self.fields[campo].choices = [("", "Todos")] + list(opcoes)

    def clean(self):
        dados = super().clean()
        if dados.get("inicio") and dados.get("fim") and dados["inicio"] > dados["fim"]:
            self.add_error("fim", "O fim do período deve ser igual ou posterior ao início.")
        return dados
