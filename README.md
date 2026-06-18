# Sistema de Donación de Medicamentos

<p align="center">
  <img src="https://img.shields.io/badge/Estado-En%20Desarrollo-orange?style=for-the-badge&logo=git" alt="Estado: En Desarrollo">
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=for-the-badge&logo=django" alt="Django version">
  <img src="https://img.shields.io/badge/Python-3.10-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python version">
  <img src="https://img.shields.io/badge/Telegram_Bot-22.1-26A69A?style=for-the-badge&logo=telegram" alt="Telegram Bot version">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker" alt="Docker version">
  <img src="https://img.shields.io/badge/Licencia-MIT-green?style=for-the-badge" alt="Licencia MIT">
</p>

---

## 📝 Descripción del Proyecto

Este es un sistema web integral y conversacional diseñado para optimizar y gestionar la donación y solicitud de medicamentos. Combina un robusto panel administrativo y API en Django con una interfaz interactiva de Telegram Bot que asiste a los usuarios solicitantes. 

El proyecto fue reestructurado para ofrecer un entorno seguro, escalable y con herramientas avanzadas para la automatización de flujos médicos, incluyendo procesamiento de recetas por OCR, auditoría física mediante actas de entrega en PDF y control de caducidad.

---

## 🚧 Estado del Proyecto
> [!NOTE]
> **Fase Actual:** **En Desarrollo**. 
> Se están implementando y refinando módulos conversacionales, pruebas del pipeline de OCR adaptativo y ajustes de seguridad en el entorno local.

---


## ✨ Características Destacadas

### 📷 Procesamiento OCR Inteligente
* **Pipeline Adaptativo:** El procesador realiza un análisis automático de calidad para decidir si aplica un preprocesamiento ligero o uno de rescate (mediante **OpenCV** y **Pillow**) ante imágenes oscuras o rotadas.
* **Extracción de Fórmulas:** Permite leer formatos PDF e imágenes (PNG/JPG) con recetas médicas mediante **Tesseract OCR**, automatizando la validación de medicamentos contra las solicitudes.

### 🤖 Bot de Telegram Multiusuario
* **Seguridad y Persistencia de Sesión:** Mantiene de forma segura el contexto de cada usuario permitiendo flujos de conversación estables y simultáneos para múltiples solicitantes.
* **Inicio y Cierre de Sesión:** Notificaciones claras al usuario sobre el estado de su sesión y el resguardo de su información.
* **Soporte Multimedia:** Capacidad de procesar múltiples archivos cargados de forma sucesiva por chat.

### 📋 Gestión de Inventario, Expiración y Auditoría
* **Actas de Entrega Físicas (PDF):** Generación automática de plantillas oficiales en formato PDF (usando **ReportLab**) preparadas para impresión física y firma manuscrita de los usuarios al recibir los medicamentos.
* **Control de Duplicación:** El sistema bloquea de manera inteligente la generación de actas duplicadas para garantizar la transparencia de la entrega de medicamentos.

### 🔒 Políticas de Datos y Consentimiento
* **Módulo de Políticas:** Mantenimiento de versiones de la política de datos (`politicas` app), garantizando que los usuarios presten su consentimiento explícito de manera transparente antes de usar el chatbot.

---

## 📁 Arquitectura del Proyecto

```
donacion_medicamentos/
├── anuncios/               # Módulo de avisos de disponibilidad
├── api/                    # Endpoints de la API REST del sistema
├── donacion_medicamentos/  # Configuración y controladores principales (Django/Bot)
│   ├── bot_controller.py   # Control de estados y lógica conversacional del Bot
│   ├── ocr.py              # Procesador y pipeline adaptativo de OCR
│   └── settings.py         # Configuración del entorno Django
├── politicas/              # Gestión de versión y vigencia de políticas de tratamiento de datos
├── stock/                  # Lógica de negocio principal (Medicamentos, Solicitudes, Entregas)
│   ├── actions/
│   │   └── plantilla_pdf.py # Motor de renderizado de actas PDF (ReportLab)
│   ├── models.py           # Estructura relacional de datos
│   └── admin.py            # Interfaces y acciones personalizadas en el Panel Admin
├── templates/              # Plantillas HTML
├── utils/                  # Scripts de utilidad (ej. poblar base de datos)
├── nginx/                  # Configuración de Servidor Web Nginx
├── docker-compose.yml      # Declaración de servicios (Django, Bot, Redis, Postgres)
├── Dockerfile              # Configuración del contenedor de la aplicación
└── requirements.txt        # Dependencias de Python del proyecto
```

---

## 🛠️ Tecnologías Utilizadas

