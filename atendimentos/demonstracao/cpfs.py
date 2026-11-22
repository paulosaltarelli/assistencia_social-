"""Identificadores sintéticos exclusivos do cenário de homologação.

O cálculo verifica somente os dígitos. Não existe faixa oficial de CPF reservada
para testes. Estes números não comprovam identidade e nunca são consultados em
serviço externo. A persistência utiliza apenas o índice e os últimos dígitos.
"""
import json
from collections import Counter
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cadastros.identificacao import documento, indice
from cadastros.models import AtualizacaoCadastro, ComplementoPessoa
from programas.models import TipoBeneficio


@lru_cache(maxsize=1)
def raizes_permutadas():
    # O multiplicador é coprimo a 10**9. A transformação é bijetiva antes da
    # exclusão das dez raízes uniformes, sem uma faixa supostamente reservada.
    raizes = []
    passo = 0
    while len(raizes) < 280:
        passo += 1
        raiz = f"{(381966011 * passo + 123456789) % 1000000000:09d}"
        if len(set(raiz)) > 1:
            raizes.append(raiz)
    return tuple(raizes)


def cpf_sintetico(ordem):
    if isinstance(ordem, bool) or not isinstance(ordem, int) or not 1 <= ordem <= 280:
        raise ValueError("Ordem do cenário fora do intervalo permitido.")
    numeros = raizes_permutadas()[ordem - 1]
    for tamanho in (9, 10):
        soma = sum(int(numero) * peso for numero, peso in zip(numeros, range(tamanho + 1, 1, -1)))
        numeros += str((soma * 10 % 11) % 10)
    return documento(numeros, "cpf")


def cpf_do_cenario(familia, posicao):
    if (isinstance(familia, bool) or isinstance(posicao, bool) or not isinstance(familia, int)
            or not isinstance(posicao, int) or not 1 <= familia <= 80 or not 0 <= posicao < 2 + familia % 4):
        raise ValueError("Pessoa fora da definição do cenário.")
    ordem = sum(2 + numero % 4 for numero in range(1, familia)) + posicao + 1
    return cpf_sintetico(ordem)


def preparar_cpfs(contexto):
    if contexto.homologacao is not True or getattr(settings, "SOCIAL_HOMOLOGACAO", False) is not True:
        raise ValidationError("Os CPFs sintéticos exigem ambiente de homologação confirmado.")
    esperados = {}
    for numero in range(1, 81):
        familia_id = contexto.identificador(f"atendimentos.familia/familia/{numero}")
        for posicao in range(2 + numero % 4):
            cpf = cpf_do_cenario(numero, posicao)
            pk = contexto.identificador(f"cadastros.complementopessoa/pessoa/dados/{numero}/{posicao}")
            esperados[pk] = {"pessoa_id": contexto.identificador(f"atendimentos.cidadao/pessoa/{numero}/{posicao}"),
                "familia_id": familia_id, "cpf_hash": indice(contexto.municipio.pk, "cpf", cpf), "cpf_ultimos": cpf[-4:]}
    contexto.cpfs_esperados = esperados
    contexto.hashes_cpf_ocupados = dict(ComplementoPessoa.objects.filter(
        municipio=contexto.municipio, cpf_hash__in=[registro["cpf_hash"] for registro in esperados.values()],
    ).values_list("cpf_hash", "pk"))


def campos_cpf(contexto, numero, posicao):
    if not hasattr(contexto, "cpfs_esperados"):
        preparar_cpfs(contexto)
    pk = contexto.identificador(f"cadastros.complementopessoa/pessoa/dados/{numero}/{posicao}")
    dados = contexto.cpfs_esperados[pk]
    dono = contexto.hashes_cpf_ocupados.get(dados["cpf_hash"])
    if dono is not None and dono != pk:
        contexto.contar("cpfs_colisoes_preservadas")
        return {"cpf_hash": "", "cpf_ultimos": ""}
    return {"cpf_hash": dados["cpf_hash"], "cpf_ultimos": dados["cpf_ultimos"]}


def complementar_cpfs(contexto, aplicar=False):
    from .carga import VERSAO

    marcador = TipoBeneficio.objects.filter(pk=contexto.identificador("metadados/periodo"), municipio=contexto.municipio).first()
    try:
        if not marcador or json.loads(marcador.regra_local).get("versao") != VERSAO:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError("A carga de demonstração esperada não foi identificada neste município.") from exc
    preparar_cpfs(contexto)
    consulta = ComplementoPessoa.objects.select_related("cidadao").filter(
        pk__in=contexto.cpfs_esperados, municipio=contexto.municipio,
    )
    if aplicar:
        consulta = consulta.select_for_update(of=("self",))
    registros = {registro.pk: registro for registro in consulta}
    contagens = Counter()
    for pk, esperado in contexto.cpfs_esperados.items():
        registro = registros.get(pk)
        if (not registro or registro.cidadao_id != esperado["pessoa_id"]
                or registro.cidadao.municipio_id != contexto.municipio.pk or registro.cidadao.familia_id != esperado["familia_id"]):
            contagens["fora_ou_ausentes"] += 1
            continue
        resumo, ultimos = esperado["cpf_hash"], esperado["cpf_ultimos"]
        if registro.cpf_hash == resumo and registro.cpf_ultimos == ultimos:
            contagens["ja_preenchidos"] += 1
            continue
        if registro.cpf_hash or registro.cpf_ultimos:
            contagens["manuais_preservados"] += 1
            continue
        dono = contexto.hashes_cpf_ocupados.get(resumo)
        if dono is not None and dono != registro.pk:
            contagens["colisoes_preservadas"] += 1
            continue
        contagens["elegiveis"] += 1
        if not aplicar:
            continue
        try:
            with transaction.atomic():
                atualizados = ComplementoPessoa.objects.filter(
                    pk=registro.pk, municipio=contexto.municipio, cpf_hash="", cpf_ultimos="",
                ).update(cpf_hash=resumo, cpf_ultimos=ultimos)
                if atualizados:
                    AtualizacaoCadastro.objects.create(municipio=contexto.municipio, objeto=registro.cidadao_id,
                        autor=contexto.user, acao="cpf_simulado", campos="cpf_hash,cpf_ultimos")
                    contagens["preenchidos"] += 1
        except IntegrityError as exc:
            # O índice único também protege contra uma edição manual concorrente.
            causa = exc.__cause__
            if getattr(getattr(causa, "diag", None), "constraint_name", None) != "cadastros_cpf_unico_municipal":
                raise
            contagens["colisoes_concorrentes"] += 1
    return {"modo": "aplicacao" if aplicar else "simulacao", "contagens": dict(contagens)}
