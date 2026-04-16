import requests as http_requests
import pandas as pd
from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse


def notificar_solicitudes_aceptadas(modeladmin, request, queryset):
    """
    Sends a Telegram notification to each solicitante whose solicitud is ACEPTADA
    and has a registered telegram_id.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    enviados = 0
    sin_telegram = 0
    no_aceptadas = 0
    errores = 0

    for solicitud in queryset.select_related('solicitante').prefetch_related('detalles__medicamento'):
        if solicitud.estado != 'aceptada':
            no_aceptadas += 1
            continue

        telegram_id = solicitud.solicitante.telegram_id
        if not telegram_id:
            sin_telegram += 1
            continue

        # Build medicine list
        lineas_medicamentos = []
        for detalle in solicitud.detalles.all():
            cantidad = detalle.cantidad_entregada if detalle.cantidad_entregada > 0 else detalle.cantidad_solicitada
            med = detalle.medicamento
            lineas_medicamentos.append(
                f"  • {med.nombre_comercial} {med.concentracion} ({med.forma_farmaceutica}): {cantidad} unidad(es)"
            )

        if lineas_medicamentos:
            lista_meds = "\n".join(lineas_medicamentos)
        else:
            lista_meds = "  (sin detalle de medicamentos)"

        mensaje = (
            f"✅ *Su solicitud #{solicitud.pk} ha sido ACEPTADA*\n\n"
            f"Estimado(a) {solicitud.solicitante.nombre}, le informamos que su solicitud "
            f"de medicamentos ha sido aprobada.\n\n"
            f"*Medicamentos a entregar:*\n{lista_meds}\n\n"
            f"Para coordinar la entrega comuníquese con nosotros."
        )

        try:
            resp = http_requests.post(
                api_url,
                json={"chat_id": telegram_id, "text": mensaje, "parse_mode": "Markdown"},
                timeout=10,
            )
            if resp.ok:
                enviados += 1
            else:
                errores += 1
                modeladmin.message_user(
                    request,
                    f"Error al notificar solicitud #{solicitud.pk}: {resp.text}",
                    level="warning",
                )
        except Exception as e:
            errores += 1
            modeladmin.message_user(
                request,
                f"Error al notificar solicitud #{solicitud.pk}: {e}",
                level="warning",
            )

    resumen = (
        f"Notificaciones enviadas: {enviados}. "
        f"Sin Telegram ID: {sin_telegram}. "
        f"No aceptadas (omitidas): {no_aceptadas}. "
        f"Errores: {errores}."
    )
    level = "success" if errores == 0 else "warning"
    modeladmin.message_user(request, resumen, level=level)


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
