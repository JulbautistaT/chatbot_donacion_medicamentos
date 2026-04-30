import pandas as pd
from stock import models as stock_models

df = pd.read_csv('Inventario.csv')

for  _, row in df.iterrows():
    nombre_comercial = row['Principio activo'].strip().replace(',', '')
    concentracion = row['Concentración'].strip()

    medicamento_obj, created = stock_models.Medicamento.objects.update_or_create(
        nombre_comercial=nombre_comercial,
        concentracion=concentracion   
    )

    if created:
        stock_models.MedicamentoDonado.objects.create(
        medicamento=medicamento_obj,
        estado=stock_models.Medicamento.Estado.DISPONIBLE,            
        )
