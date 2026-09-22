from django.db import models
from django.core.exceptions import ValidationError


class DetalleSolicitud(models.Model):
    solicitud = models.ForeignKey(
        'Solicitud',
        on_delete=models.CASCADE,
        related_name='detalles',
        help_text='Solicitud a la que pertenece el detalle'
    )
    medicamento = models.ForeignKey(
        'Medicamento',
        on_delete=models.CASCADE,
        related_name='detalles',
        help_text='Medicamento solicitado'
    )
    cantidad_entregada = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Cantidad de sobres entregados'
    )
    
    class TipoPresentacion(models.TextChoices):
        SOBRE_PASTILLAS = 'SP', 'Sobre (con Pastillas)'
        SOBRE_POLVO = 'SO', 'Sobre (en Polvo)'
        FRASCO = 'FR', 'Frasco (Jarabe / Gotas)'
        TUBO = 'TU', 'Tubo (Crema)'
        CAJA = 'CJ', 'Caja Completa'
        PIEZA = 'PS', 'Pieza Suelta'
        SONDA = 'SA', 'Sonda de Alimentación'

    tipo_presentacion = models.CharField(
        verbose_name="Tipo de presentación",
        max_length=2,
        choices=TipoPresentacion.choices,
        null=True,
        blank=True,
        help_text='Presentación del medicamento entregado',
    )
    class Meta:
        verbose_name = 'Detalle de Solicitud'
        verbose_name_plural = 'Detalles de Solicitud'


class Entrega(models.Model):
    solicitud = models.OneToOneField(
        'Solicitud',
        on_delete=models.CASCADE,
        related_name='entrega',
        help_text='Solicitud a la que pertenece la entrega'
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora en que se realizó la entrega'
    )
    persona_que_entrega = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Nombre de la persona que entrega la solicitud'
    )
    observaciones = models.TextField(
        blank=True,
        null=True,
        help_text='Observaciones adicionales sobre la entrega'
    )

    acta_generada = models.BooleanField(
        default=False,
        verbose_name="Acta generada"
    )

    class Meta:
        verbose_name = 'Entrega'
        verbose_name_plural = 'Entregas'


class Formula(models.Model):
    solicitud = models.ForeignKey(
        'Solicitud',
        on_delete=models.CASCADE,
        related_name='formulas',
        help_text='Solicitud a la que pertenece la fórmula'
    )
    archivo_formula = models.FileField(
        upload_to='formulas/',
        help_text='Archivo de la fórmula solicitada'
    )
    texto_ocr = models.TextField(
        null=True,
        blank=True,
        help_text='Texto extraído del archivo (uso interno del administrador)'
    )

    class Meta:
        verbose_name = 'Fórmula'
        verbose_name_plural = 'Fórmulas'


class Medicamento(models.Model):
    nombre_comercial = models.CharField(
        max_length=100,
        help_text='Nombre comercial del medicamento'
    )
    concentracion = models.CharField(
        max_length=100,
        help_text='Concentración del medicamento (ej. 500mg, 250mg)'
    )

    class Meta:
        verbose_name = 'Medicamento'
        verbose_name_plural = 'Medicamentos'
        ordering = ['nombre_comercial']

    def __str__(self):
        return f"{self.nombre_comercial} - {self.concentracion}"


class Solicitante(models.Model):
    nombre = models.CharField(
        max_length=100,
        help_text='Nombre del solicitante'
    )
    documento = models.CharField(
        max_length=50,
        unique=True,                         
        help_text='Número de documento del solicitante'
    )
    telegram_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,                        
        help_text='ID de Telegram del solicitante'
    )
    telefono = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text='Teléfono de contacto'
    )
    direccion_beneficiario = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Dirección del beneficiario'
    )
    fecha_registro = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora de registro'
    )
    verificado = models.BooleanField(
        default=False,
        help_text='Indica si el solicitante fue verificado mediante OCR de fórmula médica'
    )

    class Meta:
        verbose_name = 'Solicitante'
        verbose_name_plural = 'Solicitantes'

    def __str__(self):
        return f"{self.nombre} - CC {self.documento} - ({self.pk})"


class Solicitud(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        ACEPTADA = 'aceptada', 'Aceptada'
        RECHAZADA = 'rechazada', 'Rechazada'
        ENTREGADA = 'entregada', 'Entregada'

    solicitante = models.ForeignKey(
        Solicitante,
        on_delete=models.CASCADE,
        related_name='solicitudes',
        help_text='Solicitante que realiza la solicitud'
    )
    solicitud_propia = models.BooleanField(
        default=True,
        help_text='Indica si la solicitud es propia del solicitante o de un tercero'
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora de la solicitud'
    )

    estado = models.CharField(
        max_length=50,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        help_text='Estado de la solicitud'
    )
    observaciones = models.TextField(
        blank=True,
        null=True,
        help_text=(
            'Observaciones adicionales. Este texto se incluye en el mensaje de Telegram '
            'que se envía al solicitante al notificar la aceptación o el rechazo de la '
            'solicitud, por lo que debe redactarse pensando en que el usuario lo leerá '
            '(ej. motivo del rechazo o indicaciones para la entrega).'
        )
    )

    notificada_aceptacion = models.BooleanField(
        default=False,
        verbose_name="Notificación de aceptación enviada"
    )

    notificada_rechazo = models.BooleanField(
        default=False,
        verbose_name="Notificación de rechazo enviada"
    )


    class Meta:
        verbose_name = 'Solicitud'
        verbose_name_plural = 'Solicitudes'
        ordering = ['-fecha']

    def __str__(self):
        return f"Solicitud #{self.pk} - {self.solicitante.nombre} [{self.estado}]"