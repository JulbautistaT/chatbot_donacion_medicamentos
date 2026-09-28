import shutil
import tempfile

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from .models import Formula, Solicitante, Solicitud

MEDIA_TMP = tempfile.mkdtemp()


@override_settings(
    MEDIA_ROOT=MEDIA_TMP,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class BorradoArchivoFormulaTests(TestCase):
    """Al eliminar una fórmula (directa o en cascada) se borra su archivo del almacenamiento."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    def _crear_formula(self, documento):
        solicitante = Solicitante.objects.create(nombre='Prueba', documento=documento)
        solicitud = Solicitud.objects.create(solicitante=solicitante)
        formula = Formula.objects.create(solicitud=solicitud)
        formula.archivo_formula.save('prueba.jpg', ContentFile(b'img'))
        return formula

    def test_borrar_formula(self):
        formula = self._crear_formula('1')
        nombre = formula.archivo_formula.name
        self.assertTrue(default_storage.exists(nombre))
        with self.captureOnCommitCallbacks(execute=True):
            formula.delete()
        self.assertFalse(default_storage.exists(nombre))

    def test_accion_masiva_del_admin(self):
        nombres = [self._crear_formula(doc).archivo_formula.name for doc in ('2', '3')]
        with self.captureOnCommitCallbacks(execute=True):
            Formula.objects.all().delete()
        for nombre in nombres:
            self.assertFalse(default_storage.exists(nombre))

    def test_borrar_solicitud_en_cascada(self):
        formula = self._crear_formula('4')
        nombre = formula.archivo_formula.name
        with self.captureOnCommitCallbacks(execute=True):
            formula.solicitud.delete()
        self.assertFalse(default_storage.exists(nombre))
