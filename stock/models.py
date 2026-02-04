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
    cantidad_solicitada = models.PositiveIntegerField(
        default=0,
        help_text='Cantidad solicitada del medicamento'
    )
    cantidad_entregada = models.PositiveIntegerField(
        default=0,
        help_text='Cantidad entregada del medicamento'
    )


    def clean(self):
        """Validate that there's enough stock available for the cantidad_entregada."""
        super().clean()
        
        # Skip validation for new instances without medicamento
        if not self.medicamento:
            return
            
        # Get current available quantity for this medicamento
        from django.db.models import Sum
        
        # Calculate total available quantity
        total_available = MedicamentoDonado.objects.filter(
            medicamento=self.medicamento,
            estado=MedicamentoDonado.Estado.DISPONIBLE,
            cantidad__gt=0
        ).aggregate(total=Sum('cantidad'))['total'] or 0
        
        # If this is an update, we need to account for previously delivered quantity
        previous_cantidad_entregada = 0
        if self.pk:
            try:
                previous_instance = DetalleSolicitud.objects.get(pk=self.pk)
                previous_cantidad_entregada = previous_instance.cantidad_entregada
            except DetalleSolicitud.DoesNotExist:
                pass
        
        # Calculate the additional quantity being requested
        additional_quantity_needed = self.cantidad_entregada - previous_cantidad_entregada
        
        # Check if there's enough available stock
        if additional_quantity_needed > total_available:
            raise ValidationError({
                'cantidad_entregada': f'No hay suficiente stock disponible. '
                                    f'Cantidad disponible: {total_available}, '
                                    f'cantidad adicional requerida: {additional_quantity_needed}'
            })

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(cantidad_entregada__lte=models.F('cantidad_solicitada')),
                name='cantidad_entregada_no_mayor_que_solicitada'
            )
        ]


class Donacion(models.Model):

    fecha_donacion = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora en que se realizó la donación'
    )
    observaciones = models.TextField(
        blank=True,
        null=True,
        help_text='Observaciones adicionales sobre la donación'
    )
    donante = models.ForeignKey(
        'Donante',
        on_delete=models.CASCADE,
        related_name='donaciones',
        help_text='Donante que realizó la donación'
    )

    class Meta:
        verbose_name = 'Donación'
        verbose_name_plural = 'Donaciones'
        ordering = ['-fecha_donacion']


class Donante(models.Model):
    class TipoDonante(models.TextChoices):
        EMPRESA = 'empresa', 'Empresa'
        PARTICULAR = 'particular', 'Particular'
        ORGANIZACION = 'organizacion', 'Organización'

    nombre = models.CharField(max_length=100)
    tipo_donante = models.CharField(
        max_length=50,
        choices=TipoDonante.choices,
    )
    telefono = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    canal_donacion = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Canal a través del cual se realizó la donación (ej. email, teléfono, etc.)'
    )
    verificado = models.BooleanField(
        default=False,
        help_text='Indica si el donante ha sido verificado por la organización'
    )

    def __str__(self):
        return f"{self.nombre} - {self.telefono} - ({self.pk})"


class Entrega(models.Model):
    solicitud = models.OneToOneField(
        'Solicitud',
        on_delete=models.CASCADE,
        related_name='entrega',
        help_text='Solicitud a la que pertenece la entrega'
    )
    fecha = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora en que se realizó la entrega de la solicitud'
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
        help_text='Observaciones adicionales sobre la entrega de la solicitud'
    )


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


class Medicamento(models.Model):
    nombre_comercial = models.CharField(
        max_length=100,
        help_text='Nombre comercial del medicamento'
    )
    concentracion = models.CharField(
        max_length=100,
        help_text='Concentración del medicamento (ej. 500mg, 250mg, etc.)'
    )
    forma_farmaceutica = models.CharField(
        max_length=100,
        help_text='Presentación del medicamento (ej. tableta, jarabe, etc.)'
    )
    condiciones_almacenamiento = models.TextField(
        help_text='Condiciones de almacenamiento del medicamento (ej. temperatura, humedad, etc.)'
    )

    class Meta:
        verbose_name = 'Medicamento'
        verbose_name_plural = 'Medicamentos'
        ordering = ['nombre_comercial']

    def __str__(self):
        return f"{self.nombre_comercial} - {self.forma_farmaceutica} ({self.pk})"


class MedicamentoDonado(models.Model):
    class Estado(models.TextChoices):
        DISPONIBLE = 'disponible', 'Disponible'
        RESERVADO = 'reservado', 'Reservado'
        ENTREGADO = 'entregado', 'Entregado'
        VENCIDO = 'vencido', 'Vencido'


    donacion = models.ForeignKey(
        Donacion,
        on_delete=models.CASCADE,
        related_name='medicamentos_donados',
        help_text='Donación a la que pertenece el medicamento'
    )
    medicamento = models.ForeignKey(
        Medicamento,
        on_delete=models.CASCADE,
        related_name='medicamentos_donados',
        help_text='Medicamento donado'
    )
    fecha_vencimiento = models.DateField(
        help_text='Fecha de vencimiento del medicamento'
    )
    lote = models.CharField(
        max_length=50,
        help_text='Número de lote del medicamento'
    )
    cantidad = models.PositiveIntegerField(
        default=0,
        help_text='Cantidad disponible del medicamento'
    )
    fecha_ingreso = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora en que se ingresó el medicamento al sistema'
    )
    estado = models.CharField(
        max_length=50,
        choices=Estado.choices,
        default=Estado.DISPONIBLE,
        help_text='Estado del medicamento (ej. disponible, reservado, entregado, vencido)'
    )

    class Meta:
        verbose_name = 'Medicamento Donado'
        verbose_name_plural = 'Medicamentos Donados'


class Solicitante(models.Model):
    nombre = models.CharField(
        max_length=100,
        help_text='Nombre del solicitante'
    )
    documento = models.CharField(
        max_length=50,
        help_text='Número de documento del solicitante (ej. DNI, pasaporte, etc.)'
    )
    telegram_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text='ID de Telegram del solicitante (opcional)'
    )
    telefono = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        help_text='Teléfono de contacto del solicitante'
    )
    direccion_beneficiario = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='Dirección del beneficiario de la solicitud (si es diferente al solicitante)'
    )
    edad = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text='Edad del solicitante (opcional)'
    )
    fecha_registro = models.DateTimeField(
        auto_now_add=True,
        help_text='Fecha y hora en que se registró el solicitante'
    )

    def __str__(self):
        return f"{self.nombre} - CC {self.documento} - Tel. {self.telefono} - ({self.pk})"


class Solicitud(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        ACEPTADA = 'aceptada', 'Aceptada'
        RECHAZADA = 'rechazada', 'Rechazada'
        CANCELADA = 'cancelada', 'Cancelada'

    class Prioridad(models.TextChoices):
        ALTA = 'alta', 'Alta'
        MEDIA = 'media', 'Media'
        BAJA = 'baja', 'Baja'

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
        help_text='Fecha y hora en que se realizó la solicitud'
    )
    prioridad = models.CharField(
        max_length=50,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
        help_text='Prioridad de la solicitud (ej. alta, media, baja)'
    )
    estado = models.CharField(
        max_length=50,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        help_text='Estado de la solicitud (ej. pendiente, aceptada, rechazada)'
    )
    observaciones = models.TextField(
        blank=True,
        null=True,
        help_text='Observaciones adicionales sobre la solicitud'
    )

    class Meta:
        verbose_name = 'Solicitud'
        verbose_name_plural = 'Solicitudes'
        ordering = ['-fecha']

