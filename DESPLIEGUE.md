# Guía de despliegue gratuito — Oracle Cloud Always Free

Esta guía despliega la arquitectura actual del proyecto (Django + Postgres + Redis + Celery worker + bot de Telegram + Nginx, ya definida en [docker-compose.yml](docker-compose.yml)) sobre una VM del nivel **Always Free** de Oracle Cloud Infrastructure (OCI), sin reescribir código ni servicios.

## Por qué esta opción

- **Gratis para siempre**, no es un trial de tiempo limitado.
- Es una VM real: soporta los binarios de sistema que necesita el proyecto (`tesseract-ocr`, `poppler-utils`, `firefox-esr` + `geckodriver` para Selenium, ver [Dockerfile](Dockerfile)).
- Soporta procesos de larga duración sin "dormir" — crítico para el bot de Telegram (long-polling) y el worker de Celery.
- El `docker-compose.yml` del repo se usa **tal cual**, sin adaptarlo a un PaaS.

**Trade-off**: es una sola VM, sin alta disponibilidad ni escalado automático. Si se cae, hay que reiniciarla manualmente (aunque `restart: always` en Docker ayuda mucho). Aceptable para un proyecto universitario con tráfico bajo/medio.

---

## 0. Seguridad — hacer ANTES de desplegar

