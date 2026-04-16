import csv
import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from stock.models import Donante, Donacion, Medicamento, MedicamentoDonado


DONANTE_NOMBRE = 'Inventario Inicial'
LOTE_DEFAULT = 'LOTE-INICIAL'
FECHA_VENCIMIENTO_DEFAULT = date(2099, 12, 31)


class Command(BaseCommand):
    help = 'Carga el inventario de medicamentos desde un archivo CSV'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_path',
            type=str,
            help='Ruta al archivo CSV del inventario',
        )
        parser.add_argument(
            '--limpiar',
            action='store_true',
            help='Elimina todos los medicamentos y stock existente antes de cargar',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']

        if not os.path.exists(csv_path):
            raise CommandError(f'No se encontró el archivo: {csv_path}')

        if options['limpiar']:
            self.stdout.write(self.style.WARNING('Eliminando medicamentos y stock existente...'))
            MedicamentoDonado.objects.all().delete()
            Medicamento.objects.all().delete()
            self.stdout.write(self.style.WARNING('Limpieza completada.'))

        # Obtener o crear el donante de inventario inicial
        donante, _ = Donante.objects.get_or_create(
            nombre=DONANTE_NOMBRE,
            defaults={
                'tipo_donante': Donante.TipoDonante.ORGANIZACION,
                'verificado': True,
            }
        )

        # Crear una donación para este inventario
        donacion = Donacion.objects.create(
            donante=donante,
            observaciones='Carga inicial de inventario desde CSV',
        )

        creados = 0
        omitidos = 0
        errores = 0

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=2):  # start=2 porque fila 1 es encabezado
                try:
                    nombre = row.get('Principio activo', '').strip()
                    concentracion = row.get('Concentración', '').strip()
                    presentacion = row.get('Presentación ', '').strip() or row.get('Presentación', '').strip()
                    almacenamiento = row.get('Almacenamiento', '').strip()
                    cantidad_str = row.get('Cantidad', '0').strip()

                    if not nombre:
                        self.stdout.write(self.style.WARNING(f'  Fila {i}: nombre vacío, omitida.'))
                        omitidos += 1
                        continue

                    try:
                        cantidad = int(cantidad_str)
                    except ValueError:
                        self.stdout.write(self.style.WARNING(f'  Fila {i}: cantidad inválida "{cantidad_str}", usando 0.'))
                        cantidad = 0

                    medicamento = Medicamento.objects.create(
                        nombre_comercial=nombre,
                        concentracion=concentracion,
                        forma_farmaceutica=presentacion,
                        condiciones_almacenamiento=almacenamiento or 'sin restricciones',
                    )

                    MedicamentoDonado.objects.create(
                        donacion=donacion,
                        medicamento=medicamento,
                        fecha_vencimiento=FECHA_VENCIMIENTO_DEFAULT,
                        lote=LOTE_DEFAULT,
                        cantidad=cantidad,
                        estado=MedicamentoDonado.Estado.DISPONIBLE,
                    )

                    creados += 1

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Fila {i}: error inesperado - {e}'))
                    errores += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nInventario cargado: {creados} medicamentos creados, '
            f'{omitidos} omitidos, {errores} errores.'
        ))
        self.stdout.write(self.style.WARNING(
            f'IMPORTANTE: Los registros de stock tienen fecha de vencimiento '
            f'{FECHA_VENCIMIENTO_DEFAULT} y lote "{LOTE_DEFAULT}" como valores por defecto. '
            f'Actualízalos desde el admin de Django.'
        ))
