from django.db import models
from django.utils import timezone

from stock.models import DetalleSolicitud


class Anuncio(models.Model):
    medicamento = models.ForeignKey(
        'stock.Medicamento',
        on_delete= models.CASCADE,
        related_name='anuncios',
        help_text="Medicamento disponible para anunciar"
    )

    cantidad = models.PositiveIntegerField(
        help_text="Cantidad de sobres disponibles"
    )

    tipo_presentacion = models.CharField(
        verbose_name="Presentación",
        max_length=2,
        choices=DetalleSolicitud.TipoPresentacion.choices,
        null=True,
        blank=True,
        help_text='Presentación del medicamento anunciado (sobre, frasco, caja, etc.)',
    )

    notas_adicionales = models.TextField(
        blank=True,
        null=True,
        help_text='Información adicional del anuncio, como fecha de vencimiento o tiempo vigente'
    )

    fecha_anuncio = models.DateTimeField(
        default=timezone.now,
        help_text='Fecha en que se realiza el anuncio'
    )

    activo = models.BooleanField(
        default=True,
        help_text='Indica si el anuncio sigue vigente'
    )

    class Meta:
        verbose_name = 'Aviso'
        verbose_name_plural = 'Avisos'
        ordering = ['-fecha_anuncio']
    
    def __str__(self):
        return f"{self.medicamento.nombre_comercial} - {self.cantidad} sobres disponibles {self.notas_adicionales}"
    







