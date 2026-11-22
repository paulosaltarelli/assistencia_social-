"""Contagens territoriais autorizadas e leitura de malhas públicas verificadas.

Nenhum endereço de cidadão é geocodificado. Uma malha só é utilizada quando o
tenant está vinculado explicitamente ao código oficial no ambiente.
"""
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.templatetags.static import static
from PIL import Image

from atendimentos.models import Atendimento
from contas.permissoes import permissoes_efetivas
from programas.models import ConcessaoVale, PedidoMaterial, SolicitacaoBeneficio


DADOS = Path(__file__).resolve().parents[1] / "cadastros" / "dados"
CATALOGO = DADOS / "catalogo_santa_cruz_de_minas.json"
VIAS_DADOS = Path(__file__).resolve().parent / "static" / "relatorios" / "geografia"


def limites_validos(bounds):
    if not isinstance(bounds, list) or len(bounds) != 4:
        return False
    if any(isinstance(valor, bool) or not isinstance(valor, (float, int)) or not math.isfinite(valor) for valor in bounds):
        return False
    oeste, sul, leste, norte = bounds
    return -180 <= oeste < leste <= 180 and -90 <= sul < norte <= 90


def carregar_satelite(codigo, limite_sha256):
    try:
        dados = json.loads((DADOS / "satelite_santa_cruz_de_minas.json").read_text(encoding="utf-8"))
        if str(dados["codigo_ibge"]) != codigo or not limites_validos(dados["bounds"]):
            return None
        if dados.get("crs_imagem") != "EPSG:3857" or dados.get("bounds_crs") != "EPSG:4326":
            return None
        qualidade = dados.get("qualidade", {})
        if qualidade.get("cobertura_contorno_referencia") is not True or qualidade.get("limite_referencia_sha256") != limite_sha256:
            return None
        arquivo_static = dados["arquivo_static"]
        caminho = PurePosixPath(arquivo_static)
        if caminho.is_absolute() or ".." in caminho.parts or caminho.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            return None
        arquivo = find(arquivo_static)
        if not arquivo or Path(arquivo).stat().st_size > 25_000_000:
            return None
        if hashlib.sha256(Path(arquivo).read_bytes()).hexdigest() != dados["sha256"]:
            return None
        with Image.open(arquivo) as imagem:
            if imagem.format not in {"JPEG", "PNG"} or imagem.size != (dados["largura"], dados["altura"]):
                return None
            imagem.verify()
        date.fromisoformat(dados["data_captura"][:10])
        if not dados.get("credito") or not dados.get("fonte") or not dados.get("url", "").startswith("https://"):
            return None
        return {chave: dados[chave] for chave in [
            "arquivo_static", "bounds", "credito", "fonte", "url", "data_captura", "licenca", "licenca_url",
            "crs_imagem", "resolucao_origem_metros", "sha256",
        ]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def carregar_vias(codigo, limite_sha256):
    try:
        meta = json.loads((VIAS_DADOS / f"{codigo}-vias.origem.json").read_text(encoding="utf-8"))
        if str(meta["codigo_ibge"]) != codigo or meta.get("sha256_limite") != limite_sha256:
            return {}
        arquivo = VIAS_DADOS / f"{codigo}-vias.geojson"
        if arquivo.stat().st_size > 5_000_000:
            return {}
        conteudo = arquivo.read_bytes()
        if hashlib.sha256(conteudo).hexdigest() != meta["sha256_geojson"]:
            return {}
        dados = json.loads(conteudo)
        if dados.get("type") != "FeatureCollection" or not isinstance(dados.get("features"), list):
            return {}
        for feature in dados["features"]:
            props = feature.get("properties", {})
            geometria = feature.get("geometry", {})
            if not isinstance(props, dict) or set(props) - {"nome", "classe"}:
                return {}
            if geometria.get("type") not in {"LineString", "MultiLineString"}:
                return {}
            linhas = [geometria.get("coordinates")] if geometria["type"] == "LineString" else geometria.get("coordinates")
            if not isinstance(linhas, list) or not linhas:
                return {}
            for linha in linhas:
                if not isinstance(linha, list) or len(linha) < 2:
                    return {}
                for ponto in linha:
                    if not isinstance(ponto, list) or len(ponto) != 2:
                        return {}
                    x, y = ponto
                    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in ponto):
                        return {}
                    if not -180 <= x <= 180 or not -90 <= y <= 90:
                        return {}
        return {"vias_url": static(f"relatorios/geografia/{codigo}-vias.geojson"),
                "vias_credito": meta["credito"], "vias_fonte": meta["url"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def normalizar(valor):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(valor)) if not unicodedata.combining(c)).casefold().split())


