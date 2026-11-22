"""Originais fictícios para homologação, registrados pelo fluxo de ingestão do acervo."""
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .arquivos import receber
from .forms import DocumentoForm
from .models import Categoria, Estado, Versao
from .servicos import conferir, guardar_versao


def exemplo(referencia, titulo, formato, versao):
    arquivo = BytesIO()
    marca = "SIMULADO - DOCUMENTO DE DEMONSTRACAO"
    if formato == "pdf":
        pdf = Canvas(arquivo, pagesize=A4, invariant=True)
        pdf.setTitle(f"Simulado · {titulo}")
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(45, 770, marca)
        pdf.setFont("Helvetica", 12)
        pdf.drawString(45, 718, titulo)
        pdf.drawString(45, 690, f"Referência {referencia} · Versão {versao}")
        pdf.drawString(45, 635, "Exemplar fictício para treinamento, sem valor fiscal ou probatório.")
        pdf.save()
    elif formato == "png":
        imagem = Image.new("RGB", (900, 340), color="white")
        desenho = ImageDraw.Draw(imagem)
        desenho.rectangle((0, 0, 900, 62), fill="#173e45")
        desenho.text((28, 18), marca, font_size=23, fill="white")
        desenho.text((28, 100), titulo, font_size=24, fill="#173e45")
        desenho.text((28, 155), f"{referencia}  -  versão {versao}", font_size=19, fill="#173e45")
        desenho.text((28, 250), "Imagem fictícia para treinamento", font_size=20, fill="#52656a")
        imagem.save(arquivo, format="PNG")
    else:
        from xml.etree import ElementTree as XML
        raiz = XML.Element("exemploMunicipal", {"finalidade": "SIMULADO", "versao": str(versao)})
        XML.SubElement(raiz, "referencia").text = referencia
        XML.SubElement(raiz, "tipo").text = titulo
        XML.SubElement(raiz, "informacao").text = "Documento fictício para treinamento. Sem valor fiscal."
        XML.ElementTree(raiz).write(arquivo, encoding="utf-8", xml_declaration=True)
    return SimpleUploadedFile(f"{referencia}-v{versao}.{formato}", arquivo.getvalue())


def anexar(contexto, request, alvo, origem, categoria, formato, ordem, versao=1, anterior=None):
    if origem.municipio_id != contexto.municipio.pk:
        raise ValidationError("A origem do exemplo pertence a outro município.")
    operacao = contexto.identificador(f"documentos/{alvo}/{origem.pk}/{categoria}/v{versao}")
    existente = Versao.objects.filter(municipio=contexto.municipio, operacao=operacao).select_related("documento").defer("conteudo").first()
    if existente:
        if (existente.responsavel_id != contexto.usuario.pk
                or getattr(existente.documento, alvo + "_id") != origem.pk
                or existente.documento.categoria != categoria or existente.sequencia != versao):
            raise ValidationError("A referência de demonstração já possui outro vínculo.")
        return existente, False
    referencia = f"SIMULADO-{alvo.upper()}-{ordem:03d}-{categoria.upper()}"
    arquivo = exemplo(referencia, categoria.label, formato, versao)
    dados = {
        "categoria": categoria, "operacao": operacao, "base": versao - 1,
        "observacao": f"[SIMULADO] Exemplar de {categoria.label.lower()} para capacitação.",
        "vencimento": contexto.data_referencia + timedelta(days=(ordem % 5) * 4 - 7),
    }
    if alvo == "despesa":
        dados.update(razao_social=origem.fornecedor, processo_referencia=origem.processo)
    if categoria == Categoria.NOTA:
        dados.update(numero_nota=f"SIM-{contexto.ano}-{ordem:03d}", serie_nota="SIM",
                     cnpj_emissor="DEMO0000000100", valor_nota=origem.valor, data_emissao=origem.data,
                     descricao_itens="[SIMULADO] Materiais para oficinas de convivência.")
    form = DocumentoForm(dados, {"arquivo": arquivo})
    if not form.is_valid():
        raise ValidationError(form.errors.as_json())
    original = receber(arquivo)
    return guardar_versao(request, alvo, origem, form.cleaned_data, original, anterior), True


@transaction.atomic
def popular(contexto):
    if not contexto.homologacao:
        raise ValidationError("Os exemplos documentais exigem um contexto de homologação.")
    request = SimpleNamespace(municipio=contexto.municipio, user=contexto.usuario)
    previstos = []
    for i, despesa in enumerate(contexto.financeiro["despesas"], 1):
        if i % 4:
            previstos.append(("despesa", despesa, Categoria.NOTA, "xml" if i % 3 == 0 else "pdf", i))
        if i % 5 == 0:
            previstos.append(("despesa", despesa, Categoria.CONTRATO, "pdf", i))
        if i % 3 == 0 and despesa.lancamentos.filter(tipo="pagamento").exists():
            previstos.append(("despesa", despesa, Categoria.PAGAMENTO, "png", i))
    grupos = [
        ("receita", contexto.financeiro.get("receitas", [])[::4], Categoria.RECIBO, "pdf"),
        ("beneficio", contexto.beneficios[:12], Categoria.RECIBO, "pdf"),
        ("material", contexto.pedidos[:12], Categoria.ENTREGA, "png"),
        ("vale", contexto.vales[:8], Categoria.OUTRO, "pdf"),
    ]
    for alvo, origens, categoria, formato in grupos:
        previstos.extend((alvo, o, categoria, formato, i) for i, o in enumerate(origens, 1))
    contagens = {"documentos": 0, "versoes": 0, "conferencias": 0}
    for alvo, origem, categoria, formato, ordem in previstos:
        v, criado = anexar(contexto, request, alvo, origem, categoria, formato, ordem)
        if not criado:
            continue
        contagens["documentos"] += 1
        contagens["versoes"] += 1
        if ordem % 4:
            situacao = [Estado.ANEXADO, Estado.CONFERIDO, Estado.AGUARDANDO, Estado.PENDENCIA][ordem % 4]
            conferir(request, v, {"situacao": situacao, "observacao": "[SIMULADO] Conferência de capacitação.",
                    "motivo": "[SIMULADO] Aguardando complemento." if situacao == Estado.PENDENCIA else "", "providencia": ""})
            contagens["conferencias"] += 1
            if situacao == Estado.PENDENCIA and ordem % 8 == 3:
                v2, _ = anexar(contexto, request, alvo, origem, categoria, formato, ordem, 2, v.documento)
                conferir(request, v2, {"situacao": Estado.REGULARIZADO, "observacao": "", "motivo": "",
                        "providencia": "[SIMULADO] Complemento incluído e conferido na versão 2."})
                contagens["versoes"] += 1
                contagens["conferencias"] += 1
    return {"contagens": contagens}