* **Framework Principal:** [Django 5.2](https://www.djangoproject.com/)
* **Lenguaje:** [Python 3.10](https://www.python.org/)
* **Base de Datos:** [SQLite](https://www.sqlite.org/) (Por defecto para desarrollo) | [PostgreSQL](https://www.postgresql.org/) (Soportado mediante variables de entorno)
* **Motor Asíncrono y Mensajería:** [Celery](https://docs.celeryq.dev/) + [Redis](https://redis.io/)
* **Integración Conversacional:** [python-telegram-bot 22.1](https://python-telegram-bot.org/)
* **Procesamiento de Imágenes y Documentos (OCR):** [pytesseract](https://github.com/madmaze/pytesseract) + [opencv-python](https://opencv.org/) + [pdf2image](https://github.com/Belval/pdf2image)
* **Generación de Reportes PDF:** [ReportLab](https://www.reportlab.com/)
* **Servidor Web y Despliegue:** [Gunicorn](https://gunicorn.org/) + [Nginx](https://www.nginx.com/) + [Docker & Docker Compose](https://www.docker.com/)

---

## 🚀 Instalación y Configuración

### Prerrequisitos
* **Docker** y **Docker Compose** instalados en tu sistema.
* Un token de bot de Telegram obtenido a través de [@BotFather](https://t.me/BotFather).

### Paso 1: Clonar y Preparar
Clona este repositorio en tu máquina local:
```bash
git clone https://github.com/JulbautistaT/chatbot.git
cd donacion-medicamentos-master
```

### Paso 2: Variables de Entorno
Copia el archivo muestra y edita los valores correspondientes:
```bash
cp .env.sample .env
```

Abre el archivo `.env` y configura al menos los siguientes parámetros obligatorios:

```env
TELEGRAM_BOT_TOKEN='tu-token-de-telegram'
DJANGO_SECRET_KEY='una-clave-secreta-segura'
DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1'

# Opcional si decides usar PostgreSQL
# DB_NAME='nombre_bd'
# DB_USER='usuario_bd'
# DB_PASSWORD='password_bd'
# DB_HOST='db'
```

### Paso 3: Construcción y Despliegue
Construye la imagen Docker del backend:
```bash
docker build -t donacion_medicamentos-backend:1.0.0 .
```

Inicia todos los servicios del proyecto:
```bash
docker-compose up -d
```


### Paso 4: Base de Datos y Superusuario
1. Ejecuta las migraciones necesarias de Django:
   ```bash
   docker-compose exec donacion_medicamentos python manage.py migrate
   docker-compose exec donacion_medicamentos python manage.py makemigrations
   ```
2. Crea el usuario administrador para el panel web:
   ```bash
   docker-compose exec donacion_medicamentos python manage.py createsuperuser
   ```
3. *(Opcional)* Carga datos iniciales de prueba en el inventario:
   ```bash
   docker-compose exec donacion_medicamentos python utils/poblar_db.py
   ```

---

## 💡 Uso del Sistema

### Para el Administrador (Web)
1. Ingresa a la interfaz administrativa en [http://localhost:81/admin](http://localhost:81/admin).
2. Administra los **Medicamentos** 
3. Procesa las **Solicitudes** entrantes.
4. Genera las actas de entrega oficiales en formato PDF haciendo uso de las acciones personalizadas dentro del panel de **Entregas**. Recuerda imprimirlas para la firma física.

### Para el Solicitante (Telegram Bot)
1. Busca al bot en Telegram e inicia la conversación con el comando `/iniciar`.
2. Acepta las políticas de datos del sistema.
3. Registra tus datos básicos (Nombre, Documento, Teléfono, Dirección).
4. Sube tu fórmula médica (en formato PDF o foto) para la extracción y validación automática del medicamento solicitado por OCR.
5. Revisa el estado de tus solicitudes con el comando o botón **Consultar estado**.

---

## 📊 Monitoreo y Logs

Puedes seguir la ejecución del bot de Telegram y de Celery en tiempo real a través de Docker:
```bash
# Ver logs del Bot de Telegram
docker-compose logs -f telegram_bot

# Ver logs de Django
docker-compose logs -f donacion_medicamentos

# Ver logs del gestor de tareas Celery
docker-compose logs -f celery
```

---

## 👥 Créditos y Colaboradores

**Hernan Camilo Rivera Arteaga** 
 • Diseño de la arquitectura base del sistema.<br>
 • Desarrollo del MVP y primera versión funcional del bot de Telegram. 

**Julieth Andrea Bautista Tellez** [![GitHub](https://img.shields.io/badge/GitHub-Profile-181717?style=flat&logo=github)](https://github.com/JulbautistaT) 
• Reestructuración y optimización de la arquitectura.<br>
• Desarrollo de un pipeline de OCR adaptativo y automatización de envíos masivos a Telegram.<br>
• Desarrollo del sistema multiusuario persistente y generación de actas PDF para auditoría.<br>
• Integración de políticas de consentimiento de datos. |

---

## 📄 Licencia

Este proyecto está licenciado bajo la **Licencia MIT**.
