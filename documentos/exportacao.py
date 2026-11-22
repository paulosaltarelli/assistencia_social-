import hashlib
import json
import tempfile
import zipfile
from collections import defaultdict
from io import BytesIO
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate
from financeiro.models import Despesa, Lancamento

from .models import Estado
from .servicos import todas_versoes


def arquivo_do_pacote(versao):
    d = versao.documento.despesa
    dot = d.dotacao
    return "/".join((
        str(dot.exercicio.ano), slugify(dot.fundo.nome)[:60] or "fundo",
        slugify(dot.fonte.nome)[:60] or "fonte", slugify(dot.programa.nome)[:60] or "programa",
        str(d.pk), versao.documento.categoria, str(versao.documento_id), f"v{versao.sequencia}_{versao.nome}",
    ))


def indice(municipio, versoes, filtros, quadro):
    arquivo = BytesIO()
    pdf = SimpleDocTemplate(arquivo, pagesize=A4, title="Índice de prestação de contas", author="Gestão Social Municipal")
    estilos = getSampleStyleSheet()
    pequeno = ParagraphStyle("Detalhe", parent=estilos["Normal"], fontSize=8, leading=11, spaceAfter=4)
    historia = [Paragraph("Índice de prestação de contas", estilos["Heading1"]),
                Paragraph(escape(municipio.nome), estilos["Heading2"])]
    if filtros:
        historia.append(Paragraph("Seleção · " + escape(" • ".join(filtros)), pequeno))
    historia.append(Paragraph(f"{len(quadro)} despesa(s) e {len(versoes)} versão(ões) de documento. Emissão em {timezone.localtime():%d/%m/%Y %H:%M}.", pequeno))
    for item in quadro:
        historia.append(Paragraph(escape(f"{item['processo']} · {item['descricao']}"), estilos["Heading3"]))
        historia.append(Paragraph(escape(f"Despesa {item['despesa']} · {item['data']} · R$ {item['valor']} · {item['fornecedor']}"), pequeno))
        historia.append(Paragraph(escape(" · ".join([str(item['exercicio']), item['fundo'], item['fonte'], item['programa']])), pequeno))
        for movimento in item["movimentos"]:
            texto = f"{movimento['etapa']} {movimento['referencia']} · {movimento['data']} · R$ {movimento['valor']} · {movimento['documento']}"
            historia.append(Paragraph(escape(texto), pequeno))
        if not item["documentos"]:
            historia.append(Paragraph("Sem documentos autorizados na seleção.", pequeno))
    if versoes:
        historia.append(Paragraph("Índice de originais", estilos["Heading2"]))
    for ordem, v in enumerate(versoes, 1):
        despesa = v.documento.despesa
        dot = despesa.dotacao
        resumo = f"{ordem}. {v.nome} (v{v.sequencia})"
        historia.extend([
            Paragraph(escape(resumo), estilos["Heading3"]),
            Paragraph(escape(f"Despesa {despesa.pk} · {despesa.descricao} · Processo {despesa.processo or 'sem referência'}"), pequeno),
            Paragraph(escape(f"{dot.exercicio.ano} · {dot.fundo.nome} · {dot.fonte.nome} · {dot.programa.nome}"), pequeno),
            Paragraph(escape(f"{v.documento.get_categoria_display()} · {Estado(v.estado_atual).label} · "
                             f"{timezone.localtime(v.criado_em):%d/%m/%Y} · {v.responsavel.get_username()}"), pequeno),
            Paragraph(escape(f"SHA-256: {v.sha256}"), pequeno),
        ])
    def rodape(canvas, doc):
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(A4[0] - 55, 35, f"Página {doc.page}")

    pdf.build(historia, onFirstPage=rodape, onLaterPages=rodape)
    return arquivo.getvalue()


