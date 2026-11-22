from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def reais(valor):
    # Formatação independente da localidade do processo de aplicação.
    rotulo = f"{Decimal(valor or 0):,.2f}"
    return "R$ " + rotulo.translate(str.maketrans(",.", ".,"))


@register.simple_tag(takes_context=True)
def pagina_url(context, numero, parametro="pagina"):
    query = context["request"].GET.copy()
    query[parametro or "pagina"] = numero
    return "?" + query.urlencode()
