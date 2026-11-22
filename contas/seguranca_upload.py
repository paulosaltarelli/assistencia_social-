"""Limites anteriores à validação CSRF e ao processamento das views."""
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler
from django.http import HttpResponse

LIMITE_REQUISICAO = 9 * 1024 * 1024
LIMITE_ARQUIVO = 8 * 1024 * 1024


class ExcessoUpload(Exception):
    pass


class FluxoLimitado:
    def __init__(self, fluxo):
        self.fluxo = fluxo
        self.lidos = 0

    def _contar(self, dados):
        self.lidos += len(dados)
        if self.lidos > LIMITE_REQUISICAO:
            raise ExcessoUpload()
        return dados

    def read(self, tamanho=-1):
        restante = LIMITE_REQUISICAO - self.lidos + 1
        tamanho = restante if tamanho is None or tamanho < 0 else min(tamanho, restante)
        return self._contar(self.fluxo.read(tamanho))

    def readline(self, tamanho=-1):
        restante = LIMITE_REQUISICAO - self.lidos + 1
        tamanho = restante if tamanho is None or tamanho < 0 else min(tamanho, restante)
        return self._contar(self.fluxo.readline(tamanho))

    def close(self):
        self.fluxo.close()


class LimitarArquivo(FileUploadHandler):
    """Conta bytes reais sem confiar no tamanho declarado de cada arquivo."""
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.recebidos = 0
        if self.content_length and self.content_length > LIMITE_ARQUIVO:
            raise ExcessoUpload()

    def receive_data_chunk(self, raw_data, start):
        self.recebidos += len(raw_data)
        if self.recebidos > LIMITE_ARQUIVO:
            raise ExcessoUpload()
        return raw_data

    def file_complete(self, file_size):
        return None


class LimitarUploadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in {"POST", "PUT", "PATCH"}:
            return self.get_response(request)
        try:
            declarado = int(request.META.get("CONTENT_LENGTH") or 0)
        except (ValueError, TypeError):
            return HttpResponse("Tamanho da requisição inválido.", status=400)
        if declarado < 0:
            return HttpResponse("Tamanho da requisição inválido.", status=400)
        if declarado > LIMITE_REQUISICAO:
            return self.recusar(request)
        request._stream = FluxoLimitado(request._stream)
        try:
            # O parser precisa ser executado aqui para devolver 413 antes do CSRF.
            # Arquivos ficam sujeitos aos handlers e limites normais do Django.
            if request.method == "POST" and request.content_type in {
                "multipart/form-data", "application/x-www-form-urlencoded",
            }:
                request.POST
        except (ExcessoUpload, RequestDataTooBig):
            return self.recusar(request)
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, (ExcessoUpload, RequestDataTooBig)):
            return self.recusar(request)
        return None

    @staticmethod
    def recusar(request):
        for handler in getattr(request, "_upload_handlers", []):
            arquivo = getattr(handler, "file", None)
            if arquivo:
                arquivo.close()
        return HttpResponse("Arquivo ou requisição acima do tamanho permitido.", status=413)
