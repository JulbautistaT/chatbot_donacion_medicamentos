from django.db import models
from django.utils import timezone


class PoliticaDatos(models.Model):
    version = models.CharField(max_length=10, unique=True)
    titulo = models.CharField(max_length=200)
    contenido_html = models.TextField()  
    fecha_vigencia = models.DateField()
    fecha_creacion = models.DateTimeField(default=timezone.now)
    es_activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['-fecha_vigencia']
        verbose_name = 'Política de datos'
        verbose_name_plural = 'Políticas de datos'

    def __str__(self):
        return f"Política v{self.version} ({self.fecha_vigencia})"