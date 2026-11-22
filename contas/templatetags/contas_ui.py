"""Apresentação da matriz de permissões, sem decisão de autorização."""
from django import template
from contas.permissoes import DELEGACOES, MATRIZ, PERMISSOES

register = template.Library()

MODULOS = {
    "cadastros": "Pessoas e famílias",
    "atendimentos": "Atendimentos",
    "beneficios": "Benefícios eventuais",
    "materiais": "Materiais e estoque",
    "vale": "Vale-Alimentação",
    "financeiro": "Financeiro",
    "gestao": "Painel exclusivo do gestor",
    "documentos": "Documentos",
    "relatorios": "Relatórios",
    "sigilo": "Registros técnicos sigilosos",
    "contas": "Equipe e acessos",
    "configuracao": "Dados da Secretaria",
}


@register.simple_tag
def grupos_acesso(form):
    perfil = form["perfil"].value()
    incluidos = MATRIZ.get(perfil, set())
    permitir = set(form["permitir"].value() or [])
    negar = set(form["negar"].value() or [])
    grupos = []
    for modulo, titulo in MODULOS.items():
        linhas = []
        for codigo, nome in PERMISSOES.items():
            if codigo.split(".")[0] != modulo or codigo in DELEGACOES or codigo == "painel.ver":
                continue
            linhas.append({
                "codigo": codigo, "nome": nome,
                "incluido": codigo in incluidos,
                "permitido": codigo in permitir, "negado": codigo in negar,
            })
        if linhas:
            grupos.append({"modulo": modulo, "titulo": titulo, "linhas": linhas})
    return grupos


@register.simple_tag
def matriz_de_perfis():
    return {perfil: sorted(codigos) for perfil, codigos in MATRIZ.items()}


@register.simple_tag
def resumo_equipe(profissionais):
    itens = list(profissionais)
    ativas = sum(item.usuario.is_active for item in itens)
    return {"total": len(itens), "ativas": ativas, "inativas": len(itens) - ativas}
