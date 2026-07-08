import csv
import os
from django.db import migrations
from django.conf import settings

def load_initial_medicamentos(apps, schema_editor):
    Medicamento = apps.get_model('stock', 'Medicamento')
    
    # Path to Inventario.csv
    csv_path = os.path.join(settings.BASE_DIR, 'utils', 'Inventario.csv')
    
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                principio_activo = row.get('Principio activo')
                if principio_activo:
                    nombre = principio_activo.strip().replace(',', '')
                    concentracion = row.get('Concentración', '').strip()
                    Medicamento.objects.update_or_create(
                        nombre_comercial=nombre,
                        concentracion=concentracion
                    )

def unload_initial_medicamentos(apps, schema_editor):
    Medicamento = apps.get_model('stock', 'Medicamento')
    Medicamento.objects.all().delete()

class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(load_initial_medicamentos, unload_initial_medicamentos),
    ]
