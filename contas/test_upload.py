from io import BytesIO
from unittest.mock import Mock
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from .seguranca_upload import (
    ExcessoUpload, FluxoLimitado, LimitarArquivo, LimitarUploadMiddleware,
    LIMITE_ARQUIVO, LIMITE_REQUISICAO,
)

HANDLERS = [
    'contas.seguranca_upload.LimitarArquivo',
    'django.core.files.uploadhandler.MemoryFileUploadHandler',
    'django.core.files.uploadhandler.TemporaryFileUploadHandler',
]


@override_settings(FILE_UPLOAD_HANDLERS=HANDLERS)
class LimitesUploadTests(SimpleTestCase):
    def test_total_superior_nove_mib_recusado_antes_da_leitura(self):
        request = RequestFactory().post('/documentos/', data={})
        request.META['CONTENT_LENGTH'] = str(LIMITE_REQUISICAO + 1)
        request._stream = Mock()
        view = Mock(return_value=HttpResponse('view'))
        resposta = LimitarUploadMiddleware(view)(request)
        self.assertEqual(resposta.status_code, 413)
        request._stream.read.assert_not_called()
        view.assert_not_called()

    def test_parte_sem_tamanho_declarado_limita_bytes_reais(self):
        handler = LimitarArquivo()
        handler.new_file('arquivo', 'ficticio.bin', 'application/octet-stream', None, None)
        bloco = b'x' * 65536
        for indice in range(LIMITE_ARQUIVO // len(bloco)):
            self.assertEqual(handler.receive_data_chunk(bloco, indice * len(bloco)), bloco)
        with self.assertRaises(ExcessoUpload):
            handler.receive_data_chunk(b'x', LIMITE_ARQUIVO)

    def test_multipart_acima_oito_mib_recusado_antes_da_view(self):
        request = RequestFactory().post('/documentos/', {'arquivo': SimpleUploadedFile('ficticio.bin', b'x' * (LIMITE_ARQUIVO + 1))})
        view = Mock(return_value=HttpResponse('view'))
        resposta = LimitarUploadMiddleware(view)(request)
        self.assertEqual(resposta.status_code, 413)
        view.assert_not_called()
        for handler in request.upload_handlers:
            if hasattr(handler, 'file'):
                self.assertTrue(handler.file.closed)

    def test_arquivo_permitido_chega_a_view(self):
        request = RequestFactory().post('/documentos/', {'arquivo': SimpleUploadedFile('ficticio.txt', b'conteudo ficticio')})
        resposta = LimitarUploadMiddleware(lambda req: HttpResponse(req.FILES['arquivo'].read()))(request)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.content, b'conteudo ficticio')

    def test_stream_bruto_sem_tamanho_declarado_tem_limite_total(self):
        fluxo = FluxoLimitado(BytesIO(b'x' * (LIMITE_REQUISICAO + 1)))
        with self.assertRaises(ExcessoUpload):
            fluxo.read()
