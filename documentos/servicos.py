from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.urls import reverse

from atendimentos.acesso import registrar_evento, tem_permissao
from .models import Categoria, Conferencia, Documento, Estado, Versao


ORIGENS = {
    "despesa": ("financeiro.Despesa", "financeiro", "Despesa", "financeiro:despesa"),
    "receita": ("financeiro.Receita", "financeiro", "Receita", "financeiro:receita"),
    "beneficio": ("programas.SolicitacaoBeneficio", "beneficios", "Benefício eventual", "programas:beneficio_detalhe"),
    "material": ("programas.PedidoMaterial", "materiais", "Pedido de material", "programas:pedido_detalhe"),
    "vale": ("programas.ConcessaoVale", "vale", "Vale-Alimentação", "programas:vale_detalhe"),
}
METADADOS = ("observacao", "vencimento", "numero_nota", "serie_nota", "chave_nfe", "data_emissao",
             "cnpj_emissor", "razao_social", "valor_nota", "descricao_itens", "processo_referencia",
             "empenho_referencia")


def origens_visiveis(vinculo):
    return [alvo for alvo, (_, area, _, _) in ORIGENS.items() if tem_permissao(vinculo, f"{area}.ver")]


def documentos_autorizados(request):
    filtro = Q(pk__in=[])
    for campo in origens_visiveis(request.vinculo):
        filtro |= Q(**{f"{campo}__isnull": False})
    docs = Documento.objects.filter(filtro, municipio=request.municipio)
    if not tem_permissao(request.vinculo, "sigilo.ver"):
        docs = docs.filter(sigilo_tecnico=False)
    return docs


def acesso_origem(request, alvo, pk, escrita=False):
    from django.http import Http404
    if alvo not in ORIGENS:
        raise Http404()
    modelo, area, _, _ = ORIGENS[alvo]
    if not tem_permissao(request.vinculo, f"{area}.ver"):
        raise PermissionDenied
    if escrita and not tem_permissao(request.vinculo, f"{area}.editar"):
        raise PermissionDenied
    return get_object_or_404(apps.get_model(modelo), pk=pk, municipio=request.municipio)


def pode_alterar(request, alvo):
    area = ORIGENS[alvo][1]
    return all(tem_permissao(request.vinculo, p) for p in ("documentos.ver", "documentos.editar", f"{area}.ver", f"{area}.editar"))


def pode_prestar_contas(vinculo):
    return vinculo.perfil == "gestor" and tem_permissao(vinculo, "gestao.ver") and tem_permissao(vinculo, "financeiro.ver")


def todas_versoes(docs):
    ultima_conferencia = Conferencia.objects.filter(versao_id=OuterRef("pk")).order_by("-criado_em", "-pk")
    return Versao.objects.filter(documento__in=docs).defer("conteudo").annotate(
        estado_atual=Coalesce(Subquery(ultima_conferencia.values("situacao")[:1]), Value(Estado.ANEXADO.value))
    ).select_related("documento", "responsavel")


def versoes_atuais(docs):
    posterior = Versao.objects.filter(documento_id=OuterRef("documento_id"), sequencia__gt=OuterRef("sequencia"))
    return todas_versoes(docs).filter(~Exists(posterior)).order_by("-criado_em", "-pk")


def pendencias(docs):
    return versoes_atuais(docs).filter(estado_atual__in=[
        Estado.ANEXADO, Estado.AGUARDANDO, Estado.PENDENCIA, Estado.REJEITADO,
    ])


def metricas_despesas(despesas, docs=None):
    if docs is None:
        docs = Documento.objects.filter(sigilo_tecnico=False)
    docs = docs.filter(despesa__in=despesas)
    return {
        "notas": docs.filter(categoria=Categoria.NOTA).count(),
        "documentos_pendentes": pendencias(docs).count(),
        "despesas_sem_documentos": despesas.filter(~Exists(docs.filter(despesa_id=OuterRef("pk")))).count(),
    }


def eventos_despesa(despesa, docs=None):
    if docs is None:
        docs = Documento.objects.filter(sigilo_tecnico=False)
    docs = docs.filter(municipio_id=despesa.municipio_id, despesa=despesa)
    eventos = []
    for v in Versao.objects.filter(documento__in=docs).defer("conteudo").select_related("responsavel"):
        eventos.append({"data": v.criado_em, "descricao": f"Anexo · versão {v.sequencia} · {v.nome}",
                        "usuario": v.responsavel.get_username(), "url": reverse("documentos:detalhe", args=[v.documento_id])})
    for c in Conferencia.objects.filter(versao__documento__in=docs).select_related("responsavel", "versao").defer("versao__conteudo"):
        eventos.append({"data": c.criado_em, "descricao": f"{c.get_situacao_display()} · {c.versao.nome}",
                        "usuario": c.responsavel.get_username(), "url": reverse("documentos:detalhe", args=[c.versao.documento_id])})
    return sorted(eventos, key=lambda evento: evento["data"])


