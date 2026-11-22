"""Recebimento de documentos privados. O original verificado é preservado integralmente."""
import hashlib
import io
import os
import re
import socket
import struct
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath

from defusedxml import ElementTree
from django.core.exceptions import ValidationError
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject


LIMITE = 8 * 1024 * 1024
TIPOS = {".pdf": "application/pdf", ".xml": "application/xml", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".png": "image/png"}


class ScannerIndisponivel(ValidationError):
    pass


@dataclass(frozen=True)
class Original:
    nome: str
    mime: str
    dados: bytes
    sha256: str


def resposta_clamd(scanner):
    resposta = bytearray()
    while b"\x00" not in resposta and len(resposta) < 2048:
        bloco = scanner.recv(512)
        if not bloco:
            break
        resposta.extend(bloco)
    return bytes(resposta)


def verificar_assinaturas(endereco, espera):
    with socket.create_connection(endereco, timeout=espera) as consulta:
        consulta.sendall(b"zVERSION\x00")
        resposta = resposta_clamd(consulta)
    formato = re.fullmatch(rb"ClamAV [^/\x00]{1,80}/[0-9]+/([^\x00]{12,45})\x00", resposta)
    if not formato:
        raise ScannerIndisponivel("A versão das assinaturas de segurança não pôde ser confirmada.")
    try:
        data = parsedate_to_datetime(formato[1].decode("ascii"))
        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
    except (ValueError, UnicodeError, TypeError, OverflowError) as erro:
        raise ScannerIndisponivel("A data das assinaturas de segurança não pôde ser confirmada.") from erro
    idade = datetime.now(timezone.utc) - data
    if idade < -timedelta(days=1) or idade > timedelta(days=14):
        raise ScannerIndisponivel("A atualização das assinaturas de segurança está pendente. Tente novamente mais tarde.")


def verificar_antivirus(dados):
    host = os.environ.get("SOCIAL_CLAMAV_HOST", "social-antivirus")
    try:
        porta = int(os.environ.get("SOCIAL_CLAMAV_PORT", "3310"))
        espera = float(os.environ.get("SOCIAL_CLAMAV_TIMEOUT", "20"))
        endereco = (host, porta)
        verificar_assinaturas(endereco, espera)
        with socket.create_connection(endereco, timeout=espera) as scanner:
            scanner.settimeout(espera)
            scanner.sendall(b"zINSTREAM\x00")
            for inicio in range(0, len(dados), 65536):
                bloco = dados[inicio:inicio + 65536]
                scanner.sendall(struct.pack("!I", len(bloco)) + bloco)
            scanner.sendall(b"\x00\x00\x00\x00")
            resposta = resposta_clamd(scanner)
    except (OSError, ValueError) as erro:
        raise ScannerIndisponivel("Verificação de segurança indisponível. Tente novamente mais tarde.") from erro
    if resposta == b"stream: OK\x00":
        return
    if resposta.strip(b"\x00\r\n").endswith(b" FOUND"):
        raise ValidationError("O arquivo foi recusado na verificação de segurança.")
    raise ScannerIndisponivel("A verificação de segurança não foi concluída. Tente novamente mais tarde.")


def verificar_pdf(dados):
    if not dados.startswith(b"%PDF-"):
        raise ValueError("formato")
    reader = PdfReader(io.BytesIO(dados), strict=True)
    if reader.is_encrypted:
        raise ValidationError("Envie um PDF sem senha para permitir a conferência.")
    pilha = [reader.trailer["/Root"]]
    visitados = set()
    vistos = 0
    while pilha:
        atual = pilha.pop()
        vistos += 1
        if vistos > 150000:
            raise ValidationError("O PDF é complexo demais para conferência. Divida-o em documentos menores.")
        if isinstance(atual, IndirectObject):
            chave = (atual.idnum, atual.generation)
            if chave in visitados:
                continue
            visitados.add(chave)
            atual = atual.get_object()
        if isinstance(atual, DictionaryObject):
            if any(k in atual for k in ("/AA", "/JavaScript", "/JS", "/EmbeddedFiles", "/XFA", "/RichMediaContent", "/EF")):
                raise ValidationError("Envie um PDF sem anexos internos ou conteúdo ativo.")
            if atual.get("/S") in ("/JavaScript", "/Launch", "/GoToR", "/GoToE", "/SubmitForm", "/ImportData", "/Rendition"):
                raise ValidationError("Envie um PDF sem ações executáveis.")
            pilha.extend(atual.values())
        elif isinstance(atual, ArrayObject):
            pilha.extend(atual)
    if not reader.pages:
        raise ValueError("sem páginas")


def verificar_imagem(mime, dados):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(dados)) as imagem:
            formato = "PNG" if mime == "image/png" else "JPEG"
            if imagem.format != formato or imagem.width * imagem.height > 20000000 or getattr(imagem, "n_frames", 1) != 1:
                raise ValueError("formato ou dimensões")
            imagem.verify()
        with Image.open(io.BytesIO(dados)) as imagem:
            imagem.load()


def receber(arquivo):
    if not arquivo or not 0 < arquivo.size <= LIMITE:
        raise ValidationError("Selecione um arquivo de até 8 MiB.")
    nome = PurePosixPath(arquivo.name.replace(chr(92), "/")).name
    nome = unicodedata.normalize("NFKC", nome)
    nome = "".join(c for c in nome if not unicodedata.category(c).startswith("C"))
    nome = re.sub(r"[^\w .()-]", "_", nome).strip(" .")
    extensao = PurePosixPath(nome).suffix.lower()
    mime = TIPOS.get(extensao)
    if not mime:
        raise ValidationError("Selecione um PDF, XML, JPG ou PNG.")
    nome = PurePosixPath(nome).stem[:140] + extensao
    dados = arquivo.read(LIMITE + 1)
    if len(dados) != arquivo.size or len(dados) > LIMITE:
        raise ValidationError("O envio excede o limite ou ficou incompleto.")
    verificar_antivirus(dados)
    try:
        if mime == "application/pdf":
            verificar_pdf(dados)
        elif mime == "application/xml":
            ElementTree.fromstring(dados, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        else:
            verificar_imagem(mime, dados)
    except ValidationError:
        raise
    except Exception as erro:
        # As bibliotecas expõem erros específicos conforme o tipo de documento.
        # Nenhuma mensagem de parser, caminho ou amostra é enviada ao usuário.
        raise ValidationError("Não foi possível validar o conteúdo do arquivo no formato informado.") from erro
    return Original(nome, mime, dados, hashlib.sha256(dados).hexdigest())
