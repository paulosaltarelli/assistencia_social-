from io import BytesIO
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from .models import Secretaria
from .permissoes import PERFIS, PERMISSOES, DELEGACOES


class ProfissionalForm(forms.Form):
    nome = forms.CharField(max_length=150, label="Nome do profissional")
    username = forms.CharField(max_length=150, label="Identificador de acesso")
    email = forms.EmailField(label="E-mail pessoal de trabalho", required=False)
    perfil = forms.ChoiceField(choices=PERFIS)
    permitir = forms.MultipleChoiceField(choices=[(k, v) for k, v in PERMISSOES.items() if k not in DELEGACOES and k != "painel.ver"], required=False, widget=forms.CheckboxSelectMultiple, label="Permissões adicionais")
    negar = forms.MultipleChoiceField(choices=[(k, v) for k, v in PERMISSOES.items() if k not in DELEGACOES and k != "painel.ver"], required=False, widget=forms.CheckboxSelectMultiple, label="Permissões removidas do perfil")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        get_user_model()._meta.get_field("username").run_validators(username)
        return username

    def clean(self):
        data = super().clean()
        if set(data.get("permitir", [])) & set(data.get("negar", [])):
            raise forms.ValidationError("Escolha uma única decisão por permissão.")
        return data


class SecretariaForm(forms.ModelForm):
    imagem_brasao = forms.FileField(required=False, label="Brasão oficial (PNG ou JPEG, até 1 MB)")
    remover_brasao = forms.BooleanField(required=False)

    class Meta:
        model = Secretaria
        fields = ["nome", "email_oficial", "telefone", "endereco", "site_oficial"]
        labels = {"nome": "Nome oficial da Secretaria", "endereco": "Endereço de atendimento", "site_oficial": "Site oficial"}

    def clean_imagem_brasao(self):
        arquivo = self.cleaned_data.get("imagem_brasao")
        if not arquivo:
            return None
        if arquivo.size > 1024 * 1024:
            raise forms.ValidationError("O arquivo deve ter até 1 MB.")
        from PIL import Image, UnidentifiedImageError
        try:
            imagem = Image.open(arquivo)
            if imagem.format not in {"PNG", "JPEG"} or imagem.width > 2048 or imagem.height > 2048:
                raise ValueError()
            imagem.verify()
            arquivo.seek(0)
            imagem = Image.open(arquivo).convert("RGBA")
            saida = BytesIO()
            imagem.save(saida, format="PNG")
            return saida.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise forms.ValidationError("Envie uma imagem PNG ou JPEG válida de até 2048 pixels por lado.")


class RecuperarForm(forms.Form):
    username = forms.CharField(label="Identificador de acesso", max_length=150)


class SalvarSenha:
    def save(self, commit=True):
        self.user.set_password(self.cleaned_data["new_password1"])
        if commit:
            self.user.save(update_fields=["password"])
        return self.user


class NovaSenhaForm(SalvarSenha, SetPasswordForm):
    comprovante = forms.CharField(widget=forms.HiddenInput)


class AlterarSenhaForm(SalvarSenha, PasswordChangeForm):
    pass
