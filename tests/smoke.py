"""Smoke HTTP real em ambiente de desenvolvimento com contas e dados fictícios.

Provisionar previamente seed_demo e fornecer SOCIAL_DEMO_PASSWORD no ambiente.
Executar com SOCIAL_SMOKE_URL apontando para a aplicação de desenvolvimento.
"""
import http.cookiejar
from html import unescape
from html.parser import HTMLParser
import os
import re
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request


class SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Formularios(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.formularios = []
        self.atual = None
        self.select = None
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.atual = {}
            self.formularios.append(self.atual)
        if self.atual is None:
            return
        nome = attrs.get("name")
        if tag == "input" and nome and "disabled" not in attrs:
            tipo = attrs.get("type", "text")
            if tipo not in {"checkbox", "radio", "file", "submit", "button"} or "checked" in attrs:
                self.atual[nome] = attrs.get("value", "")
        if tag == "select" and nome:
            self.select = nome
        if tag == "option" and self.select:
            if self.select not in self.atual or "selected" in attrs:
                self.atual[self.select] = attrs.get("value", "")
        if tag == "textarea" and nome:
            self.textarea = nome
            self.atual[nome] = ""

    def handle_data(self, data):
        if self.textarea and self.atual is not None:
            self.atual[self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.atual = None
        if tag == "select":
            self.select = None
        if tag == "textarea":
            self.textarea = None


class Navegador:
    def __init__(self, base):
        self.base = base.rstrip("/") + "/"
        self.cookies = http.cookiejar.CookieJar()
        handlers = [HTTPCookieProcessor(self.cookies), SemRedirecionar()]
        if urlsplit(base).hostname in {"localhost", "127.0.0.1"}:
            handlers.append(ProxyHandler({}))
        self.http = build_opener(*handlers)

    def requisicao(self, path, dados=None, esperado=200, csrf=True):
        url = urljoin(self.base, path)
        headers = {"Referer": url}
        if dados is not None:
            origem = urlsplit(self.base)
            headers["Origin"] = f"{origem.scheme}://{origem.netloc}"
            dados = dict(dados)
            if csrf:
                for cookie in self.cookies:
                    if cookie.name == "csrftoken":
                        dados["csrfmiddlewaretoken"] = cookie.value
            corpo = urlencode(dados).encode()
        else:
            corpo = None
        try:
            resposta = self.http.open(Request(url, corpo, headers), timeout=25)
        except HTTPError as erro:
            resposta = erro
        conteudo = resposta.read()
        assert resposta.code == esperado, f"{path}: esperado {esperado}, recebido {resposta.code}"
        return resposta, conteudo

    def entrar(self, usuario, senha):
        self.requisicao("/entrar/")
        resposta, _ = self.requisicao("/entrar/", {"username": usuario, "password": senha}, esperado=302)
        assert resposta.headers["Location"] == "/", "Login sem next deve abrir o painel inicial"
        self.requisicao("/")

    def formulario(self, path, campo):
        _, html = self.requisicao(path)
        return next(form for form in Formularios(html.decode()).formularios if campo in form)


def main():
    base = os.environ.get("SOCIAL_SMOKE_URL", "http://127.0.0.1:18083")
    senha = os.environ["SOCIAL_DEMO_PASSWORD"]
    marcador = "Validação fictícia " + str(uuid.uuid4())[:8]
    cliente = Navegador(base)
    _, saude = cliente.requisicao("/health/")
    assert saude == b"ok"
    cliente.requisicao("/", esperado=302)
    cliente.entrar("tecnico-a", senha)
    dados = cliente.formulario("/cadastros/familias/nova/", "referencia")
    dados.update(referencia=marcador)
    sem_csrf = dict(dados)
    sem_csrf.pop("csrfmiddlewaretoken", None)
    cliente.requisicao("/cadastros/familias/nova/", sem_csrf, esperado=403, csrf=False)
    resposta, _ = cliente.requisicao("/cadastros/familias/nova/", dados, esperado=302)
    familia_path = resposta.headers["Location"]
    familia_id = familia_path.rstrip("/").rsplit("/", 1)[1]
    _, ficha = cliente.requisicao(familia_path)
    assert marcador in ficha.decode()
    dados = cliente.formulario("/cadastros/pessoas/nova/?familia=" + familia_id, "familia_id")
    dados.update(nome="Pessoa fictícia " + marcador, familia_id=familia_id)
    resposta, _ = cliente.requisicao("/cadastros/pessoas/nova/", dados, esperado=302)
    pessoa_path = resposta.headers["Location"]
    pessoa_id = pessoa_path.rstrip("/").rsplit("/", 1)[1]
    cliente.requisicao(pessoa_path)
    dados = cliente.formulario("/cadastros/atendimentos/novo/?cidadao=" + pessoa_id, "cidadao_id")
    dados.update(cidadao_id=pessoa_id, unidade="Unidade fictícia de validação", encaminhamento=marcador, situacao="concluido")
    resposta, _ = cliente.requisicao("/cadastros/atendimentos/novo/", dados, esperado=302)
    atendimento_path = resposta.headers["Location"]
    _, ficha = cliente.requisicao(atendimento_path)
    assert marcador in ficha.decode()
    _, pesquisa = cliente.requisicao("/cadastros/atendimentos/?" + urlencode({"q": marcador}))
    assert marcador in pesquisa.decode()
    cliente.requisicao("/financeiro/", esperado=403)
    cliente.requisicao("/financeiro/gestor/", esperado=403)
    cliente.requisicao("/contas/profissionais/novo/", esperado=403)
    cliente.requisicao("/sair/", {}, esperado=302)
    cliente.requisicao("/", esperado=302)

    outro = Navegador(base)
    outro.entrar("tecnico-b", senha)
    for path in [familia_path, pessoa_path, atendimento_path]:
        outro.requisicao(path, esperado=404)
    dados = outro.formulario("/cadastros/pessoas/nova/", "familia_id")
    dados.update(nome="Registro fictício recusado", familia_id=familia_id)
    _, recusado = outro.requisicao("/cadastros/pessoas/nova/", dados)
    assert "Selecione uma família deste município" in recusado.decode()

    auditor = Navegador(base)
    auditor.entrar("auditor-a", senha)
    auditor.requisicao(atendimento_path)
    auditor.requisicao("/cadastros/familias/nova/", esperado=403)
    auditor.requisicao("/cadastros/familias/nova/", {"referencia": "Alteração fictícia recusada"}, esperado=403)
    usuario_admin = os.environ.get("SOCIAL_SMOKE_ADMIN")
    if usuario_admin:
        administrador = Navegador(base)
        administrador.entrar(usuario_admin, senha)
        nome_novo = "profissional-ficticio-" + str(uuid.uuid4())[:8]
        dados = administrador.formulario("/contas/profissionais/novo/", "username")
        dados.update(username=nome_novo, nome="Profissional fictício de validação", perfil="atendente", email="profissional@example.invalid")
        _, html = administrador.requisicao("/contas/profissionais/novo/", dados)
        link = unescape(re.search(r'<textarea[^>]*id="link-pessoal"[^>]*>(.*?)</textarea>', html.decode(), re.S)[1])
        comprovante = urlsplit(link).fragment
        novo = Navegador(base)
        dados = novo.formulario("/contas/definir-senha/", "comprovante")
        dados.update(comprovante=comprovante, new_password1=senha, new_password2=senha)
        novo.requisicao("/contas/definir-senha/", dados, esperado=302)
        _, replay = novo.requisicao("/contas/definir-senha/", dados)
        assert "Link indisponível" in replay.decode()
        novo.entrar(nome_novo, senha)
        novo.requisicao("/financeiro/", esperado=403)
        novo.requisicao("/contas/profissionais/novo/", esperado=403)
        _, lista = administrador.requisicao("/contas/")
        linhas = re.findall(r"<tr>(.*?)</tr>", lista.decode(), re.S)
        linha = next(linha for linha in linhas if nome_novo in linha)
        profissional_id = re.search(r'/contas/profissionais/(\d+)/', linha)[1]
        administrador.requisicao(f"/contas/profissionais/{profissional_id}/acao/", {"acao": "revogar"}, esperado=302)
        novo.requisicao("/", esperado=302)
        novo.entrar(nome_novo, senha)
        administrador.requisicao(f"/contas/profissionais/{profissional_id}/acao/", {"acao": "desativar"}, esperado=302)
        novo.requisicao("/", esperado=302)
        dados = administrador.formulario("/contas/profissionais/novo/", "username")
        dados.update(username="financeiro-recusado-" + str(uuid.uuid4())[:8], nome="Concessão fictícia recusada", perfil="financeiro")
        _, recusado = administrador.requisicao("/contas/profissionais/novo/", dados)
        assert "autorização específica" in recusado.decode()
        print("OK HTTP real: link pessoal de uso único, bloqueio de repetição, revogação, desativação e recusa de concessão financeira sem delegação.")
    usuario_piloto = os.environ.get("SOCIAL_SMOKE_PILOTO")
    if usuario_piloto:
        piloto = Navegador(base)
        piloto.entrar(usuario_piloto, senha)
        for path in [
            "/cadastros/", "/cadastros/familias/", "/cadastros/atendimentos/",
            "/programas/beneficios/", "/programas/beneficios/tipos/", "/programas/materiais/",
            "/programas/materiais/pedidos/", "/programas/vale/", "/financeiro/",
            "/financeiro/despesas/", "/financeiro/gestor/", "/financeiro/gestor/auditoria/",
            "/documentos/", "/documentos/prestacao-de-contas/", "/relatorios/",
            "/relatorios/alertas/", "/contas/", "/contas/secretaria/",
        ]:
            piloto.requisicao(path)
        print("OK HTTP real: páginas integradas de cadastros, benefícios, estoque, vale, financeiro, gestão, documentos, relatórios e contas.")
    print("OK HTTP real: login/logout, CSRF, família, cidadão, atendimento, busca, isolamento municipal e perfis.")


if __name__ == "__main__":
    main()
