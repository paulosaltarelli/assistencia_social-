from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Prefetch
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from . import servicos
from .arquivos import ScannerIndisponivel, receber
from .exportacao import preparar
from .forms import ConferenciaForm, DocumentoForm, FiltrosForm
from .links import link_valido
from .models import Conferencia, Estado, Versao


def pagina(request, template, contexto, status=200):
    return render(request, f"documentos/{template}.html", contexto, status=status)


@require_GET
@municipal("documentos.ver")
def inicio(request):
    docs = servicos.documentos_autorizados(request)
    itens = servicos.versoes_atuais(docs)
    busca = request.GET.get("q", "").strip()[:100]
    if busca:
        itens = itens.filter(nome__icontains=busca)
    paginador = Paginator(itens, 25)
    registrar_evento(request, "doc.listar")
    return pagina(request, "lista", {
        "pagina": paginador.get_page(request.GET.get("pagina")), "busca": busca,
        "titulo": "Documentos", "arquivo_autorizado": servicos.pode_prestar_contas(request.vinculo),
    })


@require_GET
@municipal("documentos.ver")
def vinculo(request, alvo, pk):
    origem = servicos.acesso_origem(request, alvo, pk)
    docs = servicos.documentos_autorizados(request).filter(**{alvo: origem})
    registrar_evento(request, "doc.consultar_vinculo", pk)
    return pagina(request, "lista", {
        "titulo": "Documentos comprobatórios",
        "pagina": Paginator(servicos.versoes_atuais(docs), 25).get_page(request.GET.get("pagina")),
        "origem": origem, "alvo": alvo, "rotulo": servicos.ORIGENS[alvo][2],
        "voltar": reverse(servicos.ORIGENS[alvo][3], args=[pk]),
        "editar": servicos.pode_alterar(request, alvo),
    })


def formulario_envio(request, alvo, origem, documento=None):
    if (not servicos.pode_alterar(request, alvo)
            or (documento and documento.sigilo_tecnico and not tem_permissao(request.vinculo, "sigilo.editar"))):
        raise PermissionDenied
    inicial = {"base": 0}
    if documento is not None:
        anterior = Versao.objects.filter(documento=documento).defer("conteudo").order_by("-sequencia").first()
        inicial.update({k: getattr(anterior, k) for k in servicos.METADADOS})
        inicial.update(base=anterior.sequencia, categoria=documento.categoria)
    elif alvo == "despesa":
        inicial.update(cnpj_emissor=origem.cnpj, razao_social=origem.fornecedor, processo_referencia=origem.processo)
    form = DocumentoForm(request.POST if request.method == "POST" else None, request.FILES or None,
                         initial=inicial, categoria_fixa=documento.categoria if documento else None,
                         permitir_sigilo=(alvo not in ("despesa", "receita") and tem_permissao(request.vinculo, "sigilo.editar")
                                          and tem_permissao(request.vinculo, "sigilo.ver")))
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            original = receber(form.cleaned_data["arquivo"])
            versao = servicos.guardar_versao(request, alvo, origem, form.cleaned_data, original, documento)
        except ScannerIndisponivel as erro:
            form.add_error("arquivo", erro)
            status = 503
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, f"Versão {versao.sequencia} anexada.")
            return redirect("documentos:detalhe", pk=versao.documento_id)
    return pagina(request, "enviar", {"form": form, "alvo": alvo, "origem": origem, "documento": documento,
                  "rotulo": servicos.ORIGENS[alvo][2], "titulo": "Substituir documento" if documento else "Anexar documento"}, status)


@require_http_methods(["GET", "POST"])
@municipal("documentos.ver", post="documentos.editar")
def anexar(request, alvo, pk):
    origem = servicos.acesso_origem(request, alvo, pk, escrita=True)
    return formulario_envio(request, alvo, origem)


@require_http_methods(["GET", "POST"])
@municipal("documentos.ver", post="documentos.editar")
def substituir(request, pk):
    doc = get_object_or_404(servicos.documentos_autorizados(request), pk=pk)
    origem = servicos.acesso_origem(request, doc.alvo, getattr(doc, doc.alvo + "_id"), escrita=True)
    return formulario_envio(request, doc.alvo, origem, doc)


