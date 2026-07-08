# Sistema de Donación de Medicamentos

Un sistema web completo para la gestión de donaciones y solicitudes de medicamentos, desarrollado con Django y integrado con un bot de Telegram para facilitar las solicitudes.

## Características

- 🏥 **Gestión de Inventario**: Control completo de medicamentos donados con fechas de vencimiento y lotes
- 👥 **Gestión de Usuarios**: Registro y manejo de donantes y solicitantes
- 📋 **Solicitudes Inteligentes**: Sistema de solicitudes con validación de stock automática
- 🤖 **Bot de Telegram**: Interfaz conversacional para solicitudes de medicamentos
- 📊 **Panel Administrativo**: Interface web completa para la gestión del sistema
- 🔄 **Procesamiento Asíncrono**: Manejo de tareas con Celery y Redis
- 📁 **Gestión de Archivos**: Upload y manejo de fórmulas médicas
- 🔒 **Validaciones**: Control de inventario y auditoría automática

## Tecnologías

- **Backend**: Django 4.x, Python 3.10
- **Base de Datos**: SQLite (configurable a PostgreSQL/MySQL)
- **Cola de Tareas**: Celery + Redis
- **Bot**: python-telegram-bot
- **Servidor Web**: Gunicorn + Nginx
- **Contenedores**: Docker + Docker Compose

## Estructura del Proyecto

```
donacion_medicamentos/
├── api/                    # API REST endpoints
├── donacion_medicamentos/  # Configuración principal de Django
├── stock/                  # Modelos y lógica de negocio principal
│   ├── models.py          # Modelos de datos
│   ├── admin.py           # Configuración del admin
│   ├── signals.py         # Señales para control de inventario
│   └── actions/           # Acciones personalizadas
├── media/                 # Archivos subidos (fórmulas, fotos)
├── static/                # Archivos estáticos
├── templates/             # Plantillas HTML
├── nginx/                 # Configuración de Nginx
├── logs/                  # Logs de la aplicación
├── docker-compose.yml     # Configuración de servicios
├── Dockerfile            # Imagen de contenedor
├── requirements.txt      # Dependencias de Python
└── manage.py             # Comando de gestión de Django
```

## Instalación y Configuración

### Prerrequisitos

