import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac


def documento(valor, tipo):
    valor = valor.strip()
    if not valor:
        return ''
    if re.search(r'[^\d.\-\s]', valor):
        raise ValidationError('Informe somente os números do documento.')
    numeros = re.sub(r'\D', '', valor)
    if len(numeros) != 11 or len(set(numeros)) == 1:
        raise ValidationError('Confira os 11 dígitos do documento.')
    if tipo == 'cpf':
        for tamanho in (9, 10):
            soma = sum(int(numero) * peso for numero, peso in zip(numeros[:tamanho], range(tamanho + 1, 1, -1)))
            digito = (soma * 10 % 11) % 10
            if digito != int(numeros[tamanho]):
                raise ValidationError('CPF com dígitos verificadores inválidos.')
    else:
        soma = sum(int(numero) * peso for numero, peso in zip(numeros[:10], [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
        resto = 11 - soma % 11
        if (0 if resto >= 10 else resto) != int(numeros[10]):
            raise ValidationError('NIS com dígito verificador inválido.')
    return numeros


def indice(municipio_id, tipo, numero):
    return salted_hmac('cadastros.documento.v1', f'{municipio_id}:{tipo}:{numero}', secret=getattr(settings, "SOCIAL_CHAVE_INDICE", settings.SECRET_KEY), algorithm='sha256').hexdigest()
