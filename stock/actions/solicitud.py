import requests as http_requests
import pandas as pd
import logging
import io
from django.conf import settings
from django.http import HttpResponse

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


def enviar_mensaje_telegram(chat_id, mensaje):
    logger = logging.getLogger(__name__)

    token = settings.TELEGRAM_BOT_TOKEN

    api_url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    try:
        resp = http_requests.post(
            api_url,
            json={
                "chat_id": chat_id,
                "text": mensaje,
                "parse_mode": "Markdown"
            },
            timeout=10,
        )

        if resp.ok:
            return True

        logger.error(
            f"Telegram respondió con error: {resp.text}"
        )
        return False

    except Exception as e:
        logger.error(
            f"Error enviando mensaje Telegram: {e}"
        )
        return False




def notificar_solicitudes_aceptadas(modeladmin, request, queryset):

    enviados = 0
    errores = 0

    for solicitud in queryset:

        mensaje = (
            f"✅ *Solicitud #{solicitud.pk} ACEPTADA*\n\n"
            f"Hola {solicitud.solicitante.nombre},\n\n"
            f"Tu solicitud fue aprobada.\n\n"
            f"📌 Acércate a reclamar tus medicamentos.\n\n"
        )

        if solicitud.observaciones:
            mensaje += f"📝 Observaciones: {solicitud.observaciones}\n\n"

        mensaje += "Gracias 🙌"

        ok = enviar_mensaje_telegram(
            solicitud.solicitante.telegram_id,
            mensaje
        )

        if ok:
            solicitud.notificada_aceptacion = True
            solicitud.save(
                update_fields=['notificada_aceptacion']
            )
            enviados += 1
        else:
            errores += 1

    modeladmin.message_user(
        request,
        f"Enviados: {enviados}, Errores: {errores}",
        level='success' if errores == 0 else 'warning'
    )


def notificar_solicitudes_rechazadas(modeladmin, request, queryset):

    enviados = 0
    errores = 0

    for solicitud in queryset:

        mensaje = (
            f"❌ *Solicitud #{solicitud.pk} RECHAZADA*\n\n"
            f"Hola {solicitud.solicitante.nombre},\n\n"
            f"Tu solicitud no pudo ser aprobada en esta ocasión.\n\n"
        )

        if solicitud.observaciones:
            mensaje += f"📝 Motivo: {solicitud.observaciones}\n\n"

        mensaje += (
            f"📌 Puedes realizar una nueva solicitud más adelante.\n\n"
            f"Gracias 🙌"
        )

        ok = enviar_mensaje_telegram(
            solicitud.solicitante.telegram_id,
            mensaje
        )

        if ok:
            solicitud.notificada_rechazo = True
            solicitud.save(
                update_fields=['notificada_rechazo']
            )
            enviados += 1
        else:
            errores += 1

    modeladmin.message_user(
        request,
        f"Enviados: {enviados}, Errores: {errores}",
        level='success' if errores == 0 else 'warning'
    )