@require_GET
@municipal("documentos.ver")
def detalhe(request, pk):
    docs = servicos.documentos_autorizados(request)
    doc = get_object_or_404(docs.select_related(
        "despesa__dotacao__fundo", "despesa__dotacao__fonte", "despesa__dotacao__programa",
    ), pk=pk)
    historico = Conferencia.objects.select_related("responsavel").order_by("criado_em", "pk")
    versoes = list(servicos.todas_versoes(docs.filter(pk=pk)).prefetch_related(
        Prefetch("conferencias", queryset=historico)).order_by("-sequencia"))
    atual = versoes[0]
    registrar_evento(request, "doc.abrir", pk)
    return pagina(request, "detalhe", {"documento": doc, "atual": atual, "versoes": versoes,
        "origem_id": getattr(doc, doc.alvo + "_id"), "titulo": "Detalhe do documento",
        "estado": Estado(atual.estado_atual).label, "similares": servicos.duplicidades(atual, docs)[:10],
        "editar": (servicos.pode_alterar(request, doc.alvo)
                   and (not doc.sigilo_tecnico or tem_permissao(request.vinculo, "sigilo.editar"))), "conferencia": ConferenciaForm(),
    })


@require_http_methods(["POST"])
@municipal("documentos.ver", post="documentos.editar")
def conferir(request, pk):
    versao = get_object_or_404(Versao.objects.filter(documento__in=servicos.documentos_autorizados(request)).select_related("documento").defer("conteudo"), pk=pk)
    if (not servicos.pode_alterar(request, versao.documento.alvo)
            or (versao.documento.sigilo_tecnico and not tem_permissao(request.vinculo, "sigilo.editar"))):
        raise PermissionDenied
    form = ConferenciaForm(request.POST)
    if form.is_valid():
        try:
            servicos.conferir(request, versao, form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Conferência registrada.")
            return redirect("documentos:detalhe", pk=versao.documento_id)
    return pagina(request, "conferir", {"form": form, "versao": versao, "titulo": "Conferência de documento"}, 422)


@require_GET
@never_cache
@municipal("documentos.ver")
def arquivo(request, pk, modo):
    if modo not in ("visualizar", "baixar"):
        from django.http import Http404
        raise Http404
    if not link_valido(request, pk, modo):
        return HttpResponse("Link de acesso expirado ou inválido. Reabra a ficha do documento.", status=403)
    v = get_object_or_404(Versao.objects.filter(documento__in=servicos.documentos_autorizados(request)), pk=pk)
    registrar_evento(request, "doc.baixar" if modo == "baixar" else "doc.visualizar", pk)
    mime = "text/plain" if v.mime == "application/xml" and modo == "visualizar" else v.mime
    resposta = FileResponse(BytesIO(bytes(v.conteudo)), filename=v.nome, as_attachment=modo == "baixar", content_type=mime)
    resposta["X-Content-Type-Options"] = "nosniff"
    resposta["Content-Security-Policy"] = "sandbox; default-src 'none'; frame-ancestors 'none'"
    resposta["Referrer-Policy"] = "no-referrer"
    return resposta


@require_http_methods(["GET", "POST"])
@never_cache
@municipal("documentos.ver")
def prestacao(request):
    if not servicos.pode_prestar_contas(request.vinculo):
        raise PermissionDenied
    origem = request.POST if request.method == "POST" else request.GET
    form = FiltrosForm(origem, municipio=request.municipio)
    itens = []
    quantidade = 0
    if form.is_valid():
        despesas = servicos.despesas_do_arquivo(request.municipio, form.cleaned_data)
        docs = servicos.documentos_autorizados(request).filter(despesa__in=despesas)
        if request.method == "POST":
            tipo = request.POST.get("formato")
            if tipo not in ("pdf", "zip"):
                return HttpResponse("Formato inválido.", status=400)
            filtros = []
            for campo in form:
                valor = form.cleaned_data.get(campo.name)
                if valor:
                    opcoes = getattr(campo.field, "choices", ())
                    exibido = next((rotulo for chave, rotulo in opcoes if str(chave) == str(valor)), str(valor))
                    filtros.append(f"{campo.label} = {exibido}")
            try:
                arquivo = preparar(request.municipio, docs, filtros, tipo == "zip", despesas=despesas)
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                registrar_evento(request, "doc.exportar_" + tipo)
                return FileResponse(arquivo, as_attachment=True, filename="prestacao-de-contas." + tipo,
                                    content_type="application/pdf" if tipo == "pdf" else "application/zip")
        quantidade = despesas.count()
        atuais = servicos.versoes_atuais(docs).values(
            "documento_id", "nome", "mime", "sequencia", descricao_despesa=F("documento__despesa__descricao"),
        )
        itens = Paginator(atuais, 25).get_page(request.GET.get("pagina"))
        registrar_evento(request, "doc.prestacao_consulta")
    return pagina(request, "prestacao", {"form": form, "pagina": itens, "despesas": quantidade,
                  "titulo": "Arquivo de prestação de contas"})
