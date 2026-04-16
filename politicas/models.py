from django.db import models
from django.utils import timezone
from datetime import date

class PoliticaDatos(models.Model):
    version = models.CharField(max_length=10, unique=True)
    titulo = models.CharField(max_length=200)
    contenido_html = models.TextField()  
    fecha_vigencia = models.DateField()
    fecha_creacion = models.DateTimeField(default=timezone.now)
    es_activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['-fecha_vigencia']

    def __str__(self):
        return f"Política v{self.version} ({self.fecha_vigencia})"

class AceptacionPolitica(models.Model):
    telegram_chat_id = models.CharField(max_length=50, unique=True)
    politica = models.ForeignKey(PoliticaDatos, on_delete=models.PROTECT)
    fecha_consentimiento = models.DateField(default=date.today)
    hora_consentimiento = models.TimeField(null=True, blank=True)
    acepto = models.BooleanField(default=True)
    fecha_hora_completa = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-fecha_hora_completa']

    def __str__(self):
        return f"{self.telegram_chat_id} aceptó v{self.politica.version}"