def preparar(municipio, documentos, filtros, incluir_originais, despesas=None):
    documentos = documentos.filter(municipio=municipio, despesa__isnull=False)
    if despesas is None:
        despesas = Despesa.objects.filter(pk__in=documentos.values("despesa_id"))
    despesas = list(despesas.filter(municipio=municipio).select_related("dotacao__exercicio", "dotacao__fundo", "dotacao__fonte", "dotacao__programa")
                    .order_by("data", "pk")[:1001])
    if not despesas:
        raise ValidationError("Nenhuma despesa para os filtros selecionados.")
    if len(despesas) > 1000:
        raise ValidationError("A seleção excede 1.000 despesas. Reduza o período ou selecione um fundo ou programa.")
    ids_despesas = [d.pk for d in despesas]
    versoes = list(todas_versoes(documentos.filter(despesa_id__in=ids_despesas)).select_related(
        "documento__despesa__dotacao__exercicio", "documento__despesa__dotacao__fundo",
        "documento__despesa__dotacao__fonte", "documento__despesa__dotacao__programa",
    ).order_by("documento__despesa__data", "documento__despesa_id", "documento_id", "sequencia")[:1001])
    if len(versoes) > 1000 or (incluir_originais and sum(v.tamanho for v in versoes) > 96 * 1024 * 1024):
        raise ValidationError("A seleção excede o limite do pacote. Use um período, fundo ou programa mais específico.")
    movimentos = list(Lancamento.objects.filter(municipio=municipio, despesa_id__in=ids_despesas)
                      .order_by("data", "criado_em", "pk")[:3001])
    if len(movimentos) > 3000:
        raise ValidationError("A seleção excede 3.000 lançamentos. Reduza o período ou selecione um fundo ou programa.")
    por_despesa = defaultdict(list)
    documentos_por_despesa = defaultdict(set)
    for v in versoes:
        documentos_por_despesa[v.documento.despesa_id].add(v.documento_id)
    for m in movimentos:
        por_despesa[m.despesa_id].append({
            "etapa": m.get_tipo_display(), "referencia": m.referencia, "documento": m.documento,
            "data": m.data.isoformat(), "valor": str(m.valor), "id": str(m.pk),
            "origem": str(m.anterior_id) if m.anterior_id else None,
        })
    quadro = [{
        "despesa": str(d.pk), "descricao": d.descricao, "processo": d.processo, "data": d.data.isoformat(),
        "valor": str(d.valor), "exercicio": d.dotacao.exercicio.ano, "fundo": d.dotacao.fundo.nome,
        "fonte": d.dotacao.fonte.nome, "origem_recurso": d.dotacao.fonte.get_origem_display(),
        "programa": d.dotacao.programa.nome, "fornecedor": d.fornecedor, "documento": d.documento,
        "movimentos": por_despesa[d.pk], "documentos": len(documentos_por_despesa[d.pk]),
    } for d in despesas]
    conteudo_indice = indice(municipio, versoes, filtros, quadro)
    if not incluir_originais:
        return BytesIO(conteudo_indice)
    buf = tempfile.SpooledTemporaryFile(max_size=1024*1024, mode="w+b")
    try:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as pacote:
            pacote.writestr("indice.pdf", conteudo_indice)
            pacote.writestr("quadro-financeiro.json", json.dumps(quadro, ensure_ascii=False, indent=2).encode("utf-8"))
            manifesto = []
            for v in versoes:
                caminho = arquivo_do_pacote(v)
                # Materializa um original por vez; metadados e versão são imutáveis.
                if hashlib.sha256(v.conteudo).hexdigest() != v.sha256:
                    raise ValidationError("Falha na verificação de integridade. A exportação foi interrompida.")
                pacote.writestr(caminho, bytes(v.conteudo))
                del v.conteudo
                manifesto.append({
                    "arquivo": caminho, "documento": str(v.documento_id), "despesa": str(v.documento.despesa_id),
                    "versao": v.sequencia, "nome": v.nome, "tamanho": v.tamanho, "categoria": v.documento.get_categoria_display(),
                    "sha256": v.sha256, "conferencia": Estado(v.estado_atual).label,
                    "criado_em": v.criado_em.isoformat(),
                })
            pacote.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        return buf
    except Exception:
        buf.close()
        raise