def coordenadas_validas(geometria):
    if not isinstance(geometria, dict) or geometria.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    poligonos = geometria.get("coordinates")
    if geometria["type"] == "Polygon":
        poligonos = [poligonos]
    total = 0
    if not isinstance(poligonos, list) or not poligonos:
        return False
    for poligono in poligonos:
        if not isinstance(poligono, list) or not poligono:
            return False
        for anel in poligono:
            if not isinstance(anel, list) or len(anel) < 4 or anel[0] != anel[-1]:
                return False
            for ponto in anel:
                if not isinstance(ponto, list) or len(ponto) < 2:
                    return False
                x, y = ponto[:2]
                if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    return False
                if not math.isfinite(x) or not math.isfinite(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
                    return False
                total += 1
                if total > 100000:
                    return False
    return True


def ponto_no_contorno(longitude, latitude, features):
    def em_anel(anel):
        dentro = False
        anterior = anel[-1]
        for atual in anel:
            x1, y1 = anterior[:2]
            x2, y2 = atual[:2]
            if (y1 > latitude) != (y2 > latitude):
                cruzamento = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
                if longitude < cruzamento:
                    dentro = not dentro
            anterior = atual
        return dentro

    for feature in features:
        if feature["properties"]["tipo"] != "municipio":
            continue
        geometria = feature["geometry"]
        poligonos = [geometria["coordinates"]] if geometria["type"] == "Polygon" else geometria["coordinates"]
        for poligono in poligonos:
            if em_anel(poligono[0]) and not any(em_anel(anel) for anel in poligono[1:]):
                return True
    return False


def referencias_verificadas(dados, codigo, features):
    referencias = []
    fontes = {fonte["id"]: fonte for fonte in dados.get("fontes", []) if isinstance(fonte, dict) and fonte.get("id")}
    for ponto in dados.get("referencias_localidades", []):
        if not isinstance(ponto, dict) or ponto.get("estado") != "verificado_agregado" or str(ponto.get("codigo_ibge")) != codigo:
            continue
        quantidade = ponto.get("coordenadas_distintas")
        x, y = ponto.get("longitude"), ponto.get("latitude")
        fonte = fontes.get(ponto.get("fonte_id"), {})
        if not ponto.get("nome") or not fonte.get("url", "").startswith("https://"):
            continue
        if not fonte.get("consultado_em") or not re.fullmatch(r"[0-9a-f]{64}", fonte.get("sha256_arquivo_origem", "")):
            continue
        if isinstance(quantidade, bool) or not isinstance(quantidade, int) or quantidade < 10:
            continue
        if any(isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) for valor in (x, y)):
            continue
        if not -180 <= x <= 180 or not -90 <= y <= 90 or not ponto_no_contorno(x, y, features):
            continue
        aliases = ponto.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            continue
        referencias.append({"nome": str(ponto["nome"]), "aliases": aliases,
            "longitude": x, "latitude": y, "coordenadas_distintas": quantidade,
            "metodo": str(ponto.get("metodo", "centro_amostral")), "fonte": fonte})
    return sorted(referencias, key=lambda item: normalizar(item["nome"]))