- Docker y Docker Compose instalados
- Un bot de Telegram creado (obtén el token desde [\@BotFather](https://telegram.me/BotFather)).

### 1. Clonar el repositorio

```bash
git clone <repository-url>
cd donacion_medicamentos
```

### 2. Configurar variables de entorno

```bash
# Copiar el archivo de configuración de ejemplo
cp .env.sample .env

# Editar el archivo .env con tus valores
nano .env
```

**Variables importantes a configurar:**

```bash
# Token de tu bot de Telegram
TELEGRAM_BOT_TOKEN='tu-token-aqui'

# Configuración de Django
DJANGO_SECRET_KEY='tu-clave-secreta'
DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1'
DJANGO_CSRF_TRUSTED_ORIGINS='http://localhost:81'

# Host para archivos media
MEDIA_HOST='http://localhost:8000'
```

### 3. Construir la imagen Docker

```bash
docker build -t donacion_medicamentos-backend:1.0.0 .
```

### 4. Iniciar los servicios

```bash
# Iniciar todos los servicios
docker-compose up -d

# Ver los logs
docker-compose logs -f
```

### 5. Configurar la base de datos

```bash
# Ejecutar migraciones
docker-compose exec donacion_medicamentos python manage.py migrate
docker-compose exec donacion_medicamentos python manage.py make migrations

# Crear superusuario para el admin
docker-compose exec donacion_medicamentos python manage.py createsuperuser

# (Opcional) Cargar datos de prueba
docker-compose exec donacion_medicamentos python utils/poblar_db.py
```

## Servicios Disponibles

Una vez iniciado el sistema, tendrás acceso a:

### 🌐 **Aplicación Web** 
- **URL**: http://localhost:81
- **Admin**: http://localhost:81/admin
- Gestión completa de donaciones, solicitudes y medicamentos

### 🤖 **Bot de Telegram**
- Busca tu bot en Telegram usando el nombre configurado
- Comando inicial: `/iniciar`
- Permite crear solicitudes de medicamentos de forma conversacional

### 📊 **API REST**
- **Base URL**: http://localhost:81/api/
- Endpoints para integración con otros sistemas

## Uso del Sistema

### Para Administradores

1. **Accede al panel admin**: http://localhost:81/admin
2. **Gestiona Donantes**: Registra organizaciones y personas que donan
3. **Registra Donaciones**: Añade medicamentos recibidos con lotes y fechas
4. **Procesa Solicitudes**: Revisa y aprueba solicitudes de medicamentos
5. **Controla Inventario**: El sistema mantiene automáticamente el stock

### Para Solicitantes (Telegram)

1. **Inicia conversación**: Envía `/iniciar` a tu bot
2. **Registro inicial**: Proporciona documento, nombre, telefono y dirección
3. **Solicita medicamentos**: Elige entre:
   - Descripción manual de medicamentos
   - Subir foto/PDF de fórmula médica
4. **Seguimiento**: Consulta estado con "Consultar estado"

### Validaciones de Negocio

- **Estados consistentes**: Transiciones automáticas de estados

### Bot Inteligente

- **Sesiones persistentes**: Mantiene el contexto de la conversación
- **Validación en tiempo real**: Verifica datos mientras el usuario los ingresa
- **Búsqueda por letra**: Facilita encontrar medicamentos disponibles
- **Múltiples formatos**: Acepta fotos, PDFs y texto

## Comandos Útiles

### Gestión de Contenedores

```bash
# Ver estado de los servicios
docker-compose ps

# Detener todos los servicios
docker-compose down

# Reiniciar un servicio específico
docker-compose restart donacion_medicamentos

# Ver logs de un servicio
docker-compose logs -f telegram_bot
```

### Gestión de Django

```bash
# Ejecutar comandos de Django
docker-compose exec donacion_medicamentos python manage.py <comando>

# Crear migraciones
docker-compose exec donacion_medicamentos python manage.py makemigrations

# Aplicar migraciones
docker-compose exec donacion_medicamentos python manage.py migrate

# Shell de Django
docker-compose exec donacion_medicamentos python manage.py shell
```

### Gestión de la Base de Datos

```bash
# Backup de la base de datos
docker-compose exec donacion_medicamentos python manage.py dumpdata > backup.json

# Restaurar desde backup
docker-compose exec donacion_medicamentos python manage.py loaddata backup.json
```

``` bash
# Cargar inventario inicial
docker-compose exec donacion_medicamentos python manage.py shell

exec(open("utils/poblar_db.py").read())
```

## Estructura de la Base de Datos

### Modelos Principales

- **Solicitante**: Personas que solicitan medicamentos
- **Medicamento**: Catálogo de medicamentos
- **Solicitud**: Solicitudes de medicamentos
- **DetalleSolicitud**: Detalle de medicamentos por solicitud
- **Entrega**: Registro de entregas realizadas
- **Formula**: Archivos de fórmulas médicas

## Monitoreo y Logs

Los logs se almacenan en la carpeta `logs/`:

```bash
# Ver logs de la aplicación
tail -f logs/donacion_medicamentos.log

# Ver logs del bot
docker-compose logs -f telegram_bot

# Ver logs de Celery
docker-compose logs -f celery
```

## Solución de Problemas

### El bot no responde

1. Verifica que el token de Telegram sea correcto
2. Asegúrate de que el servicio `telegram_bot` esté ejecutándose
3. Revisa los logs: `docker-compose logs -f telegram_bot`

### Error de migraciones

```bash
# Aplicar migraciones específicas
docker-compose exec donacion_medicamentos python manage.py migrate stock

# Ver estado de migraciones
docker-compose exec donacion_medicamentos python manage.py showmigrations
```

### Problemas de permisos

```bash
# Ajustar permisos de carpetas
sudo chown -R $USER:$USER media/ static/ logs/
```

## Desarrollo

### Agregar nuevas funcionalidades

1. **Modifica modelos** en `stock/models.py`
2. **Crea migraciones**: `python manage.py makemigrations`
3. **Actualiza admin** en `stock/admin.py`
4. **Añade validaciones** en `stock/signals.py`

### Personalizar el bot

El bot se encuentra en el paquete modular `donacion_medicamentos/bot/`. El orquestador principal de arranque es `donacion_medicamentos/bot/controller.py`. Puedes:
- Añadir o modificar comandos en `handlers.py`
- Modificar o agregar flujos de conversación dentro de la carpeta `conversation/`
- Integrar nuevos validadores o servicios en sus archivos correspondientes (`validators.py`, `request.py`, etc.)

## Contribución

1. Fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -am 'Añadir nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Crea un Merge Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo LICENSE para detalles.

## Soporte

Para problemas y preguntas:
- Crea un issue en el repositorio
- Puedes contactar a @user5c
- Consulta los logs para diagnóstico

---

**Nota**: Asegúrate de configurar correctamente las variables de entorno antes de iniciar el sistema en producción.
