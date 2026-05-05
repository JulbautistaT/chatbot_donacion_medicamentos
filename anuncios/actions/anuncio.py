import requests as http_requests
from django.conf import settings
from stock.models import Solicitante


def enviar_anuncio_masivo(modeladmin, request, queryset):
    token = settings.TELEGRAM_BOT_TOKEN
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    solicitantes = Solicitante.objects.exclude(
        telegram_id__isnull=True
    ).exclude(
        telegram_id=''
    )

    anuncios_texto = []

    for anuncio in queryset.select_related('medicamento'):
        texto = (
            f"• {anuncio.medicamento.nombre_comercial} "
            f"{anuncio.medicamento.concentracion}\n"
            f"Cantidad disponible: {anuncio.cantidad} sobres\n"
        )

        if anuncio.notas_adicionales:
            texto += f"Notas: {anuncio.notas_adicionales}\n"

        anuncios_texto.append(texto)

    mensaje = (
        "📢 *Medicamentos disponibles actualmente*\n\n"
        + "\n".join(anuncios_texto) +
        "\nPor favor comuníquese si necesita alguno."
    )

    enviados = 0
    errores = 0

    telegram_ids = (
        Solicitante.objects
        .exclude(telegram_ids_isnull = True)
        .exclude(telegram_id='')
        .values_list('telegram_id', flat=True)
        .distinct()
    )

    for telegram_id in telegram_ids:
        try:
            response = http_requests.post(
                api_url,
                json={
                    "chat_id": telegram_id,
                    "text": mensaje,
                    "parse_mode": "Markdown"
                },
                timeout=10
            )

            if response.ok:
                enviados += 1
            else:
                errores += 1

        except Exception:
            errores += 1

    modeladmin.message_user(
        request,
        f"Mensajes enviados: {enviados}. Errores: {errores}"
    )