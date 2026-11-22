"""Cenário inteiramente simulado e aditivo para homologação autorizada.

Chaves UUID pertencem a um namespace reservado. Uma carga confirmada mantém a
mesma data-base nas reexecuções. O relógio de fixtures afeta apenas este processo
de comando e permite inserir registros históricos pelas APIs normais do Django.
"""
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from django.core.exceptions import ValidationError
from django.utils import timezone

from atendimentos.models import Atendimento, Cidadao, Familia
from cadastros.models import AcompanhamentoAtendimento, ComplementoFamilia, ComplementoPessoa, NotaTecnica
from programas.models import ConcessaoVale, Material, MovimentoEstoque, PedidoMaterial, SolicitacaoBeneficio, TipoBeneficio
from programas.services import alterar_vale, decidir_beneficio, decidir_pedido, historico, movimentar_estoque, solicitar_beneficio


VERSAO = "vexo-social-demonstracao-v1"
MARCA = "[SIMULADO]"
BAIRROS = [f"{MARCA} Setor {nome}" for nome in ("Azul", "Verde", "Amarelo", "Laranja", "Violeta", "Branco")]


def meses_anteriores(referencia):
    indice = referencia.year * 12 + referencia.month - 1
    return [date(numero // 12, numero % 12 + 1, 1) for numero in range(indice - 11, indice + 1)]


@dataclass
class Contexto:
    municipio: object
    user: object
    data_referencia: date
    homologacao: bool = True
    familias: list = field(default_factory=list)
    cidadaos: list = field(default_factory=list)
    beneficios: list = field(default_factory=list)
    pedidos: list = field(default_factory=list)
    vales: list = field(default_factory=list)
    financeiro: dict = field(default_factory=dict)
    contagens: Counter = field(default_factory=Counter)

    @property
    def usuario(self):
        return self.user

    @property
    def ano(self):
        return self.data_referencia.year

    def identificador(self, chave):
        return uuid5(NAMESPACE_URL, f"{VERSAO}/municipio/{self.municipio.pk}/{chave}")

    def contar(self, chave, quantidade=1):
        self.contagens[chave] += quantidade

    @contextmanager
    def no_instante(self, dia, hora=10):
        instante = timezone.make_aware(datetime.combine(dia, time(hora, 0)))
        with patch("django.utils.timezone.now", return_value=instante):
            yield instante

    def criar(self, modelo, chave, **defaults):
        pk = self.identificador(f"{modelo._meta.label_lower}/{chave}")
        existente = modelo.objects.filter(pk=pk, municipio=self.municipio).first()
        if existente:
            return existente, False
        objeto = modelo(pk=pk, municipio=self.municipio, **defaults)
        # Preenche timestamps para validação, antes de seus pre_save automáticos.
        for campo in modelo._meta.local_fields:
            if getattr(campo, "auto_now_add", False) or getattr(campo, "auto_now", False):
                setattr(objeto, campo.name, timezone.now())
        objeto.full_clean()
        objeto.save(force_insert=True)
        self.contar(modelo._meta.label_lower)
        return objeto, True


def configurar_periodo(contexto, explicita=False):
    chave = contexto.identificador("metadados/periodo")
    existente = TipoBeneficio.objects.filter(pk=chave, municipio=contexto.municipio).first()
    if existente:
        try:
            dados = json.loads(existente.regra_local)
            referencia = date.fromisoformat(dados["data_referencia"])
            if dados["versao"] != VERSAO:
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError("O marcador reservado da demonstração não confere. Nenhum dado foi alterado.") from exc
        if explicita and contexto.data_referencia != referencia:
            raise ValidationError("A carga existente usa outra data-base. Reutilize-a para preservar a demonstração.")
        contexto.data_referencia = referencia
        return
    marcador = TipoBeneficio(
        pk=chave, municipio=contexto.municipio, nome=f"{MARCA} Controle da carga demonstrativa",
        regra_local=json.dumps({"versao": VERSAO, "data_referencia": contexto.data_referencia.isoformat(),
            "aviso": "Metadados de treinamento. Não representam norma ou critério municipal real."}, ensure_ascii=False),
        vigencia_inicio=meses_anteriores(contexto.data_referencia)[0], ativo=False,
    )
    marcador.full_clean()
    marcador.save(force_insert=True)
    contexto.contar("programas.tipobeneficio")


def popular_cadastros(contexto):
    referencia = contexto.data_referencia
    for numero in range(1, 81):
        familia, nova = contexto.criar(Familia, f"familia/{numero}", referencia=f"{MARCA} Família cenário {numero:03d}")
        contexto.familias.append(familia)
        integrantes = []
        for posicao in range(2 + numero % 4):
            pessoa, _ = contexto.criar(Cidadao, f"pessoa/{numero}/{posicao}", familia=familia,
                nome=f"{MARCA} Pessoa {numero:03d}-{posicao + 1}")
            contexto.cidadaos.append(pessoa)
            integrantes.append(pessoa)
            idade = (22 + numero % 48) if posicao == 0 else (4 + (numero + posicao * 9) % 70)
            contexto.criar(ComplementoPessoa, f"pessoa/dados/{numero}/{posicao}", cidadao=pessoa,
                nascimento=date(referencia.year - idade, 1 + (numero + posicao) % 12, 1 + numero % 27),
                parentesco="Referência familiar" if posicao == 0 else "Integrante simulado",
                telefone="", cpf_hash="", cpf_ultimos="", nis_hash="", nis_ultimos="")
        contexto.criar(ComplementoFamilia, f"familia/dados/{numero}", familia=familia,
            endereco=f"{MARCA} Rua do cenário {numero:03d}", numero=str(numero), bairro=BAIRROS[numero % len(BAIRROS)],
            territorio=f"{MARCA} Território {1 + numero % 3}", cidade="Santa Cruz de Minas — cenário simulado",
            renda_mensal=Decimal(250 + (numero % 12) * 180),
            moradia=f"{MARCA} " + ["Própria", "Alugada", "Cedida", "Moradia provisória"][numero % 4],
            responsavel=integrantes[0])


def popular_atendimentos(contexto):
    for indice, mes in enumerate(meses_anteriores(contexto.data_referencia)):
        for numero in range(18 + indice * 2):
            pessoa = contexto.cidadaos[(indice * 23 + numero * 7) % len(contexto.cidadaos)]
            dia = min(mes.replace(day=1 + numero % 27), contexto.data_referencia)
            situacao = ["aberto", "aguarda", "concluido", "concluido"][numero % 4]
            with contexto.no_instante(dia) as instante:
                atendimento, _ = contexto.criar(Atendimento, f"atendimento/{mes:%Y%m}/{numero}", cidadao=pessoa,
                    unidade=f"{MARCA} Unidade {1 + numero % 3}",
                    encaminhamento=f"{MARCA} " + ["Orientação cadastral", "Acompanhamento familiar", "Avaliação de benefício", "Retorno de encaminhamento"][numero % 4])
                acompanhamento, _ = contexto.criar(AcompanhamentoAtendimento, f"acompanhamento/{mes:%Y%m}/{numero}",
                    atendimento=atendimento, data_efetiva=instante, situacao=situacao, responsavel=contexto.user,
                    proxima_acao=f"{MARCA} Revisar pendências do cenário" if situacao != "concluido" else "",
                    retorno=dia + timedelta(days=10) if situacao != "concluido" else None, sigiloso=numero % 11 == 0)
                if acompanhamento.sigiloso:
                    contexto.criar(NotaTecnica, f"nota/{mes:%Y%m}/{numero}", acompanhamento=acompanhamento,
                        texto=f"{MARCA} Nota fictícia de treinamento para demonstrar restrição de acesso técnico. Sem caso real associado.")


def popular_beneficios(contexto):
    tipos = []
    for indice, nome in enumerate(["Cesta básica", "Auxílio natalidade", "Auxílio funeral", "Auxílio passagem"]):
        tipo, _ = contexto.criar(TipoBeneficio, f"tipo/{indice}", nome=f"{MARCA} {nome}",
            regra_local=f"{MARCA} Critérios fictícios para treinamento. Nenhuma lei ou regra municipal real foi associada.",
            vigencia_inicio=meses_anteriores(contexto.data_referencia)[0])
        tipos.append(tipo)
    for indice, mes in enumerate(meses_anteriores(contexto.data_referencia)):
        for numero in range(6):
            chave = f"beneficio/{mes:%Y%m}/{numero}"
            pk = contexto.identificador(chave)
            existente = SolicitacaoBeneficio.objects.filter(pk=pk, municipio=contexto.municipio).first()
            if existente:
                contexto.beneficios.append(existente)
                continue
            pessoa = contexto.cidadaos[(indice * 11 + numero * 13) % len(contexto.cidadaos)]
            dia = min(mes.replace(day=4 + numero), contexto.data_referencia)
            with contexto.no_instante(dia):
                beneficio = solicitar_beneficio(SolicitacaoBeneficio(pk=pk, municipio=contexto.municipio,
                    familia=pessoa.familia, cidadao=pessoa, tipo=tipos[numero % len(tipos)], solicitado_em=dia,
                    quantidade_solicitada=Decimal("2"), valor_solicitado=Decimal(100 + numero * 50),
                    observacoes=f"{MARCA} Solicitação do cenário {mes:%m/%Y}-{numero}.",
                    justificativa_tecnica=f"{MARCA} Conteúdo técnico fictício para testar o perfil autorizado."), contexto.user)
                fase = (indice + numero) % 7
                if fase:
                    decidir_beneficio(pk, contexto.municipio, contexto.user, "analise", f"{MARCA} Triagem da solicitação.")
                if fase in (2, 3, 4):
                    parcial = fase == 3
                    decidir_beneficio(pk, contexto.municipio, contexto.user, "parcial" if parcial else "aprovado",
                        f"{MARCA} Decisão de treinamento, sem concessão real.", Decimal("1") if parcial else Decimal("2"),
                        beneficio.valor_solicitado / 2 if parcial else beneficio.valor_solicitado)
                    if fase == 4:
                        decidir_beneficio(pk, contexto.municipio, contexto.user, "entregue", f"{MARCA} Recibo demonstrativo {mes:%Y%m}-{numero}.")
                if fase == 5:
                    decidir_beneficio(pk, contexto.municipio, contexto.user, "indeferido", f"{MARCA} Documentação fictícia insuficiente no cenário.")
                if fase == 6:
                    decidir_beneficio(pk, contexto.municipio, contexto.user, "cancelado", f"{MARCA} Solicitação fictícia encerrada para demonstração.")
                beneficio.refresh_from_db()
                contexto.beneficios.append(beneficio)
                contexto.contar("programas.solicitacaobeneficio")


def popular_materiais(contexto):
    materiais = []
    for numero, (nome, unidade) in enumerate([("Cimento", "saco"), ("Tijolo", "unidade"), ("Telha", "unidade"), ("Areia", "m³")]):
        material, _ = contexto.criar(Material, f"material/{numero}", nome=f"{MARCA} {nome}", unidade=unidade,
            estoque_minimo=Decimal(12), custo_unitario=Decimal(12 + numero * 3))
        materiais.append(material)
    contexto.criar(Material, "material/estoque-baixo", nome=f"{MARCA} Material aguardando reposição", unidade="unidade",
        estoque_minimo=Decimal(8), custo_unitario=Decimal(18))
    for indice, mes in enumerate(meses_anteriores(contexto.data_referencia)):
        dia = min(mes.replace(day=3), contexto.data_referencia)
        with contexto.no_instante(dia):
            for numero, material in enumerate(materiais):
                chave = contexto.identificador(f"estoque/entrada/{mes:%Y%m}/{numero}")
                if not MovimentoEstoque.objects.filter(pk=chave, municipio=contexto.municipio).exists():
                    movimentar_estoque(contexto.municipio, contexto.user, material.pk, Decimal(30 + numero * 4),
                        f"{MARCA} Entrada {mes:%Y%m}-{numero}", custo_unitario=Decimal(12 + numero * 3), chave=chave)
                    contexto.contar("programas.movimentoestoque")
            for numero in range(3):
                pessoa = contexto.cidadaos[(indice * 17 + numero * 9) % len(contexto.cidadaos)]
                pedido, criado = contexto.criar(PedidoMaterial, f"pedido/{mes:%Y%m}/{numero}",
                    familia=pessoa.familia, cidadao=pessoa, material=materiais[(indice + numero) % len(materiais)],
                    solicitado_em=dia, quantidade_solicitada=Decimal(5 + numero), responsavel=contexto.user,
                    justificativa=f"{MARCA} Pedido fictício para manutenção de moradia no cenário.")
                contexto.pedidos.append(pedido)
                if not criado:
                    continue
                historico(pedido, contexto.user, "", f"{MARCA} Solicitação criada.")
                fase = (indice + numero) % 7
                if fase:
                    decidir_pedido(pedido.pk, contexto.municipio, contexto.user, "analise", f"{MARCA} Avaliação técnica simulada.")
                if fase in (2, 3, 4):
                    parcial = fase == 3
                    quantidade = pedido.quantidade_solicitada / 2 if parcial else pedido.quantidade_solicitada
                    decidir_pedido(pedido.pk, contexto.municipio, contexto.user, "parcial" if parcial else "aprovado", f"{MARCA} Decisão simulada.", quantidade)
                    if fase == 4:
                        movimentar_estoque(contexto.municipio, contexto.user, pedido.material_id, quantidade,
                            f"{MARCA} Recibo de entrega {mes:%Y%m}-{numero}", tipo="saida", pedido_id=pedido.pk,
                            chave=contexto.identificador(f"estoque/entrega/{mes:%Y%m}/{numero}"))
                        contexto.contar("programas.movimentoestoque")
                if fase == 5:
                    decidir_pedido(pedido.pk, contexto.municipio, contexto.user, "disponibilidade", f"{MARCA} Aguardando reposição no cenário.")
                if fase == 6:
                    decidir_pedido(pedido.pk, contexto.municipio, contexto.user, "indeferido", f"{MARCA} Indeferimento fictício para treinamento.")
                pedido.refresh_from_db()


def popular_vales(contexto):
    for numero in range(60):
        mes = meses_anteriores(contexto.data_referencia)[numero % 12]
        dia = min(mes.replace(day=6), contexto.data_referencia)
        pessoa = contexto.cidadaos[(numero * 7) % len(contexto.cidadaos)]
        with contexto.no_instante(dia):
            vale, criado = contexto.criar(ConcessaoVale, f"vale/{numero}", familia=pessoa.familia, cidadao=pessoa,
                valor=Decimal(100 + numero % 4 * 50), periodicidade="mensal" if numero % 3 else "quinzenal",
                solicitado_em=dia, responsavel=contexto.user)
            contexto.vales.append(vale)
            if not criado:
                continue
            historico(vale, contexto.user, "", f"{MARCA} Solicitação de Vale-Alimentação fictícia.")
            fase = numero % 5
            if fase == 4:
                alterar_vale(vale.pk, contexto.municipio, contexto.user, "indeferido", vale.valor, vale.periodicidade, f"{MARCA} Indeferimento fictício.")
            elif fase:
                alterar_vale(vale.pk, contexto.municipio, contexto.user, "ativo", vale.valor, vale.periodicidade, f"{MARCA} Inclusão fictícia.")
                if fase in (2, 3):
                    alterar_vale(vale.pk, contexto.municipio, contexto.user, "suspenso" if fase == 2 else "desligado", vale.valor,
                        vale.periodicidade, f"{MARCA} Reavaliação fictícia para demonstrar histórico.")
            vale.refresh_from_db()


def popular(contexto, data_explicita=False):
    configurar_periodo(contexto, explicita=data_explicita)
    popular_cadastros(contexto)
    popular_atendimentos(contexto)
    popular_beneficios(contexto)
    popular_materiais(contexto)
    popular_vales(contexto)
    from financeiro.demonstracao import popular as financeiro
    from documentos.demonstracao import popular as documentos
    contexto.financeiro = financeiro(contexto)
    dados_documentos = documentos(contexto)
    beneficio_entregue = next((b for b in contexto.beneficios if b.situacao == "entregue"), None)
    pedido_entregue = next((p for p in contexto.pedidos if p.situacao == "entregue"), None)
    vale_ativo = next((v for v in contexto.vales if v.situacao == "ativo"), None)
    jornadas = [
        {"titulo": "Consultar família, integrantes e atendimentos simulados", "url": f"/cadastros/familias/{contexto.familias[0].pk}/"},
        {"titulo": "Consultar pessoa e histórico autorizado", "url": f"/cadastros/pessoas/{contexto.cidadaos[0].pk}/"},
    ]
    for titulo, objeto, trecho in [
        ("Benefício com análise, decisão e entrega", beneficio_entregue, "beneficios"),
        ("Material entregue com baixa de estoque e recibo", pedido_entregue, "materiais/pedidos"),
        ("Vale ativo com valor, periodicidade e histórico", vale_ativo, "vale"),
    ]:
        if objeto:
            jornadas.append({"titulo": titulo, "url": f"/programas/{trecho}/{objeto.pk}/"})
    despesas = contexto.financeiro.get("despesas", [])
    if despesas:
        jornadas.append({"titulo": "Despesa e documentos simulados", "url": f"/financeiro/despesas/{despesas[0].pk}/"})
    return {
        "versao": VERSAO, "data_referencia": contexto.data_referencia.isoformat(),
        "criados": dict(contexto.contagens), "financeiro": contexto.financeiro.get("contagens", {}),
        "documentos": dados_documentos,
        "cenario": {"familias": len(contexto.familias), "pessoas": len(contexto.cidadaos),
                    "beneficios": len(contexto.beneficios), "pedidos": len(contexto.pedidos), "vales": len(contexto.vales)},
        "situacoes_beneficios": dict(Counter(b.situacao for b in contexto.beneficios)),
        "situacoes_materiais": dict(Counter(p.situacao for p in contexto.pedidos)),
        "situacoes_vales": dict(Counter(v.situacao for v in contexto.vales)),
        "jornadas": jornadas,
    }