def carregar_malha(municipio):
    mapeamento = getattr(settings, "SOCIAL_MUNICIPIOS_GEOGRAFICOS", {})
    codigo = str(mapeamento.get(str(municipio.pk), "")) if isinstance(mapeamento, dict) else ""
    vazio = {"geometria": None, "fonte": None, "referencias": [], "lacuna": "O vínculo deste município com o catálogo geográfico está pendente de configuração."}
    if not re.fullmatch(r"\d{7}", codigo):
        return vazio
    try:
        dados = json.loads(CATALOGO.read_text(encoding="utf-8"))
        if str(dados["municipio"]["codigo_ibge"]) != codigo:
            return {**vazio, "lacuna": "O catálogo disponível pertence a outro código municipal."}
        limite = dados["limite_municipal"]
        if limite.get("estado") != "verificado":
            return {**vazio, "lacuna": "O limite municipal aguarda conferência da fonte geográfica."}
        arquivo = (DADOS / limite["arquivo"]).resolve()
        if DADOS.resolve() not in arquivo.parents or arquivo.stat().st_size > 5_000_000:
            raise ValueError("Arquivo geográfico inválido.")
        conteudo = arquivo.read_bytes()
        if not limite.get("sha256") or hashlib.sha256(conteudo).hexdigest() != limite["sha256"]:
            raise ValueError("Hash da malha não confere.")
        geometria = json.loads(conteudo)
        if geometria.get("type") != "FeatureCollection" or not isinstance(geometria.get("features"), list):
            raise ValueError("GeoJSON incompatível.")
        features = []
        for feature in geometria["features"]:
            props = feature.get("properties", {})
            if str(props.get("codigo_ibge", "")) != codigo or props.get("tipo") not in {"municipio", "bairro", "territorio"}:
                continue
            if not coordenadas_validas(feature.get("geometry")):
                raise ValueError("Coordenadas inválidas.")
            features.append({"type": "Feature", "id": str(feature.get("id", "")),
                "geometry": feature["geometry"], "properties": {
                    "nome": str(props.get("nome", "")), "tipo": props["tipo"], "codigo_ibge": codigo,
                }})
        if not any(f["properties"]["tipo"] == "municipio" for f in features):
            raise ValueError("Contorno municipal ausente.")
        fonte = dados["proveniencia"]
        if not str(fonte.get("url", "")).startswith("https://") or not fonte.get("consultado_em"):
            raise ValueError("Proveniência incompleta.")
        features.sort(key=lambda feature: (feature["properties"]["tipo"] != "municipio", feature["properties"]["nome"]))
        referencia = next((item for item in dados.get("fontes", []) if item.get("id") == limite.get("fonte_id")), {})
        return {"geometria": {"type": "FeatureCollection", "features": features}, "fonte": fonte,
                "referencias": referencias_verificadas(dados, codigo, features),
                "satelite": carregar_satelite(codigo, limite["sha256"]),
                **carregar_vias(codigo, limite["sha256"]),
                "nota_fonte": referencia.get("observacao", ""),
                "lacuna": "Localidades sem delimitação geográfica conferida permanecem na tabela."}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {**vazio, "lacuna": "A malha territorial ainda está indisponível ou sua integridade não pôde ser conferida."}


def agrupar(consulta, municipio, familia):
    complemento = familia + "__complemento"
    pertence = Q(**{familia + "__municipio": municipio, complemento + "__municipio": municipio})
    dados = consulta.order_by().annotate(
        bairro_mapa=Case(When(pertence, then=F(complemento + "__bairro")), default=Value(""), output_field=CharField()),
        territorio_mapa=Case(When(pertence, then=F(complemento + "__territorio")), default=Value(""), output_field=CharField()),
    ).values("bairro_mapa", "territorio_mapa").annotate(total=Count("pk"))
    return [(str(row["bairro_mapa"] or "").strip(), str(row["territorio_mapa"] or "").strip(), row["total"]) for row in dados]


def associar_localidades(linhas, referencias, possui_atendimentos):
    pontos = []
    candidatos = {}
    for indice, referencia in enumerate(referencias):
        pontos.append({"nome": referencia["nome"], "longitude": referencia["longitude"], "latitude": referencia["latitude"],
            "amostra": referencia["coordenadas_distintas"], "metodo": referencia["metodo"],
            "atendimentos": 0 if possui_atendimentos else None, "demandas": 0})
        for nome in {referencia["nome"], *referencia["aliases"]}:
            candidatos.setdefault(normalizar(nome), set()).add(indice)
    for linha in linhas:
        encontrados = candidatos.get(normalizar(linha["bairro"]), set()) if linha["bairro_informado"] else set()
        linha["referencia_mapa"] = ""
        if len(encontrados) == 1:
            indice = next(iter(encontrados))
            ponto = pontos[indice]
            ponto["demandas"] += linha["demandas"]
            if possui_atendimentos:
                ponto["atendimentos"] += linha["atendimentos"]
            linha["referencia_mapa"] = ponto["nome"]
    return pontos


