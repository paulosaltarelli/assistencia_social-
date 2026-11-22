import json
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Sum

from .models import Compromisso, Conciliacao, Despesa, Historico, Lancamento, Receita, RevisaoOrcamento

ZERO = Decimal("0")


def travar(chave):
    # Um escritor por dotação, incluindo revisões e etapas de despesas diferentes.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"financeiro/{chave}"])


def verificar_municipio(objeto, municipio):
    if objeto.municipio_id != municipio.pk:
        raise ValidationError("O registro está indisponível neste município.")
    for campo in objeto._meta.fields:
        if not campo.is_relation or campo.name in {"municipio", "responsavel"}:
            continue
        if getattr(objeto, campo.attname) is None:
            continue
        relacionado = getattr(objeto, campo.name)
        if relacionado.municipio_id != municipio.pk:
            raise ValidationError("Selecione registros do município em atendimento.")


def registrar_historico(objeto, usuario, evento):
    estado = {campo.name: campo.value_from_object(objeto) for campo in objeto._meta.fields}
    Historico.objects.create(municipio=objeto.municipio, responsavel=usuario, objeto=objeto.pk,
                             entidade=objeto._meta.model_name, evento=evento,
                             estado=json.loads(json.dumps(estado, cls=DjangoJSONEncoder)))


def validar_data_exercicio(data, dotacao):
    if data.year != dotacao.exercicio.ano:
        raise ValidationError("A data deve pertencer ao exercício da dotação.")


def verificar_saldo_em_todas_as_datas(dotacao, data, debito):
    variacoes = defaultdict(lambda: ZERO)
    variacoes[data] -= debito
    revisoes = RevisaoOrcamento.objects.filter(dotacao=dotacao).order_by().values("data", "tipo").annotate(total=Sum("valor"))
    for item in revisoes:
        variacoes[item["data"]] += item["total"] if item["tipo"] == "credito" else -item["total"]
    empenhos = Lancamento.objects.filter(despesa__dotacao=dotacao, tipo="empenho").order_by().values("data").annotate(total=Sum("valor"))
    for item in empenhos:
        variacoes[item["data"]] -= item["total"]
    saldo = dotacao.valor_inicial
    for dia in sorted(variacoes):
        saldo += variacoes[dia]
        if saldo < 0:
            raise ValidationError(f"A dotação ficaria sem saldo orçamentário em {dia:%d/%m/%Y}.")


@transaction.atomic
def cadastrar(objeto, municipio, usuario):
    if isinstance(objeto, Lancamento):
        return executar_etapa(objeto, municipio, usuario)
    objeto.municipio = municipio
    objeto.responsavel = usuario
    verificar_municipio(objeto, municipio)
    if hasattr(objeto, "dotacao_id"):
        validar_data_exercicio(objeto.data, objeto.dotacao)
        if isinstance(objeto, RevisaoOrcamento):
            travar(objeto.dotacao_id)
            if objeto.tipo == "anulacao":
                verificar_saldo_em_todas_as_datas(objeto.dotacao, objeto.data, objeto.valor)
    if isinstance(objeto, Receita) and objeto.tipo == "recebida" and not objeto.comprovante.strip():
        raise ValidationError("Informe a referência do comprovante de recebimento.")
    if isinstance(objeto, Compromisso) and (objeto.situacao in {"cancelado", "empenhado"} or objeto.finalizado_em):
        raise ValidationError("O compromisso deve iniciar em uma situação aberta.")
    if isinstance(objeto, Conciliacao) and objeto.data < objeto.despesa.data:
        raise ValidationError("A conferência deve ocorrer a partir da data da despesa.")
    objeto.full_clean()
    objeto.save(force_insert=True)
    registrar_historico(objeto, usuario, "Cadastro")
    return objeto


