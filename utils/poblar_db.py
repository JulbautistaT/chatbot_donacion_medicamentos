import pandas as pd
from stock import models as stock_models

# Read CSV file
# NOTE: The headers in the CSV file should be:
# 'Principio activo', 'Presentación ', 'Almacenamiento', 'Concentración', 'Cantidad'
df = pd.read_csv('Inventario.csv')

donante_obj, _ = stock_models.Donante.objects.get_or_create(
    pk=1,
    defaults={
        'nombre': 'Donante por defecto',
        'tipo_donante': stock_models.Donante.TipoDonante.PARTICULAR,
        'telefono': '0000000000',
        'email': 'contacto@ejemplo.com',
        'canal_donacion': 'email',
        'verificado': True,
    }
)
donacion_obj = stock_models.Donacion.objects.create(
    donante=donante_obj,
    observaciones="Medicamentos de DB de UdeA",
)

for index, row in df.iterrows():
    # Extract data from the row
    nombre_comercial = row['Principio activo'].strip().replace(',', '')
    forma_farmaceutica = row['Presentación '].replace(',', '')
    condiciones_almacenamiento = row['Almacenamiento']
    concentracion = row['Concentración']  # Assuming this column exists

    # Create or update the Medicamento instance
    medicamento_obj, created = stock_models.Medicamento.objects.update_or_create(
        nombre_comercial=nombre_comercial,
        forma_farmaceutica=forma_farmaceutica,
        defaults={
            'condiciones_almacenamiento': condiciones_almacenamiento,
            'concentracion': concentracion,  # Add this field if it exists in your model
        }
    )

    medicamento_donado_obj = stock_models.MedicamentoDonado.objects.create(
        donacion=donacion_obj,
        medicamento=medicamento_obj,
        fecha_vencimiento='2025-12-31',  # Example date, adjust as needed
        lote="Lote123",  # Example lot number, adjust as needed
        cantidad=row['Cantidad'],
        estado=stock_models.MedicamentoDonado.Estado.DISPONIBLE,
    )
