import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Formula

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Formula)
def borrar_archivo_formula(sender, instance, **kwargs):
    """Borra el archivo de la fórmula del almacenamiento (Backblaze B2 o ./media).

    Django no borra los archivos de un FileField al eliminar el registro. Se dispara
    al borrar fórmulas directamente, con la acción masiva del admin y en cascada
    (al eliminar una solicitud o un solicitante). Se espera al commit para no
    perder el archivo si la eliminación se revierte.
    """
    archivo = instance.archivo_formula
    if not archivo:
        return
    nombre, storage = archivo.name, archivo.storage

    def _borrar():
        try:
            storage.delete(nombre)
            logger.info(f"Archivo de fórmula eliminado: {nombre}")
        except Exception as e:
            logger.warning(f"No se pudo eliminar el archivo de fórmula {nombre}: {e}")

    transaction.on_commit(_borrar)