@transaction.atomic
def atualizar_despesa(despesa, valores, usuario, versao):
    travar(despesa.dotacao_id)
    atual = Despesa.objects.get(pk=despesa.pk, municipio=despesa.municipio)
    if atual.versao != versao:
        raise ValidationError("A despesa foi atualizada. Reabra a ficha antes de editar.")
    if atual.lancamentos.exists():
        if any(valores.get(c) != getattr(atual, c) for c in ("valor", "fornecedor", "cnpj", "data", "documento", "processo")):
            raise ValidationError("Preserve valor, identificação, fornecedor e data da despesa que já possui execução.")
    for nome in ("descricao", "categoria", "valor", "fornecedor", "cnpj", "data", "documento", "processo", "observacoes"):
        setattr(atual, nome, valores[nome])
    validar_data_exercicio(atual.data, atual.dotacao)
    atual.versao += 1
    atual.full_clean()
    atual.save()
    registrar_historico(atual, usuario, "Revisão da despesa")
    return atual


@transaction.atomic
def alterar_compromisso(compromisso, situacao, data, usuario):
    travar(compromisso.dotacao_id)
    atual = Compromisso.objects.get(pk=compromisso.pk, municipio=compromisso.municipio)
    if atual.situacao in {"cancelado", "empenhado"} or situacao not in {"previsto", "reservado", "contratacao", "cancelado"}:
        raise ValidationError("O compromisso não aceita esta alteração.")
    validar_data_exercicio(data, atual.dotacao)
    if data < atual.data:
        raise ValidationError("Informe uma data a partir da criação do compromisso.")
    atual.situacao = situacao
    if situacao == "cancelado":
        atual.finalizado_em = data
    atual.save(update_fields=["situacao", "finalizado_em"])
    registrar_historico(atual, usuario, f"Situação: {atual.get_situacao_display()}")


@transaction.atomic
def executar_etapa(etapa, municipio, usuario):
    etapa.municipio = municipio
    etapa.responsavel = usuario
    verificar_municipio(etapa, municipio)
    travar(etapa.despesa.dotacao_id)
    despesa = Despesa.objects.select_related("dotacao__exercicio").get(pk=etapa.despesa_id, municipio=municipio)
    etapa.despesa = despesa
    if etapa.valor <= 0:
        raise ValidationError("Informe um valor positivo.")
    validar_data_exercicio(etapa.data, despesa.dotacao)
    if etapa.data < despesa.data:
        raise ValidationError("A etapa deve ocorrer a partir da data da despesa.")
    if etapa.tipo == "empenho":
        if etapa.anterior_id:
            raise ValidationError("Empenho inicia a execução da despesa.")
        empenhado = despesa.lancamentos.filter(tipo="empenho").aggregate(v=Sum("valor", default=ZERO))["v"]
        if etapa.valor > despesa.valor - empenhado:
            raise ValidationError("O valor excede o saldo da despesa para empenho.")
        verificar_saldo_em_todas_as_datas(despesa.dotacao, etapa.data, etapa.valor)
        if etapa.compromisso_id:
            compromisso = Compromisso.objects.get(pk=etapa.compromisso_id, municipio=municipio)
            if (compromisso.situacao in {"cancelado", "empenhado"} or compromisso.dotacao_id != despesa.dotacao_id
                    or compromisso.valor != etapa.valor or compromisso.data > etapa.data):
                raise ValidationError("A conversão exige compromisso aberto da mesma dotação, data válida e valor integral.")
            compromisso.situacao = "empenhado"
            compromisso.finalizado_em = etapa.data
            compromisso.save(update_fields=["situacao", "finalizado_em"])
            registrar_historico(compromisso, usuario, "Convertido em empenho")
    else:
        origem_exigida = {"liquidacao": "empenho", "pagamento": "liquidacao"}.get(etapa.tipo)
        if not origem_exigida or not etapa.anterior_id or etapa.compromisso_id:
            raise ValidationError("Selecione a etapa de origem correspondente.")
        origem = etapa.anterior
        if origem.despesa_id != despesa.pk or origem.tipo != origem_exigida or etapa.data < origem.data:
            raise ValidationError("A origem deve pertencer a esta despesa e preceder a nova etapa.")
        aplicado = origem.derivados.aggregate(v=Sum("valor", default=ZERO))["v"]
        if etapa.valor > origem.valor - aplicado:
            raise ValidationError("O valor excede o saldo disponível da etapa anterior.")
    etapa.full_clean()
    etapa.save(force_insert=True)
    registrar_historico(etapa, usuario, etapa.get_tipo_display())
    return etapa