1. **Revocar y regenerar el token de Telegram.** `.env.sample` tiene un token con formato real commiteado en el historial de git (`TELEGRAM_BOT_TOKEN='8223453736:AAH1...'`). Ve a [@BotFather](https://t.me/BotFather) → `/revoke` (o `/token` para regenerar) sobre ese bot, y reemplaza el valor en `.env.sample` por un placeholder (`'123456:ABC-placeholder'`). El token real solo debe vivir en el `.env` de producción, que nunca se commitea.
2. Generar un `DJANGO_SECRET_KEY` nuevo y aleatorio (no reutilizar el de desarrollo):
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
3. Generar contraseñas nuevas para `DB_PASSWORD` (no dejar `donacion_pass`).

---

## 1. Crear la instancia Always Free

1. Crea una cuenta en [cloud.oracle.com](https://cloud.oracle.com) (pide tarjeta para verificación anti-fraude, pero los recursos "Always Free" no cobran).
2. **Menú ☰ → Compute → Instances → Create Instance.**
3. Configuración recomendada:
   - **Image**: Ubuntu 22.04 (o 24.04) — "Always Free-eligible".
   - **Shape**: `VM.Standard.A1.Flex` (Ampere ARM) → asigna **2 OCPU / 12 GB RAM** (dentro del máximo gratuito de 4 OCPU / 24 GB total). Con Selenium + OCR + Postgres + Redis corriendo juntos, no uses el mínimo de 1 OCPU/6GB si puedes evitarlo.
   - **Boot volume**: deja el tamaño por defecto (hasta 200GB gratis disponibles en total entre volúmenes).
   - Genera y descarga el **par de llaves SSH** (o sube tu llave pública).
4. Si la creación falla por "Out of capacity" (común en Ampere A1), reintenta en otro *Availability Domain* o región — es un problema conocido del free tier, no de tu cuenta.
5. Anota la **IP pública** de la instancia.

## 2. Abrir los puertos necesarios

Por defecto OCI bloquea casi todo el tráfico entrante. Ve a la subred de tu VM → **Security List** (o crea un **Network Security Group**) y agrega reglas de ingreso:

| Puerto | Protocolo | Origen      | Uso                          |
|--------|-----------|-------------|-------------------------------|
| 22     | TCP       | tu IP /32   | SSH (no lo dejes abierto a `0.0.0.0/0` si puedes evitarlo) |
| 80     | TCP       | 0.0.0.0/0   | HTTP (Nginx)                  |
| 443    | TCP       | 0.0.0.0/0   | HTTPS (si configuras Let's Encrypt) |

**No** expongas 5432 (Postgres) ni 6379 (Redis) a `0.0.0.0/0` — en el `docker-compose.yml` verás que hoy están publicados (`ports: '5432:5432'`, `'6379:6379'`), pero eso es solo cómodo para desarrollo local. En producción, quítales el mapeo de `ports` (deja únicamente `expose`) para que solo sean accesibles dentro de la red interna de Docker.

Además del Security List, Ubuntu trae su propio firewall (`iptables`/`ufw`) activo por defecto en las imágenes de OCI — habilítalo explícitamente para 80/443/22 o el tráfico seguirá bloqueado aunque el Security List esté bien.

## 3. Conectarte e instalar Docker

```bash
ssh -i tu_llave.pem ubuntu@<IP_PUBLICA>

# Firewall local (ajusta si usas otro puerto SSH)
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Docker + plugin de Compose
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

docker --version
docker compose version
```

## 4. Clonar el proyecto y configurar `.env`

```bash
git clone <URL_DEL_REPO> donacion_medicamentos
cd donacion_medicamentos
cp .env.sample .env
nano .env
```

Ajusta al menos:

```ini
DJANGO_DEBUG=''
DJANGO_SECRET_KEY='<el que generaste en el paso 0>'
DJANGO_ALLOWED_HOSTS='<IP_PUBLICA>,tu-dominio.com'
DJANGO_CSRF_TRUSTED_ORIGINS='http://<IP_PUBLICA>,https://tu-dominio.com'

MEDIA_HOST='http://<IP_PUBLICA>'   # o https://tu-dominio.com si tienes TLS

TELEGRAM_BOT_TOKEN='<el token nuevo del paso 0>'

DB_PASSWORD='<contraseña nueva>'

IMAGE='donacion_medicamentos-backend:1.0.1'
```

## 5. Endurecer `docker-compose.yml` para producción

Antes de levantar el stack, en el repo del **servidor** (no en tu máquina local, o sí si prefieres commitear el cambio):

- En el servicio `postgres`, quita el bloque `ports:` (deja solo `expose: [5432]`).
- En el servicio `redis`, quita el bloque `ports:` (deja solo `expose: [6379]`).
- En `donacion_medicamentos`, quita `ports: ['8000:8000']` si vas a servir todo a través de Nginx (deja solo `expose: [8000]`), y en `nginx` cambia `ports: ['81:80']` por `ports: ['80:80']` para que quede en el puerto estándar.

## 6. Levantar el stack

```bash
docker compose up -d --build

# Verifica que todos los servicios estén healthy/running
docker compose ps

# Migraciones y estáticos
docker compose exec donacion_medicamentos python manage.py migrate
docker compose exec donacion_medicamentos python manage.py collectstatic --noinput
docker compose exec donacion_medicamentos python manage.py createsuperuser
```

Confirma en el navegador: `http://<IP_PUBLICA>/admin/`.

Revisa logs si algo falla:

```bash
docker compose logs -f donacion_medicamentos
docker compose logs -f telegram_bot
docker compose logs -f celery
```

## 7. HTTPS gratis (recomendado si tienes dominio)

Si apuntas un dominio (o subdominio gratuito tipo DuckDNS/No-IP) a la IP pública, puedes usar **Certbot con Let's Encrypt** (gratis, se renueva automático):

```bash
sudo apt install certbot python3-certbot-nginx -y
```

Como Nginx corre dentro de un contenedor, la forma más simple es correr Certbot en modo standalone parando Nginx un momento, o añadir un contenedor `certbot`/`nginx-proxy` con renovación automática. Si quieres, en un siguiente paso te dejo el `docker-compose` con el contenedor de Certbot ya integrado.

## 8. Que sobreviva a reinicios del servidor

Docker ya se instala como servicio systemd y arranca en el boot. Solo falta que el *engine* de Docker levante tus contenedores automáticamente (ya tienen `restart: always` / `unless-stopped` en el compose, que cubre reinicios del propio Docker):

```bash
sudo systemctl enable docker
```

Con eso, si la VM se reinicia, Docker arranca solo y los contenedores con política de reinicio vuelven a levantarse.

## 9. Backups gratuitos

- **Postgres**: cron diario con `pg_dump` hacia el **Object Storage** de OCI (10GB gratis en Always Free):
  ```bash
  docker compose exec -T postgres pg_dump -U $DB_USER $DB_NAME > backup_$(date +%F).sql
  ```
  Sube el `.sql` con `oci os object put` (CLI de OCI) o simplemente rota backups locales en el volumen `postgres_data` si el volumen del boot ya tiene espacio de sobra.
- **Media** (fórmulas/fotos subidas): incluye la carpeta `media/` en el mismo backup o sincronízala al Object Storage.

## 10. Monitoreo básico gratuito

- [UptimeRobot](https://uptimerobot.com) (plan free): pings cada 5 min a `http://<IP_o_dominio>/admin/login/` y te avisa por correo/Telegram si el sitio cae.
- `docker compose logs` + `docker stats` para revisar uso de CPU/RAM manualmente.

---

## Checklist final

- [ ] Token de Telegram revocado y regenerado
- [ ] `.env` con secretos nuevos (no los de `.env.sample`)
- [ ] Puertos 5432/6379 no expuestos públicamente
- [ ] `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` con la IP o dominio real
- [ ] `docker compose ps` muestra todos los servicios `Up`/`healthy`
- [ ] Admin accesible y superusuario creado
- [ ] Bot responde en Telegram
- [ ] `systemctl enable docker` ejecutado
- [ ] Backup de Postgres programado (cron)
- [ ] Monitor externo (UptimeRobot) configurado
