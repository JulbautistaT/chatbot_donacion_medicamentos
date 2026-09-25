from django.conf import settings
from storages.backends.s3 import S3Storage


class ProtectedS3Storage(S3Storage):
    """S3/R2 privado: las URLs apuntan a la vista protegida de la app, nunca al bucket."""

    def url(self, name, parameters=None, expire=None, http_method=None):
        return settings.MEDIA_URL + name.lstrip('/')
