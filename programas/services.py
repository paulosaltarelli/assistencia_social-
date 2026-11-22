from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ConcessaoVale, HistoricoBeneficio, HistoricoPedido, HistoricoVale,
    Material, MovimentoEstoque, PedidoMaterial, SolicitacaoBeneficio,
)


def historico(objeto, autor, anterior, motivo, dados=None):
    modelos = {
        SolicitacaoBeneficio: (HistoricoBeneficio, "solicitacao"),
        PedidoMaterial: (HistoricoPedido, "pedido"),
        ConcessaoVale: (HistoricoVale, "concessao"),
    }
    modelo, campo = modelos[type(objeto)]
    registro = modelo(municipio_id=objeto.municipio_id, autor=autor, anterior=anterior,
                      situacao=objeto.situacao, motivo=motivo, dados=dados or {}, **{campo: objeto})
    registro.full_clean()
    registro.save()


def motivo_obrigatorio(motivo):
    if not motivo or not motivo.strip():
        raise ValidationError("Informe a fundamentação desta operação.")


@transaction.atomic
def solicitar_beneficio(objeto, autor):
    tipo = objeto.tipo
    if not tipo.ativo or objeto.solicitado_em < tipo.vigencia_inicio or (
        tipo.vigencia_fim and objeto.solicitado_em > tipo.vigencia_fim
    ):
        raise ValidationError("O tipo de benefício não está disponível na data da solicitação.")
    objeto.responsavel = autor
    objeto.regra_aplicada = {
        "tipo_id": str(tipo.pk), "nome": tipo.nome, "regra_local": tipo.regra_local,
        "vigencia_inicio": tipo.vigencia_inicio.isoformat(),
        "vigencia_fim": tipo.vigencia_fim.isoformat() if tipo.vigencia_fim else None,
    }
    objeto.full_clean()
    objeto.save()
    historico(objeto, autor, "", "Solicitação registrada.")
    return objeto


def validar_aprovacao(objeto, situacao, quantidade, valor=None):
    if quantidade <= 0 or quantidade > objeto.quantidade_solicitada:
        raise ValidationError("A quantidade aprovada deve ser positiva e não exceder a solicitação.")
    parcial = quantidade < objeto.quantidade_solicitada
    if valor is not None:
        if valor < 0 or valor > objeto.valor_solicitado:
            raise ValidationError("O valor aprovado não pode exceder o solicitado ou ser negativo.")
        if objeto.valor_solicitado > 0 and valor == 0:
            raise ValidationError("Informe um valor aprovado positivo para esta solicitação.")
        parcial = parcial or valor < objeto.valor_solicitado
    if (situacao == "parcial") != parcial:
        raise ValidationError("Use aprovação parcial quando quantidade ou valor for inferior ao solicitado.")


@transaction.atomic
def decidir_beneficio(pk, municipio, autor, situacao, motivo, quantidade=Decimal("0"), valor=Decimal("0")):
    objeto = SolicitacaoBeneficio.objects.select_for_update().get(pk=pk, municipio=municipio)
    motivo_obrigatorio(motivo)
    permitidas = {
        "solicitado": {"analise", "cancelado"},
        "analise": {"aprovado", "parcial", "indeferido", "cancelado"},
        "aprovado": {"entregue", "cancelado"}, "parcial": {"entregue", "cancelado"},
    }
    if situacao not in permitidas.get(objeto.situacao, set()):
        raise ValidationError("Transição indisponível para a situação atual. Atualize a página.")
    anterior = objeto.situacao
    agora = timezone.now()
    if situacao == "analise" and not objeto.analisado_em:
        objeto.analisado_em = agora
    if situacao in {"aprovado", "parcial"}:
        validar_aprovacao(objeto, situacao, quantidade, valor)
        objeto.quantidade_aprovada, objeto.valor_aprovado = quantidade, valor
        objeto.concedido_em = agora
    if situacao == "entregue":
        objeto.entregue_em = agora
    objeto.situacao = situacao
    objeto.full_clean()
    objeto.save()
    historico(objeto, autor, anterior, motivo, {
        "quantidade_aprovada": str(objeto.quantidade_aprovada), "valor_aprovado": str(objeto.valor_aprovado),
    })
    return objeto


@transaction.atomic
def decidir_pedido(pk, municipio, autor, situacao, motivo, quantidade=Decimal("0")):
    pedido = PedidoMaterial.objects.select_for_update().get(pk=pk, municipio=municipio)
    motivo_obrigatorio(motivo)
    permitidas = {
        "solicitado": {"analise", "cancelado"},
        "analise": {"aprovado", "parcial", "indeferido", "disponibilidade", "cancelado"},
        "disponibilidade": {"analise", "aprovado", "parcial", "cancelado"},
        "aprovado": {"disponibilidade", "cancelado"}, "parcial": {"disponibilidade", "cancelado"},
    }
    if situacao not in permitidas.get(pedido.situacao, set()):
        raise ValidationError("Transição indisponível para a situação atual. Atualize a página.")
    if pedido.entregue > 0 and situacao == "cancelado":
        raise ValidationError("Pedido com entrega registrada exige reconciliação antes de cancelamento.")
    if situacao in {"aprovado", "parcial"}:
        validar_aprovacao(pedido, situacao, quantidade)
        if quantidade < pedido.entregue:
            raise ValidationError("A aprovação não pode ser inferior ao já entregue.")
        pedido.quantidade_aprovada = quantidade
    anterior = pedido.situacao
    pedido.situacao = situacao
    pedido.full_clean()
    pedido.save()
    historico(pedido, autor, anterior, motivo, {"quantidade_aprovada": str(pedido.quantidade_aprovada)})
    return pedido


