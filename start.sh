#!/bin/bash
# Arranca web + bot en un mismo contenedor (plataformas con un solo servicio gratuito).
set -e

python manage.py migrate --noinput

# Crea el administrador inicial solo si se definieron DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD.
# Si ya existe (o faltan variables) el comando falla y se ignora.
python manage.py createsuperuser --noinput || true

python bot.py &
BOT_PID=$!

gunicorn donacion_medicamentos.wsgi:application \
    --workers 1 --timeout 120 --bind "0.0.0.0:${PORT:-8000}" \
    --forwarded-allow-ips '*' --access-logfile - --error-logfile - &
WEB_PID=$!

trap 'kill $BOT_PID $WEB_PID 2>/dev/null' TERM INT

# Si cualquiera de los dos procesos muere, el contenedor termina y la plataforma lo reinicia.
set +e
wait -n
STATUS=$?
kill $BOT_PID $WEB_PID 2>/dev/null
exit $STATUS
