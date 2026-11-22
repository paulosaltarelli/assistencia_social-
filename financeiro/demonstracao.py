"""Execução inteiramente fictícia para o comando de homologação municipal."""
from collections import Counter
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (Compromisso, Conciliacao, Despesa, Dotacao, Exercicio, Fonte, Fundo,
                     Lancamento, Natureza, Programa, Receita, RevisaoOrcamento, VinculoSocial)
from .servicos import cadastrar, executar_etapa, travar


# Nomes descritivos e referências próprias do cenário, sem números de convênios ou atos reais.
CLASSIFICACOES = [
    ("municipal", "Tesouro municipal", "Assistência social", "Benefícios eventuais", "Aquisição de bens"),
    ("estadual", "Transferência estadual", "Proteção social", "Materiais para moradia", "Material de consumo"),
    ("federal", "Transferência federal", "Proteção social", "Segurança alimentar", "Distribuição de bens"),
]


def periodos(data_referencia):
    indice = data_referencia.year * 12 + data_referencia.month - 1
    for posicao in range(indice - 11, indice + 1):
        ano, mes = divmod(posicao, 12)
        yield date(ano, mes + 1, 1)


@transaction.atomic
def popular(contexto):
    if getattr(contexto, "homologacao", False) is not True:
        raise ValidationError("A carga financeira exige um contexto de homologação.")
    municipio, usuario = contexto.municipio, contexto.user
    travar(f"demonstracao/{municipio.pk}")
    contagens = Counter()
    despesas = []
    recebimentos = []

    def novo(modelo, chave, **campos):
        identificador = contexto.identificador(f"financeiro/{modelo._meta.model_name}/{chave}")
        registro = modelo.objects.filter(municipio=municipio, pk=identificador).first()
        if registro:
            if registro.responsavel_id != usuario.pk:
                raise ValidationError("A chave reservada para a demonstração pertence a outro responsável.")
            return registro
        registro = modelo(pk=identificador, **campos)
        salvar = executar_etapa if modelo is Lancamento else cadastrar
        salvar(registro, municipio, usuario)
        contagens[modelo._meta.model_name] += 1
        return registro

    meses = list(periodos(contexto.data_referencia))
    dotacoes = {}
    for origem, fonte_nome, fundo_nome, programa_nome, natureza_nome in CLASSIFICACOES:
        prefixo = f"DEMO-FIN-{origem.upper()[:3]}"
        fonte = novo(Fonte, origem, codigo=prefixo, nome=f"[SIMULADO] {fonte_nome}", origem=origem,
                     finalidade=f"[SIMULADO] Custeio de {programa_nome.lower()}", restricoes="")
        cod_fundo = "AS" if fundo_nome == "Assistência social" else "PS"
        fundo = novo(Fundo, cod_fundo, codigo=f"DEMO-FIN-{cod_fundo}", nome=f"[SIMULADO] {fundo_nome}")
        programa = novo(Programa, origem, codigo=prefixo, nome=f"[SIMULADO] {programa_nome}")
        natureza = novo(Natureza, origem, codigo=prefixo, nome=f"[SIMULADO] {natureza_nome}")
        for ano in sorted({mes.year for mes in meses}):
            # O exercício é único no município, inclusive quando já existia antes do cenário.
            exercicio = Exercicio.objects.filter(municipio=municipio, ano=ano).first()
            if not exercicio:
                exercicio = novo(Exercicio, str(ano), ano=ano)
            dotacao = novo(Dotacao, f"{origem}/{ano}", codigo=f"{prefixo}-{ano}", exercicio=exercicio,
                           fonte=fonte, fundo=fundo, programa=programa, natureza=natureza,
                           valor_inicial=Decimal("180000"), saldo_inicial=Decimal("12000"))
            dotacoes[origem, ano] = dotacao

    origens = {"municipal": ("beneficio", contexto.beneficios), "estadual": ("material", contexto.pedidos),
               "federal": ("vale", contexto.vales)}
    for mes in meses:
        for grupo, (origem, _, _, programa_nome, _) in enumerate(CLASSIFICACOES, 1):
            dotacao = dotacoes[origem, mes.year]
            chave = f"{mes:%Y%m}-{origem.upper()[:3]}"
            processo = f"DEMO-FIN-{chave}"

            def dia(numero):
                return min(mes.replace(day=numero), contexto.data_referencia)

            valor = Decimal(3500 + grupo * 280 + mes.month * 45)
            for tipo, numero, total in [("prevista", 1, valor * 3), ("recebida", 3, valor * 2)]:
                receita = novo(Receita, f"{chave}/{tipo}", dotacao=dotacao, data=dia(numero), tipo=tipo, valor=total,
                               origem=f"[SIMULADO] Origem {origem}", documento=f"{processo}-REC",
                               comprovante=f"{processo}-EXTRATO" if tipo == "recebida" else "")
                if tipo == "recebida":
                    recebimentos.append(receita)
            if mes.month in (3, 9):
                tipo = "credito" if mes.month == 3 else "anulacao"
                novo(RevisaoOrcamento, chave, dotacao=dotacao, data=dia(3), tipo=tipo,
                     valor=Decimal(1000), documento=f"{processo}-ATO",
                     motivo="[SIMULADO] Ajuste de dotação para o exercício demonstrativo")
            despesa = novo(Despesa, chave, dotacao=dotacao, data=dia(4), descricao=f"[SIMULADO] {programa_nome} – {mes:%m/%Y}",
                           fornecedor=f"[SIMULADO] Fornecedor {grupo}", categoria="[SIMULADO] Custeio",
                           valor=valor, documento=f"{processo}-DOC", processo=processo,
                           observacoes="[SIMULADO] Despesa exclusiva para demonstração.")
            despesas.append(despesa)
            compromisso = novo(Compromisso, chave, dotacao=dotacao, data=dia(4), vencimento=mes.replace(day=25),
                               descricao=f"[SIMULADO] Reserva para {programa_nome.lower()}", referencia=f"{processo}-RES",
                               valor=valor, situacao="reservado")
            campo, registros = origens[origem]
            candidatos = [r for r in registros if mes <= r.solicitado_em <= dia(11)
                          and r.situacao in {"aprovado", "parcial", "entregue", "ativo"}]
            if candidatos:
                novo(VinculoSocial, chave, despesa=despesa, **{campo: candidatos[0]})

            # A distribuição muda conforme mês e origem, e é estável em reexecuções.
            fase = (mes.month + grupo) % 6
            if fase == 0:
                continue
            def etapa(tipo, numero, total, anterior=None, reserva=None):
                return novo(Lancamento, f"{chave}/{tipo}", despesa=despesa, tipo=tipo, data=dia(numero),
                            valor=total, referencia=f"{processo}-{tipo.upper()}", documento=f"{processo}-{tipo[:3]}-DOC",
                            anterior=anterior, compromisso=reserva)

            empenho = etapa("empenho", 6, valor, reserva=compromisso)
            if fase < 2:
                continue
            liquidado = valor / 2 if fase == 2 else valor
            liquidacao = etapa("liquidacao", 9, liquidado, anterior=empenho)
            if fase == 2:
                continue
            pago = liquidado / 2 if fase == 3 else liquidado
            etapa("pagamento", 11, pago, anterior=liquidacao)
            if fase >= 4:
                novo(Conciliacao, chave, despesa=despesa, data=dia(12), referencia=f"{processo}-CONT",
                     situacao="conferido" if fase == 5 else "divergente",
                     observacoes="[SIMULADO] Resultado do confronto com o extrato de treinamento.")
    return {"despesas": despesas, "receitas": recebimentos, "contagens": dict(contagens)}
