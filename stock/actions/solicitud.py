import pandas as pd
from django.contrib import admin
from django.http import HttpResponse



def download_requests_info(modeladmin, request, queryset):
    """
    Custom action to download information about requests.
    This is a placeholder for the actual implementation.
    """
    
    # Make df with the next columns:
    solicitud_query = queryset.select_related('solicitante')

    data = []
    for solicitud in solicitud_query:

        medicamentos_solicitados = ""
        for detalle in solicitud.detalles.all():
            medicamentos_solicitados += f"{detalle.medicamento.nombre_comercial} (Cantidad: {detalle.cantidad_solicitada}), "
        medicamentos_solicitados = medicamentos_solicitados.rstrip(", ")

        data.append({
            'Solicitante': solicitud.solicitante.nombre,
            'Documento': solicitud.solicitante.documento,
            'Fecha': solicitud.fecha.strftime('%Y-%m-%d'),
            'Prioridad': solicitud.get_prioridad_display(),
            'Estado': solicitud.get_estado_display(),
            'Observaciones': solicitud.observaciones,
            'Medicamentos Solicitados': medicamentos_solicitados
        })

    df = pd.DataFrame(data)
    df.to_csv('solicitudes_info.csv', index=False)

    # Send the file to the user
    with open('solicitudes_info.csv', 'rb') as f:
        response = HttpResponse(f.read(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="solicitudes_info.csv"'
        return response
