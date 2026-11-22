from django import forms
from django.utils import timezone
from programas.models import ConcessaoVale, Material, TipoBeneficio


class FiltrosRelatorio(forms.Form):
    inicio = forms.DateField(label='De', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    fim = forms.DateField(label='Até', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    bairro = forms.CharField(label='Bairro', required=False, max_length=120)
    modalidade = forms.ModelChoiceField(label='Modalidade de benefício', queryset=TipoBeneficio.objects.none(), required=False, empty_label='Todas as modalidades')
    material = forms.ModelChoiceField(label='Material', queryset=Material.objects.none(), required=False, empty_label='Todos os materiais')
    situacao_vale = forms.ChoiceField(label='Situação do vale', choices=[('', 'Todas as situações'), *ConcessaoVale.SITUACOES], required=False)
    nominal = forms.BooleanField(label='Incluir identificação das pessoas', required=False)

    def __init__(self, *args, municipio=None, **kwargs):
        super().__init__(*args, **kwargs)
        if municipio is not None:
            self.fields['modalidade'].queryset = TipoBeneficio.objects.filter(municipio=municipio)
            self.fields['material'].queryset = Material.objects.filter(municipio=municipio)

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get('inicio'), dados.get('fim')
        if fim is None and 'fim' not in self.errors:
            fim = dados['fim'] = timezone.localdate()
        if inicio and fim and inicio > fim:
            self.add_error('fim', 'Informe uma data igual ou posterior ao início.')
        if fim and fim > timezone.localdate():
            self.add_error('fim', 'Escolha uma data até hoje.')
        return dados
