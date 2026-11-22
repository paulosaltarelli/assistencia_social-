from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from atendimentos.acesso import tem_permissao
from documentos.models import Categoria, Documento
from documentos.servicos import origens_visiveis, pendencias, versoes_atuais
from financeiro.models import Despesa


def alertas_documentais(municipio, vinculo):
    origens = Q(pk__in=[])
    for nome in origens_visiveis(vinculo):
        origens |= Q(**{f'{nome}__isnull': False})
    documentos = Documento.objects.filter(origens, municipio=municipio)
    if not tem_permissao(vinculo, 'sigilo.ver'):
        documentos = documentos.filter(sigilo_tecnico=False)
    versoes = versoes_atuais(documentos)
    hoje = timezone.localdate()
    itens = [
        ('Documentos aguardando conferência ou regularização', pendencias(documentos).count(), 'documentos:inicio'),
        ('Documentos vencidos', versoes.filter(vencimento__lt=hoje).count(), 'documentos:inicio'),
        ('Documentos a vencer em 7 dias', versoes.filter(vencimento__range=(hoje, hoje + timedelta(days=7))).count(), 'documentos:inicio'),
        ('Notas fiscais aguardando conferência', pendencias(documentos.filter(categoria=Categoria.NOTA)).count(), 'documentos:inicio'),
    ]
    if tem_permissao(vinculo, 'financeiro.ver'):
        despesas = Despesa.objects.filter(municipio=municipio)
        sem_documentos = despesas.filter(~Exists(Documento.objects.filter(municipio=municipio, despesa_id=OuterRef('pk'))))
        itens.append(('Despesas sem documentos anexados', sem_documentos.count(), 'financeiro:inicio'))
    return itens
