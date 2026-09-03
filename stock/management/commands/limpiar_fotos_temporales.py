import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from donacion_medicamentos.bot.constants import PHOTOS_CLEANUP_HOURS


class Command(BaseCommand):
    help = (
        "Elimina archivos huérfanos en BASE_DIR/photos/ con más de N horas de antigüedad. "
        "Red de seguridad para sesiones del bot que expiraron o fallaron a mitad de flujo "
        "sin que su archivo temporal llegara a borrarse."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--horas', type=float, default=PHOTOS_CLEANUP_HOURS,
            help=f'Antigüedad mínima en horas para eliminar (default: {PHOTOS_CLEANUP_HOURS}).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Solo muestra qué archivos se eliminarían, sin borrarlos.',
        )

    def handle(self, *args, **options):
        horas = options['horas']
        dry_run = options['dry_run']
        photo_dir = Path(settings.BASE_DIR) / "photos"

        if not photo_dir.exists():
            self.stdout.write(self.style.WARNING(f'No existe el directorio {photo_dir}'))
            return

        limite = time.time() - horas * 3600
        eliminados = 0
        conservados = 0

        for path in photo_dir.iterdir():
            if not path.is_file():
                continue
            if path.stat().st_mtime > limite:
                conservados += 1
                continue
            if dry_run:
                self.stdout.write(f'[dry-run] Se eliminaría: {path.name}')
            else:
                try:
                    path.unlink()
                except OSError as e:
                    self.stdout.write(self.style.ERROR(f'No se pudo eliminar {path.name}: {e}'))
                    continue
            eliminados += 1

        accion = 'a eliminar' if dry_run else 'eliminados'
        self.stdout.write(self.style.SUCCESS(
            f'\nLimpieza finalizada:\n'
            f'- Archivos {accion}: {eliminados}\n'
            f'- Archivos recientes (< {horas}h) conservados: {conservados}'
        ))
