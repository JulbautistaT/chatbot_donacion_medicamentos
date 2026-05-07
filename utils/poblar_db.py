import os
import sys
import django

sys.path.insert(0, '/home/app/donacion_medicamentos')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'donacion_medicamentos.settings')
django.setup()

import pandas as pd
from stock import models as stock_models

df = pd.read_csv('/home/app/donacion_medicamentos/utils/Inventario.csv', on_bad_lines='skip', encoding='utf-8-sig')
df.columns = df.columns.str.strip().str.replace('\ufeff', '')

print("Columnas encontradas:", df.columns.tolist())

for _, row in df.iterrows():
    nombre_comercial = row['Principio activo'].strip().replace(',', '')
    concentracion = row['Concentración'].strip()

    medicamento_obj, created = stock_models.Medicamento.objects.update_or_create(
        nombre_comercial=nombre_comercial,
        concentracion=concentracion
    )
    if created:
        print(f"✅ Creado: {nombre_comercial} - {concentracion}")

print("✅ Carga completada.")