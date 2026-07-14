from django.core.exceptions import ValidationError
from django.db import models, transaction
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

    def clean(self):
        super().clean()
        if not self.es_activa and self.__es_la_unica_activa():
            raise ValidationError({
                'es_activa': (
                    "No puedes desactivar esta política: siempre debe existir al "
                    "menos una política de datos activa. Activa otra versión primero."
                )
            })

    def __es_la_unica_activa(self) -> bool:
        """True si este registro está activo en BD y ninguna otra política lo está."""
        if not self.pk:
            return False
        sigue_activa_en_bd = PoliticaDatos.objects.filter(pk=self.pk, es_activa=True).exists()
        if not sigue_activa_en_bd:
            return False
        hay_otra_activa = PoliticaDatos.objects.filter(es_activa=True).exclude(pk=self.pk).exists()
        return not hay_otra_activa

    def save(self, *args, **kwargs):
        """Solo puede haber una política activa a la vez: al activar esta, se
        desactivan automáticamente las demás (ver `desactivadas_automaticamente`,
        usado por el admin para avisar de ese efecto secundario)."""
        self.desactivadas_automaticamente = []
        if not self.es_activa:
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            otras_activas = PoliticaDatos.objects.filter(es_activa=True).exclude(pk=self.pk)
            self.desactivadas_automaticamente = list(otras_activas.values_list('version', flat=True))
            otras_activas.update(es_activa=False)
            super().save(*args, **kwargs)