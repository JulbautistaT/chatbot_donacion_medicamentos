import csv
import os
from django.core.management.base import BaseCommand, CommandError
from stock.models import Medicamento


class Command(BaseCommand):
    help = 'Carga medicamentos desde un archivo CSV'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_path',
            type=str,
            help='Ruta al archivo CSV',
        )
        parser.add_argument(
            '--limpiar',
            action='store_true',
            help='Elimina todos los medicamentos antes de cargar',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']

        if not os.path.exists(csv_path):
            raise CommandError(f'No se encontró el archivo: {csv_path}')

        if options['limpiar']:
            self.stdout.write(self.style.WARNING('Eliminando medicamentos existentes...'))
            Medicamento.objects.all().delete()
            self.stdout.write(self.style.WARNING('Limpieza completada.'))

        creados = 0
        existentes = 0
        omitidos = 0
        errores = 0

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for i, row in enumerate(reader, start=2):
                try:
                    nombre = row.get('Principio activo', '').strip()
                    concentracion = row.get('Concentración', '').strip()

                    if not nombre:
                        self.stdout.write(self.style.WARNING(f'Fila {i}: nombre vacío, omitida.'))
                        omitidos += 1
                        continue

                    # evitar duplicados
                    medicamento, creado = Medicamento.objects.get_or_create(
                        nombre_comercial=nombre,
                        concentracion=concentracion
                    )

                    if creado:
                        creados += 1
                    else:
                        existentes += 1

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Fila {i}: error - {e}'))
                    errores += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nCarga finalizada:\n'
            f'- Nuevos: {creados}\n'
            f'- Ya existentes: {existentes}\n'
            f'- Omitidos: {omitidos}\n'
            f'- Errores: {errores}'
        ))