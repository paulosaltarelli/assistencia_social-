from functools import wraps
import uuid
from django.contrib.auth.views import redirect_to_login
from django.db import connection, transaction
from django.http import HttpResponseForbidden
from django.urls import reverse
from .models import Auditoria, Vinculo


def tem_permissao(vinculo, codigo):
    from contas.permissoes import permissoes_efetivas
    if not vinculo or not vinculo.usuario.is_active:
        return False
    return codigo in permissoes_efetivas(vinculo)


def registrar_evento(request, evento, objeto=None):
    if objeto is not None:
        objeto = getattr(objeto, "pk", objeto)
        if not isinstance(objeto, uuid.UUID):
            objeto = uuid.UUID(str(objeto))
    Auditoria.objects.create(
        municipio=request.municipio, usuario=request.user,
        evento=evento[:40], objeto=objeto,
    )


def municipal(codigo, post=None):
    def decorar(view):
        @wraps(view)
        def executar(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), reverse("contas:entrar"))
            with transaction.atomic():
                vinculo = Vinculo.objects.select_related("municipio", "usuario").filter(usuario=request.user).first()
                if not vinculo or not vinculo.usuario.is_active:
                    return HttpResponseForbidden("Acesso indisponível para esta conta.")
                request.municipio = vinculo.municipio
                request.vinculo = vinculo
                # A consulta aos ajustes RLS exige o contexto do vínculo já validado.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('social.municipio', %s, true)", [str(vinculo.municipio_id)])
                permissao = post if request.method not in {"GET", "HEAD", "OPTIONS"} and post else codigo
                if not tem_permissao(vinculo, permissao):
                    registrar_evento(request, "acesso_recusado")
                    return HttpResponseForbidden("Acesso indisponível para este perfil.")
                return view(request, *args, **kwargs)
        return executar
    return decorar
