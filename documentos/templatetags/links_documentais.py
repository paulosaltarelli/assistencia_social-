from django import template
from documentos.links import link_original

register = template.Library()


@register.simple_tag(takes_context=True)
def acesso_original(context, pk, modo):
    return link_original(context["request"], pk, modo)
