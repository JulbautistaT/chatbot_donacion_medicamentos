import requests as http_requests
import pandas as pd
import logging
import io
from django.conf import settings
from django.http import HttpResponse


def notificar_solicitudes_aceptadas(modeladmin, request, queryset):
    logger = logging.getLogger(__name__)
    token = settings.TELEGRAM_BOT_TOKEN
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    enviados = 0
    errores = 0

    for solicitud in queryset:
        try:
            telegram_id = solicitud.solicitante.telegram_id

            mensaje = (
                f"✅ *Solicitud #{solicitud.pk} ACEPTADA*\n\n"
                f"Hola {solicitud.solicitante.nombre},\n\n"
                f"Tu solicitud fue aprobada.\n\n"
                f"📌 Acercate a reclamar tus medicamentos.\n\n"
                f"Gracias 🙌"
            )

            resp = http_requests.post(
                api_url,
                json={
                    "chat_id": telegram_id,
                    "text": mensaje,
                    "parse_mode": "Markdown"
                },
                timeout=10,
            )

            if resp.ok:
                enviados += 1
            else:
                errores += 1

        except Exception as e:
            logger.error(f"Error enviando Telegram a solicitud {solicitud.pk}: {e}")
            errores += 1

    modeladmin.message_user(
        request,
        f"Enviados: {enviados}, Errores: {errores}",
        level='success' if errores == 0 else 'warning'
    )


def download_requests_info(modeladmin, request, queryset):
    """
    Custom action to download information about requests.
    This is a placeholder for the actual implementation.
    """
    
    # Make df with the next columns:
    solicitud_query = queryset.select_related('solicitante').prefetch_related('detalles__medicamento')

    data = []
    for solicitud in solicitud_query:

        medicamentos_solicitados = ""
        for detalle in solicitud.detalles.all():
            medicamentos_solicitados += f"{detalle.medicamento.nombre_comercial} ({detalle.medicamento.concentracion})"
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
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="solicitudes_info.csv"'
    return response

