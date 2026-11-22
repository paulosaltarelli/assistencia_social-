from django.conf import settings
from django.urls import reverse
from contas.models import Secretaria
from contas.permissoes import permissoes_efetivas

SECOES = [
    ("Atendimento", [
        ("Início", "painel", "painel.ver", "layout-dashboard"),
        ("Pessoas e famílias", "cadastros:inicio", "cadastros.ver", "users-round"),
        ("Atendimentos", "cadastros:atendimentos", "atendimentos.ver", "clipboard-list"),
    ]),
    ("Programas municipais", [
        ("Benefícios eventuais", "programas:beneficios", "beneficios.ver", "hand-heart"),
        ("Materiais e estoque", "programas:estoque", "materiais.ver", "package"),
        ("Vale-Alimentação", "programas:vales", "vale.ver", "credit-card"),
    ]),
    ("Gestão", [
        ("Painel do gestor", "financeiro:gestor", "gestao.ver", "landmark"),
        ("Financeiro", "financeiro:inicio", "financeiro.ver", "wallet"),
        ("Documentos", "documentos:inicio", "documentos.ver", "files"),
        ("Relatórios", "relatorios:inicio", "relatorios.ver", "chart-column"),
        ("Alertas", "relatorios:alertas", "relatorios.ver", "bell"),
    ]),
    ("Administração", [
        ("Equipe e acessos", "contas:inicio", "contas.gerir", "settings"),
        ("Dados da secretaria", "contas:configurar", "configuracao.editar", "landmark"),
    ]),
]


def contexto(request):
    dados = {
        "municipio_publico": settings.SOCIAL_MUNICIPIO_PUBLICO,
        "homologacao": settings.SOCIAL_HOMOLOGACAO,
    }
    vinculo = getattr(request, "vinculo", None)
    if not vinculo:
        return dados
    permissoes = permissoes_efetivas(vinculo)
    grupos = []
    candidatas = []
    for nome, itens in SECOES:
        links = []
        for titulo, rota, permissao, icone in itens:
            if permissao not in permissoes or (permissao == "gestao.ver" and vinculo.perfil != "gestor"):
                continue
            href = reverse(rota)
            link = {"titulo": titulo, "url": href, "icone": icone, "ativo": False}
            links.append(link)
            if request.path == href or (href != "/" and request.path.startswith(href)):
                candidatas.append(link)
        if links:
            grupos.append((nome, links))
    if candidatas:
        max(candidatas, key=lambda link: len(link["url"]))["ativo"] = True
    orgao = Secretaria.objects.filter(municipio_id=vinculo.municipio_id).values_list("nome", flat=True).first()
    dados.update(menu_municipal=grupos, direitos=permissoes, orgao_municipal=orgao)
    return dados
