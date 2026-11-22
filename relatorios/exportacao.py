"""Exportação de conjuntos já autorizados e auditados pela view."""
from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def texto_seguro(valor):
    texto = str(valor if valor is not None else '')
    if texto.lstrip().startswith(('=', '+', '-', '@')) or texto.startswith(('\t', '\r', '\n')):
        return "'" + texto
    return texto


def xlsx(tabelas, municipio):
    livro = Workbook()
    livro.remove(livro.active)
    for indice, tabela in enumerate(tabelas, 1):
        folha = livro.create_sheet(f'{indice} {tabela["titulo"]}'[:31])
        folha.append([texto_seguro(municipio)])
        folha.append(tabela['colunas'])
        for celula in folha[2]:
            celula.font = Font(bold=True)
        for linha in tabela['linhas']:
            folha.append([valor if isinstance(valor, (int, float, Decimal)) else texto_seguro(valor) for valor in linha])
        folha.freeze_panes = 'A3'
        folha.auto_filter.ref = f'A2:{folha.cell(folha.max_row, folha.max_column).coordinate}'
        for coluna in folha.columns:
            folha.column_dimensions[coluna[0].column_letter].width = 28
    destino = BytesIO()
    livro.save(destino)
    resposta = HttpResponse(destino.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resposta['Content-Disposition'] = 'attachment; filename="relatorio-municipal.xlsx"'
    return resposta


def pdf(tabelas, municipio):
    destino = BytesIO()
    estilos = getSampleStyleSheet()
    documento = SimpleDocTemplate(destino, pagesize=landscape(A4), title='Relatório municipal',
                                 leftMargin=25, rightMargin=25, topMargin=25, bottomMargin=25)
    elementos = [Paragraph(escape(municipio), estilos['Title'])]
    for tabela in tabelas:
        elementos.extend([Paragraph(escape(tabela['titulo']), estilos['Heading2']), Spacer(1, 8)])
        linhas = [tabela['colunas'], *tabela['linhas']]
        conteudo = [[Paragraph(escape(str(celula if celula is not None else '')), estilos['BodyText'])
                     for celula in linha] for linha in linhas]
        largura = (landscape(A4)[0] - 50) / len(tabela['colunas'])
        grade = Table(conteudo, colWidths=[largura] * len(tabela['colunas']), repeatRows=1, hAlign='LEFT')
        grade.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eaf1f5')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elementos.extend([grade, Spacer(1, 14)])
    documento.build(elementos)
    resposta = HttpResponse(destino.getvalue(), content_type='application/pdf')
    resposta['Content-Disposition'] = 'attachment; filename="relatorio-municipal.pdf"'
    return resposta
