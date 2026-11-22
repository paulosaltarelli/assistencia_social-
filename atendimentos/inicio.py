from django.db.models import Count, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from contas.permissoes import permissoes_efetivas
from financeiro.consultas import resumo_financeiro
from programas.models import ConcessaoVale, PedidoMaterial, SolicitacaoBeneficio
from relatorios.consultas import series_resumidas
from relatorios.territorial import resumo_territorial

from .acesso import municipal, registrar_evento
from .models import Atendimento, Cidadao, Familia


LEGADO = {
    "familia": "cadastros:familia_nova",
    "cidadao": "cadastros:pessoa_nova",
    "atendimento": "cadastros:atendimento_novo",
}


def cadastro_legado(request, cadastro):
    if cadastro not in LEGADO:
        raise Http404()
    return HttpResponseRedirect(reverse(LEGADO[cadastro]), preserve_request=request.method == "POST")


@never_cache
@municipal("painel.ver")
@require_http_methods(["GET", "HEAD", "POST"])
def inicio(request):
    if request.method == "POST":
        return cadastro_legado(request, request.POST.get("tipo", "atendimento"))
    municipio = request.municipio
    direitos = permissoes_efetivas(request.vinculo)
    hoje = timezone.localdate()
    indicadores = []
    pendencias = []

    def indicador(rotulo, valor, rota):
        indicadores.append((rotulo, valor, reverse(rota)))

    if "cadastros.ver" in direitos:
        indicador("Pessoas cadastradas", Cidadao.objects.filter(municipio=municipio).count(), "cadastros:inicio")
        indicador("Famílias cadastradas", Familia.objects.filter(municipio=municipio).count(), "cadastros:familias")
    if "atendimentos.ver" in direitos:
        atendimentos = Atendimento.objects.filter(municipio=municipio)
        if "sigilo.ver" not in direitos:
            atendimentos = atendimentos.exclude(acompanhamento__sigiloso=True)
        indicador("Atendimentos registrados", atendimentos.count(), "cadastros:atendimentos")
    if "beneficios.ver" in direitos:
        totais = SolicitacaoBeneficio.objects.filter(municipio=municipio).aggregate(
            concedidos=Count("pk", filter=Q(concedido_em__date__range=(hoje.replace(day=1), hoje))),
            pendentes=Count("pk", filter=Q(situacao__in=["analise", "solicitado"])),
        )
        indicador("Benefícios concedidos no mês", totais["concedidos"], "programas:beneficios")
        pendencias.append(("Benefícios em análise ou aguardando análise", totais["pendentes"], reverse("programas:beneficios")))
    if "vale.ver" in direitos:
        indicador("Beneficiários ativos do vale", ConcessaoVale.objects.filter(municipio=municipio, situacao="ativo").values("cidadao_id").distinct().count(), "programas:vales")
    if "materiais.ver" in direitos:
        pedidos = PedidoMaterial.objects.filter(municipio=municipio)
        indicador("Solicitações de materiais", pedidos.count(), "programas:pedidos")
        indicador("Pedidos com entrega concluída", pedidos.filter(situacao="entregue").count(), "programas:pedidos")
        pendencias.append(("Pedidos de material em avaliação", pedidos.filter(situacao__in=["solicitado", "analise"]).count(), reverse("programas:pedidos")))
    financas = resumo_financeiro(municipio, {"ano": hoje.year}) if "financeiro.ver" in direitos else None
    registrar_evento(request, "visao_geral")
    return render(request, "inicio.html", {
        "indicadores": indicadores,
        "pendencias": pendencias,
        "financas": financas,
        "hoje": hoje,
        "series_resumidas": series_resumidas(municipio, request.vinculo),
        "territorial": resumo_territorial(municipio, request.vinculo, direitos=direitos, hoje=hoje),
    })
