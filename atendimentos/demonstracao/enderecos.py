"""Atualiza exclusivamente os endereços gerados pela versão identificada da carga piloto."""
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from atendimentos.models import Auditoria
from cadastros.localidades import CIDADE, cidade_do_catalogo, distribuir_enderecos, pares_e_bairros
from cadastros.models import AtualizacaoCadastro, ComplementoFamilia
from programas.models import TipoBeneficio


SETORES_ANTIGOS = ('Azul', 'Verde', 'Amarelo', 'Laranja', 'Violeta', 'Branco')
# Assinaturas literais da normalização histórica, usadas apenas para reconhecer a origem.
PARES_ANTIGOS = (
    ('Rua das Acácias', 'Centro'), ('Rua do Cedro', 'Jardim das Flores'),
    ('Rua das Hortênsias', 'Vila Nova'), ('Rua dos Ipês', 'Alto da Serra'),
    ('Rua do Bosque', 'Boa Vista'), ('Rua das Palmeiras', 'Primavera'),
)


@transaction.atomic
def atualizar_enderecos(contexto, conferir=False):
    from .carga import VERSAO
    if not contexto.homologacao or not settings.SOCIAL_HOMOLOGACAO or not cidade_do_catalogo(contexto.municipio):
        raise ValidationError('A atualização de endereços é exclusiva da demonstração de Santa Cruz de Minas.')
    marcador = TipoBeneficio.objects.filter(municipio=contexto.municipio, pk=contexto.identificador('metadados/periodo')).first()
    if not marcador or json.loads(marcador.regra_local).get('versao') != VERSAO:
        raise ValidationError('O marcador original da demonstração não foi localizado neste município.')
    pares, _ = pares_e_bairros(contexto.municipio)
    enderecos = distribuir_enderecos(pares)
    confirmados = {(p['logradouro'], p['bairro']) for p in enderecos}
    contagens = {'pares_disponiveis': len(pares), 'verificadas': 0, 'manuais_preservadas': 0,
                 'ja_atualizadas': 0, 'legadas': 0, 'atualizadas': 0}
    municipal = ComplementoFamilia.objects.filter(municipio=contexto.municipio)
    manual = AtualizacaoCadastro.objects.filter(municipio=contexto.municipio, objeto=OuterRef('familia_id')).exclude(acao='endereco_demonstracao')
    for numero in range(1, 81):
        familia_id = contexto.identificador(f'atendimentos.familia/familia/{numero}')
        complemento_id = contexto.identificador(f'cadastros.complementofamilia/familia/dados/{numero}')
        qs = municipal.filter(pk=complemento_id, familia_id=familia_id, familia__municipio=contexto.municipio)
        atual = qs.annotate(editada=Exists(manual)).values('endereco', 'bairro', 'cidade', 'numero', 'editada').first()
        if not atual:
            continue
        contagens['verificadas'] += 1
        if atual['editada']:
            contagens['manuais_preservadas'] += 1
            continue
        par_atual = atual['endereco'], atual['bairro']
        if par_atual in confirmados:
            contagens['ja_atualizadas'] += 1
            continue
        originais = {(f'[SIMULADO] Rua do cenário {numero:03d}', f'[SIMULADO] Setor {SETORES_ANTIGOS[numero % 6]}'),
                     PARES_ANTIGOS[numero % 6]}
        if par_atual not in originais:
            contagens['manuais_preservadas'] += 1
            continue
        if atual['cidade'] not in {CIDADE, CIDADE + ' — cenário simulado'} or atual['numero'] != str(numero):
            contagens['manuais_preservadas'] += 1
            continue
        contagens['legadas'] += 1
        if conferir or not enderecos:
            continue
        destino = enderecos[(numero - 1) % len(enderecos)]
        alteradas = qs.filter(~Exists(manual), endereco=atual['endereco'], bairro=atual['bairro'],
                              numero=atual['numero'], cidade=atual['cidade']).exclude(
            endereco=destino['logradouro'], bairro=destino['bairro'], cidade=CIDADE).update(
            endereco=destino['logradouro'], bairro=destino['bairro'], cidade=CIDADE, atualizado=timezone.now())
        if alteradas:
            AtualizacaoCadastro.objects.create(municipio=contexto.municipio, autor=contexto.user, objeto=familia_id,
                acao='endereco_demonstracao', campos='logradouro, bairro, cidade')
            Auditoria.objects.create(municipio=contexto.municipio, usuario=contexto.user, objeto=familia_id, evento='endereco_demonstracao')
            contagens['atualizadas'] += 1
    return contagens
