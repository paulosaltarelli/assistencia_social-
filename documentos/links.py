from urllib.parse import urlencode
from django.core import signing
from django.urls import reverse


DURACAO_SEGUNDOS = 600
SAL = "documentos.versao.link.v1"


def escopo(request, pk, modo):
    return [str(pk), modo, str(request.user.pk), str(request.municipio.pk)]


def link_original(request, pk, modo):
    token = signing.dumps(escopo(request, pk, modo), salt=SAL)
    return reverse("documentos:arquivo", args=[pk, modo]) + "?" + urlencode({"acesso": token})


def link_valido(request, pk, modo):
    try:
        dados = signing.loads(request.GET.get("acesso", ""), salt=SAL, max_age=DURACAO_SEGUNDOS)
    except signing.BadSignature:
        return False
    return dados == escopo(request, pk, modo)
