"""Permissões independentes por módulo. A ausência representa recusa."""

PERFIS = [
    ("administrador", "Administrador"), ("gestor", "Gestor"),
    ("coordenador", "Coordenador"), ("assistente", "Assistente social"),
    ("psicologo", "Psicólogo"), ("atendente", "Atendente"),
    ("almoxarifado", "Almoxarifado"), ("financeiro", "Financeiro"),
    ("consulta", "Consulta"), ("tecnico", "Técnico (legado)"),
    ("auditor", "Auditor (legado)"),
]

PERMISSOES = {
    "painel.ver": "Acessar página inicial",
    "beneficios.tecnico": "Consultar e elaborar parecer técnico protegido",
    "cadastros.ver": "Consultar cadastros",
    "cadastros.editar": "Cadastrar e alterar pessoas e famílias",
    "atendimentos.ver": "Consultar atendimentos",
    "atendimentos.editar": "Registrar e alterar atendimentos",
    "sigilo.ver": "Consultar conteúdo técnico sigiloso",
    "sigilo.editar": "Registrar conteúdo técnico sigiloso",
    "beneficios.ver": "Consultar benefícios",
    "beneficios.editar": "Gerenciar benefícios",
    "materiais.ver": "Consultar materiais",
    "materiais.editar": "Gerenciar materiais",
    "vale.ver": "Consultar vale-alimentação",
    "vale.editar": "Gerenciar vale-alimentação",
    "financeiro.ver": "Consultar financeiro",
    "financeiro.editar": "Gerenciar financeiro",
    "gestao.ver": "Acessar painel exclusivo do gestor",
    "documentos.ver": "Consultar documentos",
    "documentos.editar": "Gerenciar documentos",
    "relatorios.ver": "Consultar relatórios",
    "relatorios.exportar": "Exportar relatórios",
    "contas.gerir": "Gerenciar contas do próprio município",
    "configuracao.editar": "Configurar identidade da Secretaria",
    "contas.conceder_financeiro": "Autorizar concessões financeiras",
    "contas.conceder_sigilo": "Autorizar concessões de sigilo",
    "contas.conceder_gestao": "Autorizar acesso ao painel exclusivo",
}

MATRIZ = {
    "administrador": {"contas.gerir", "configuracao.editar"},
    "gestor": {"cadastros.ver", "atendimentos.ver", "beneficios.ver", "materiais.ver", "vale.ver", "relatorios.ver"},
    "coordenador": {"cadastros.ver", "cadastros.editar", "atendimentos.ver", "atendimentos.editar", "beneficios.ver", "beneficios.editar", "materiais.ver", "vale.ver", "relatorios.ver", "relatorios.exportar", "documentos.ver"},
    "assistente": {"cadastros.ver", "cadastros.editar", "atendimentos.ver", "atendimentos.editar", "sigilo.ver", "sigilo.editar", "beneficios.tecnico", "beneficios.ver", "beneficios.editar", "documentos.ver", "documentos.editar"},
    "psicologo": {"cadastros.ver", "atendimentos.ver", "atendimentos.editar", "beneficios.ver", "sigilo.ver", "sigilo.editar", "beneficios.tecnico", "documentos.ver", "documentos.editar"},
    "atendente": {"cadastros.ver", "cadastros.editar", "atendimentos.ver", "atendimentos.editar"},
    "almoxarifado": {"materiais.ver", "materiais.editar", "documentos.ver", "documentos.editar"},
    "financeiro": {"financeiro.ver", "financeiro.editar", "vale.ver", "vale.editar", "documentos.ver", "documentos.editar"},
    "consulta": {"cadastros.ver", "atendimentos.ver"},
    "tecnico": {"cadastros.ver", "cadastros.editar", "atendimentos.ver", "atendimentos.editar"},
    "auditor": {"cadastros.ver", "atendimentos.ver", "relatorios.ver"},
}

# Estes poderes de delegação são concedidos por procedimento operacional explícito.
DELEGACOES = {"contas.conceder_financeiro", "contas.conceder_sigilo", "contas.conceder_gestao"}
FINANCEIRAS = {"financeiro.ver", "financeiro.editar", "vale.editar"}
SIGILOSAS = {"sigilo.ver", "sigilo.editar", "beneficios.tecnico"}
GESTAO = {"gestao.ver"}


def permissoes_efetivas(vinculo):
    if hasattr(vinculo, "_permissoes_efetivas") and getattr(vinculo, "_perfil_permissoes", None) == vinculo.perfil:
        return set(vinculo._permissoes_efetivas)
    permissoes = set(MATRIZ.get(vinculo.perfil, set()))
    for ajuste in vinculo.ajustes_permissao.all():
        if ajuste.permitido:
            permissoes.add(ajuste.codigo)
        else:
            permissoes.discard(ajuste.codigo)
    if vinculo.perfil in MATRIZ:
        permissoes.add("painel.ver")
    if vinculo.perfil != "gestor":
        permissoes.discard("gestao.ver")
    for codigo in tuple(permissoes):
        consulta = codigo.removesuffix(".editar") + ".ver"
        if codigo.endswith(".editar") and consulta in PERMISSOES and consulta not in permissoes:
            permissoes.discard(codigo)
    if "relatorios.ver" not in permissoes:
        permissoes.discard("relatorios.exportar")
    if not {"sigilo.ver", "beneficios.ver"}.issubset(permissoes):
        permissoes.discard("beneficios.tecnico")
    vinculo._perfil_permissoes = vinculo.perfil
    vinculo._permissoes_efetivas = frozenset(permissoes)
    return permissoes
