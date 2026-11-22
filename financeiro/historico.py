from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Case, CharField, F, IntegerField, JSONField, Q, UUIDField, Value, When
from django.urls import reverse

from documentos.models import Conferencia, Estado, Versao
from .models import Historico


def eventos(queryset, categoria, texto, *, documento=None, numero=None, situacao=None, estado=None):
    # Todas as origens têm a mesma projeção para a paginação conjunta no PostgreSQL.
    return queryset.order_by().values(
        instante=F('criado_em'), chave=F('pk'), origem=Value(categoria), legenda=F(texto),
        usuario=F(f'responsavel__{get_user_model().USERNAME_FIELD}'),
        documento_uuid=F(documento) if documento else Value(None, output_field=UUIDField()),
        numero_versao=F(numero) if numero else Value(None, output_field=IntegerField()),
        conferencia=F(situacao) if situacao else Value(None, output_field=CharField()),
        dados=estado if estado is not None else Value(None, output_field=JSONField()),
    )


def linha_do_tempo(despesa, documentos, numero_pagina):
    objetos = Q(objeto=despesa.pk) | Q(objeto__in=despesa.lancamentos.values('pk'))
    objetos |= Q(objeto__in=despesa.conciliacoes.values('pk')) | Q(objeto__in=despesa.origens_sociais.values('pk'))
    registros = Historico.objects.filter(objetos, municipio_id=despesa.municipio_id)
    estado = Case(When(entidade='despesa', then=F('estado')), output_field=JSONField())
    consulta = eventos(registros, 'financeiro', 'evento', estado=estado)
    if documentos is not None:
        autorizados = documentos.filter(municipio_id=despesa.municipio_id, despesa=despesa)
        versoes = Versao.objects.filter(municipio_id=despesa.municipio_id, documento__in=autorizados)
        conferencias = Conferencia.objects.filter(municipio_id=despesa.municipio_id, versao__documento__in=autorizados)
        consulta = consulta.union(
            eventos(versoes, 'versao', 'nome', documento='documento_id', numero='sequencia'),
            eventos(conferencias, 'conferencia', 'versao__nome', documento='versao__documento_id', situacao='situacao'),
            all=True,
        )
    pagina = Paginator(consulta.order_by('-instante', 'origem', '-chave'), 30).get_page(numero_pagina)
    rotulos = dict(Estado.choices)
    linhas = []
    for item in pagina.object_list:
        descricao = item['legenda']
        if item['origem'] == 'versao':
            descricao = f"Anexo · versão {item['numero_versao']} · {descricao}"
        elif item['origem'] == 'conferencia':
            descricao = f"{rotulos.get(item['conferencia'], item['conferencia'])} · {descricao}"
        linhas.append({'data': item['instante'], 'descricao': descricao, 'usuario': item['usuario'],
                       'estado': item['dados'], 'url': reverse('documentos:detalhe', args=[item['documento_uuid']]) if item['documento_uuid'] else None})
    pagina.object_list = linhas
    return pagina