def trancar(chave):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(chave.bytes[:8], "big", signed=True)])


@transaction.atomic
def guardar_versao(request, alvo, origem, dados, original, documento=None):
    trancar(dados["operacao"])
    previa = Versao.objects.filter(municipio=request.municipio, operacao=dados["operacao"]).select_related("documento").defer("conteudo").first()
    if previa:
        if (previa.responsavel_id == request.user.pk and previa.sha256 == original.sha256
                and previa.nome == original.nome and previa.mime == original.mime
                and getattr(previa.documento, alvo + "_id") == origem.pk
                and previa.documento.categoria == dados["categoria"]
                and previa.sequencia == dados["base"] + 1
                and all(getattr(previa, k) == dados[k] for k in METADADOS)
                and (documento is not None or previa.documento.sigilo_tecnico == dados.get("sigilo_tecnico", False))
                and (documento is None or previa.documento_id == documento.pk)):
            return previa
        raise ValidationError("O envio já foi utilizado. Reabra o formulário.")
    if documento is None:
        documento = Documento.objects.create(municipio=request.municipio, categoria=dados["categoria"], sigilo_tecnico=dados.get("sigilo_tecnico", False), **{alvo: origem})
        sequencia = 1
    else:
        trancar(documento.pk)
        sequencia = Versao.objects.filter(documento=documento).order_by("-sequencia").values_list("sequencia", flat=True).first() + 1
    if dados["base"] != sequencia - 1:
        raise ValidationError("Uma nova versão foi registrada. Volte ao histórico e revise o documento atual.")
    versao = Versao.objects.create(
        municipio=request.municipio, documento=documento, sequencia=sequencia, operacao=dados["operacao"],
        nome=original.nome, mime=original.mime, tamanho=len(original.dados), sha256=original.sha256,
        conteudo=original.dados, responsavel=request.user, **{k: dados[k] for k in METADADOS},
    )
    registrar_evento(request, "doc.anexar" if sequencia == 1 else "doc.versionar", documento.pk)
    return versao


@transaction.atomic
def conferir(request, versao, dados):
    trancar(versao.documento_id)
    if Versao.objects.filter(documento_id=versao.documento_id, sequencia__gt=versao.sequencia).exists():
        raise ValidationError("Existe uma versão mais recente. Reabra a conferência.")
    ultima = Conferencia.objects.filter(versao=versao).order_by("-criado_em", "-pk").first()
    if dados["situacao"] == Estado.REGULARIZADO:
        precedente = ultima or Conferencia.objects.filter(versao__documento_id=versao.documento_id).order_by("-criado_em", "-pk").first()
        if not precedente or precedente.situacao not in (Estado.PENDENCIA, Estado.REJEITADO):
            raise ValidationError("Regularização requer uma pendência ou rejeição anterior neste documento.")

    Conferencia.objects.create(versao=versao, municipio=request.municipio, responsavel=request.user, **dados)
    registrar_evento(request, "doc.conferir", versao.pk)


def duplicidades(versao, documentos):
    if versao.documento.categoria != Categoria.NOTA:
        return Versao.objects.none()
    regra = Q(pk__in=[])
    if versao.chave_nfe:
        regra |= Q(chave_nfe=versao.chave_nfe)
    if versao.cnpj_emissor and versao.numero_nota and versao.valor_nota is not None:
        regra |= Q(cnpj_emissor=versao.cnpj_emissor, numero_nota=versao.numero_nota,
                   serie_nota=versao.serie_nota, valor_nota=versao.valor_nota)
    return versoes_atuais(documentos.filter(categoria=Categoria.NOTA)).filter(regra).exclude(documento_id=versao.documento_id)


def despesas_do_arquivo(municipio, valores):
    from financeiro.models import Despesa
    campos = {"exercicio": "dotacao__exercicio__ano", "fundo": "dotacao__fundo_id",
              "fonte": "dotacao__fonte_id", "programa": "dotacao__programa_id",
              "inicio": "data__gte", "fim": "data__lte"}
    return Despesa.objects.filter(municipio=municipio, **{
        destino: valores[nome] for nome, destino in campos.items() if valores.get(nome)
    })


def documentos_filtrados(municipio, valores):
    return Documento.objects.filter(municipio=municipio, despesa__in=despesas_do_arquivo(municipio, valores))
