import requests as http_requests
import logging
from django.conf import settings
from stock.models import Solicitante

logger = logging.getLogger(__name__)

LIMITE_TELEGRAM = 4096


def dividir_en_partes(anuncios_texto, encabezado, pie):
    """
    Agrupa los anuncios en partes que no superen el límite de Telegram.
    Cada parte incluye encabezado y pie de mensaje.
    """
    partes = []
    parte_actual = []
    largo_actual = len(encabezado) + len(pie)

    for texto in anuncios_texto:
        if largo_actual + len(texto) > LIMITE_TELEGRAM:
            if parte_actual:
                partes.append(parte_actual)
            parte_actual = [texto]
            largo_actual = len(encabezado) + len(pie) + len(texto)
        else:
            parte_actual.append(texto)
            largo_actual += len(texto)

    if parte_actual:
        partes.append(parte_actual)

    return partes


def enviar_anuncio_masivo(modeladmin, request, queryset):
    if not queryset.exists():
        modeladmin.message_user(request, "No hay anuncios seleccionados.", level="warning")
        return

    token = settings.TELEGRAM_BOT_TOKEN
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    encabezado = "📢 *Medicamentos disponibles actualmente*\n\n"
    pie = (
        "\nSi cuenta con una fórmula no mayor a 3 meses de estos medicamentos."
        "\nPor favor acercarse."
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

    partes = dividir_en_partes(anuncios_texto, encabezado, pie)

    telegram_ids = (
        Solicitante.objects
        .exclude(telegram_id__isnull=True)
        .exclude(telegram_id='')
        .values_list('telegram_id', flat=True)
        .distinct()
    )

    enviados = 0
    errores = 0
    total_partes = len(partes)

    for telegram_id in telegram_ids:
        for i, parte in enumerate(partes, start=1):
            # Indica parte X de N solo si hay más de una
            sufijo_parte = f" _(parte {i}/{total_partes})_" if total_partes > 1 else ""
            mensaje = encabezado.rstrip() + sufijo_parte + "\n\n" + "\n".join(parte) + pie

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
                    logger.warning(f"Telegram rechazó mensaje a {telegram_id}: {response.text}")
                    errores += 1

            except Exception as e:
                logger.error(f"Error enviando anuncio a {telegram_id}: {e}")
                errores += 1

    modeladmin.message_user(
        request,
        f"{queryset.count()} anuncio(s) en {total_partes} parte(s). "
        f"✅ Enviados: {enviados} | ❌ Errores: {errores}"
    )