@transaction.atomic
def movimentar_estoque(municipio, autor, material_id, quantidade, comprovante,
                       tipo="entrada", custo_unitario=Decimal("0"), pedido_id=None, chave=None):
    motivo_obrigatorio(comprovante)
    if quantidade <= 0 or custo_unitario < 0 or tipo not in {"entrada", "saida"}:
        raise ValidationError("Informe quantidade positiva, custo válido e tipo de movimento.")
    pedido = None
    # Todas as entregas bloqueiam primeiro o pedido e depois o material.
    if pedido_id:
        pedido = PedidoMaterial.objects.select_for_update().get(pk=pedido_id, municipio=municipio)
        existente = MovimentoEstoque.objects.filter(pk=chave, municipio=municipio).first() if chave else None
        if existente:
            if existente.pedido_id != pedido.pk or existente.quantidade != quantidade or existente.comprovante != comprovante.strip():
                raise ValidationError("A chave da operação já foi utilizada com outros dados.")
            return existente
        if tipo != "saida" or pedido.material_id != material_id:
            raise ValidationError("O material deve corresponder ao pedido de saída.")
        if pedido.situacao not in {"aprovado", "parcial"}:
            raise ValidationError("O pedido precisa estar aprovado para entrega.")
        if quantidade > pedido.quantidade_aprovada - pedido.entregue:
            raise ValidationError("A entrega excede o saldo aprovado deste pedido.")
    elif tipo == "saida":
        raise ValidationError("Toda saída exige um pedido aprovado e comprovante.")
    material = Material.objects.select_for_update().get(pk=material_id, municipio=municipio)
    if chave:
        existente = MovimentoEstoque.objects.filter(pk=chave, municipio=municipio).first()
        if existente:
            if (existente.material_id != material_id or existente.tipo != tipo or existente.quantidade != quantidade
                    or existente.custo_unitario != custo_unitario or existente.comprovante != comprovante.strip()):
                raise ValidationError("A chave da operação já foi utilizada com outros dados.")
            return existente
    novo_saldo = material.saldo + quantidade if tipo == "entrada" else material.saldo - quantidade
    if novo_saldo < 0:
        raise ValidationError("Estoque insuficiente. Nenhuma movimentação foi registrada.")
    movimento = MovimentoEstoque(municipio=municipio, material=material, pedido=pedido,
        tipo=tipo, quantidade=quantidade, custo_unitario=custo_unitario,
        comprovante=comprovante.strip(), responsavel=autor)
    if chave:
        movimento.pk = chave
    movimento.full_clean()
    movimento.save()
    material.saldo = novo_saldo
    if tipo == "entrada":
        material.custo_unitario = custo_unitario
    material.full_clean()
    material.save(update_fields=["saldo", "custo_unitario"])
    if pedido:
        anterior = pedido.situacao
        pedido.entregue += quantidade
        if pedido.entregue == pedido.quantidade_aprovada:
            pedido.situacao = "entregue"
        pedido.full_clean()
        pedido.save(update_fields=["entregue", "situacao"])
        historico(pedido, autor, anterior, "Entrega registrada.", {
            "movimento": str(movimento.pk), "quantidade": str(quantidade), "comprovante": comprovante,
        })
    return movimento


@transaction.atomic
def alterar_vale(pk, municipio, autor, situacao, valor, periodicidade, motivo):
    concessao = ConcessaoVale.objects.select_for_update().get(pk=pk, municipio=municipio)
    motivo_obrigatorio(motivo)
    permitidas = {
        "analise": {"ativo", "indeferido"}, "ativo": {"ativo", "suspenso", "desligado"},
        "suspenso": {"ativo", "suspenso", "desligado"},
    }
    if situacao not in permitidas.get(concessao.situacao, set()):
        raise ValidationError("Transição indisponível para esta concessão.")
    anterior = concessao.situacao
    antes = {"valor": str(concessao.valor), "periodicidade": concessao.periodicidade}
    concessao.valor, concessao.periodicidade, concessao.situacao = valor, periodicidade, situacao
    if situacao == "ativo" and not concessao.incluido_em:
        concessao.incluido_em = timezone.now()
    concessao.full_clean()
    concessao.save()
    historico(concessao, autor, anterior, motivo, {
        "antes": antes, "depois": {"valor": str(valor), "periodicidade": periodicidade},
    })
    return concessao