def resumo_territorial(municipio, vinculo, direitos=None, hoje=None):
    if vinculo.municipio_id != municipio.pk or not vinculo.usuario.is_active:
        return {"disponivel": False}
    direitos = set(direitos if direitos is not None else permissoes_efetivas(vinculo))
    if not direitos.intersection({"atendimentos.ver", "beneficios.ver", "materiais.ver", "vale.ver"}):
        return {"disponivel": False}
    hoje = hoje or timezone.localdate()
    indice = hoje.year * 12 + hoje.month - 6
    inicio = date(indice // 12, indice % 12 + 1, 1)
    grupos = {}
    fontes_pendentes = Counter()
    possui_atendimentos = "atendimentos.ver" in direitos

    def incluir(consulta, caminho, metrica, fonte=None):
        for bairro, territorio, total in agrupar(consulta, municipio, caminho):
            chave = (bairro, territorio)
            if chave not in grupos:
                grupos[chave] = {"bairro": bairro or "Bairro não informado", "territorio": territorio or "Território não informado",
                    "bairro_informado": bool(bairro), "territorio_informado": bool(territorio),
                    "atendimentos": 0 if possui_atendimentos else None, "demandas": 0, "componentes": Counter()}
            grupos[chave][metrica] += total
            if fonte:
                grupos[chave]["componentes"][fonte] += total
                fontes_pendentes[fonte] += total

    if possui_atendimentos:
        atendimentos = Atendimento.objects.filter(municipio=municipio)
        if "sigilo.ver" not in direitos:
            atendimentos = atendimentos.exclude(acompanhamento__sigiloso=True)
        periodo = atendimentos.annotate(data_mapa=Coalesce("acompanhamento__data_efetiva", "criado")).filter(
            data_mapa__date__gte=inicio, data_mapa__date__lte=hoje)
        incluir(periodo, "cidadao__familia", "atendimentos")
        incluir(atendimentos.filter(acompanhamento__situacao__in=["aberto", "aguarda"]),
            "cidadao__familia", "demandas", "Acompanhamentos em aberto")
    for modelo, permissao, filtro, fonte in [
        (SolicitacaoBeneficio, "beneficios.ver", Q(situacao__in=["solicitado", "analise"]), "Benefícios aguardando análise"),
        (PedidoMaterial, "materiais.ver", Q(situacao__in=["solicitado", "analise", "disponibilidade"]) | Q(situacao__in=["aprovado", "parcial"], entregue__lt=F("quantidade_aprovada")), "Solicitações de material pendentes"),
        (ConcessaoVale, "vale.ver", Q(situacao="analise"), "Vale-Alimentação aguardando análise"),
    ]:
        if permissao in direitos:
            incluir(modelo.objects.filter(filtro, municipio=municipio), "familia", "demandas", fonte)
    linhas = sorted(grupos.values(), key=lambda row: (normalizar(row["territorio"]), normalizar(row["bairro"])))
    for row in linhas:
        row["componentes"] = dict(row["componentes"])
    totais = {"atendimentos": sum(row["atendimentos"] or 0 for row in linhas) if possui_atendimentos else None,
              "demandas": sum(row["demandas"] for row in linhas)}
    malha = carregar_malha(municipio)
    referencias = malha.pop("referencias", [])
    fontes_referencias = {item["fonte"]["id"]: item["fonte"] for item in referencias}
    pontos = associar_localidades(linhas, referencias, possui_atendimentos)
    mapeados = {"atendimentos": sum(p["atendimentos"] or 0 for p in pontos) if possui_atendimentos else None,
                "demandas": sum(p["demandas"] for p in pontos)}
    return {"disponivel": True, "municipio": municipio.nome, "inicio": inicio, "fim": hoje,
        "linhas": linhas, "totais": totais, "componentes": dict(fontes_pendentes),
        "pontos": pontos, "mapeados": mapeados,
        "fontes_referencias": list(fontes_referencias.values()),
        "sem_ponto": {"atendimentos": totais["atendimentos"] - mapeados["atendimentos"] if possui_atendimentos else None,
                      "demandas": totais["demandas"] - mapeados["demandas"]},
        "possui_atendimentos": possui_atendimentos, **malha}
