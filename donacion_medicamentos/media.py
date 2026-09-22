import hashlib
from django.conf import settings
from django.contrib import auth
from django.core.files.storage import default_storage
from django.http.response import FileResponse, Http404, HttpResponseForbidden
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken


def _serve_from_storage(path):
    """Sirve `path` desde el STORAGES['default'] configurado (disco local o R2/S3)."""
    if not default_storage.exists(path):
        raise Http404
    return FileResponse(default_storage.open(path, 'rb'), filename=path.rsplit('/', 1)[-1])


def protected_serve(request, path, show_indexes=False):
    """ Utility function: revisa el nombre del archivo pedido para ver si es del usuario o no.
        El proceso de validación de propiedad del archivo se hace consultando la primera parte
        de la ruta del archivo <hashmd5> para compararlo con el hashm de md5("request.user.pk").
        
        Si el archivo pedido es del usuario lo retorna, de lo contrario entrega una respuesta 403
        con un diccionario vacio.

        Keywords arguments:
        kwargs['filename'] -- nombre del archivo pedido.
                            Ej.  <hashmd5>/<_keyFernet>.[jpeg|png|pdf]
    
    """
    filename = path.strip('/')
    filename_list = filename.split('/')

    # Archivos publicos
    hashmd5_public = hashlib.md5(settings.MEDIA_URL_PUBLIC.encode()).hexdigest()

    query_params = request.GET # QueryDict()
    if 'token' in query_params:
        try:
            UntypedToken(query_params['token'])
            decoded_data = jwt_decode(query_params['token'], settings.SECRET_KEY, algorithms=["HS256"])
            user = auth.models.User.objects.get(id=decoded_data["user_id"])

        except (InvalidToken, TokenError, auth.models.User.DoesNotExist) as e:
            user = None

    else:
        user = request.user


    if user:
        hashmd5_pk = hashlib.md5(str(user.pk).encode()).hexdigest()

        media_user = hashmd5_pk == filename_list[0]
        media_public = hashmd5_public == filename_list[0]
        # Admin access: allow staff/superuser, legacy "admin" group,
        # or explicit stock permissions granted via Django admin.
        media_user_admin = (
            user.is_staff
            or user.is_superuser
            or user.groups.filter(name="admin").exists()
            or user.has_perm("stock.view_formula")
            or user.has_perm("stock.change_formula")
            or user.has_perm("stock.view_solicitud")
            or user.has_perm("stock.change_solicitud")
        )

        if media_user or media_public or media_user_admin:
            return _serve_from_storage(path)
        else:
            return HttpResponseForbidden()
    else:
        if hashmd5_public == filename_list[0]:
            return _serve_from_storage(path)
        else:
            return HttpResponseForbidden()
