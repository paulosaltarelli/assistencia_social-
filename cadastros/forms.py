from django import forms
from django.utils import timezone
from .identificacao import documento
from .models import ComplementoFamilia, ComplementoPessoa, AcompanhamentoAtendimento


class BuscaDocumento(forms.Form):
    tipo = forms.ChoiceField(choices=[('cpf', 'CPF'), ('nis', 'NIS')], label='Documento')
    numero = forms.CharField(label='Número', max_length=18, widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))

    def clean(self):
        dados = super().clean()
        if dados.get('tipo') and dados.get('numero'):
            dados['numero'] = documento(dados['numero'], dados['tipo'])
        return dados


class PessoaForm(forms.ModelForm):
    nome = forms.CharField(label='Nome completo', max_length=120)
    cpf = forms.CharField(label='CPF (se disponível)', required=False, max_length=18, help_text='Informe apenas para inclusão ou correção. Em branco preserva o documento existente.', widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))
    nis = forms.CharField(label='NIS (se disponível)', required=False, max_length=18, help_text='Em branco preserva o documento existente.', widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))
    familia_id = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = ComplementoPessoa
        fields = ['nome', 'cpf', 'nis', 'familia_id', 'nascimento', 'telefone', 'parentesco']
        widgets = {'nascimento': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def clean_cpf(self):
        return documento(self.cleaned_data['cpf'], 'cpf')

    def clean_nis(self):
        return documento(self.cleaned_data['nis'], 'nis')

    def clean_nascimento(self):
        data = self.cleaned_data.get('nascimento')
        if data and data > timezone.localdate():
            raise forms.ValidationError('A data de nascimento deve ser hoje ou anterior.')
        return data


class FamiliaForm(forms.ModelForm):
    referencia = forms.CharField(label='Referência da família', max_length=100)
    responsavel_id = forms.UUIDField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ComplementoFamilia
        fields = ['referencia', 'responsavel_id', 'endereco', 'numero', 'complemento', 'bairro', 'territorio', 'cidade', 'renda_mensal', 'moradia']
        help_texts = {'renda_mensal': 'Deixe em branco quando não apurada. O valor zero indica renda declarada igual a zero.'}


class AtendimentoForm(forms.ModelForm):
    cidadao_id = forms.UUIDField(widget=forms.HiddenInput)
    unidade = forms.CharField(label='Unidade responsável', max_length=100, help_text='Informe a unidade municipal real que prestou o atendimento.')
    encaminhamento = forms.CharField(label='Resumo administrativo / encaminhamento', max_length=200, widget=forms.Textarea(attrs={'rows': 3}), help_text='Evite detalhes técnicos sensíveis. Use o registro sigiloso quando autorizado.')
    nota_tecnica = forms.CharField(label='Registro técnico sigiloso', required=False, max_length=12000, widget=forms.Textarea(attrs={'rows': 5}))

    class Meta:
        model = AcompanhamentoAtendimento
        fields = ['cidadao_id', 'unidade', 'encaminhamento', 'data_efetiva', 'situacao', 'responsavel', 'proxima_acao', 'retorno', 'sigiloso', 'nota_tecnica']
        widgets = {'data_efetiva': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}), 'retorno': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, municipio, sigilo=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsavel'].queryset = self.fields['responsavel'].queryset.filter(vinculo__municipio=municipio, is_active=True).order_by('username')
        if not sigilo:
            self.fields.pop('nota_tecnica')
            self.fields.pop('sigiloso')

    def clean_data_efetiva(self):
        data = self.cleaned_data['data_efetiva']
        if data > timezone.now():
            raise forms.ValidationError('A data efetiva deve ser hoje ou anterior ao horário atual.')
        return data

    def clean(self):
        dados = super().clean()
        if dados.get('situacao') == 'aguarda' and not dados.get('proxima_acao'):
            self.add_error('proxima_acao', 'Informe a providência aguardada.')
        return dados
