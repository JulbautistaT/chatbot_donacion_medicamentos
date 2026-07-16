from django.contrib import admin
from django.contrib.auth.models import Group
from stock import models as stock_models
from stock.actions import solicitud as solicitud_actions
from stock.actions import plantilla_pdf as pdf_actions


class AdminConAyuda(admin.ModelAdmin):
    DESCRIPCION = ""
    QUE_PUEDE_HACER = []
    ACCIONES = []
    CONSIDERACIONES = []

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["descripcion"] = self.DESCRIPCION
        extra_context["que_puede_hacer"] = self.QUE_PUEDE_HACER
        extra_context["acciones"] = self.ACCIONES
        extra_context["consideraciones"] = self.CONSIDERACIONES
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(stock_models.DetalleSolicitud)
class DetalleSolicitudAdmin(AdminConAyuda):
    list_display = ('solicitud', 'medicamento','tipo_presentacion' ,'cantidad_entregada')
    search_fields = ('solicitud__solicitante__nombre', 'medicamento__nombre_comercial')
    list_filter = ('solicitud', 'medicamento')
    raw_id_fields = ('solicitud', 'medicamento')

    def has_add_permission(self, request):
        return False

    DESCRIPCION = (
        "Aquí se muestra el detalle de los medicamentos asociados a cada solicitud. "
        "Cada registro indica qué medicamento fue solicitado y la cantidad entregada."
    )
    QUE_PUEDE_HACER = [
        "Consultar los medicamentos asociados a una solicitud.",
        "Ver las cantidades entregadas para cada medicamento."
    ]
    ACCIONES = ["Eliminar registros seleccionados."]
    CONSIDERACIONES = [
        "La información de esta sección se genera automáticamente a partir de las solicitudes registradas en el sistema.",
        "No se recomienda eliminar registros manualmente salvo en casos excepcionales."
    ]


@admin.register(stock_models.Entrega)
class EntregaAdmin(AdminConAyuda):
    list_display = ('solicitud', 'fecha', 'persona_que_entrega', 'acta_generada', 'observaciones')
    search_fields = ('persona_que_entrega', 'observaciones')
    list_filter = ('fecha', 'acta_generada',)
    raw_id_fields = ('solicitud',)
    actions = ['generar_acta']

    @admin.action(description='Generar acta de entrega (PDF)')
    def generar_acta(self, request, queryset):
        pendientes = queryset.filter(acta_generada=False)
        if not pendientes.exists():
            self.message_user(
                request,
                "Todas las entregas seleccionadas ya tienen un acta generada.",
                level='warning'
            )
            return
        solicitudes = stock_models.Solicitud.objects.filter(entrega__in=pendientes)
        response = pdf_actions.generar_acta_entrega(solicitudes)

        solicitudes.update(estado=stock_models.Solicitud.Estado.ENTREGADA)
        pendientes.update(acta_generada=True)
        return response

    def has_add_permission(self, request):
        return False

    DESCRIPCION = (
        "Aquí se registran automáticamente y se consultan las entregas de medicamentos realizadas "
        "a los solicitante. Cada entrega conserva información sobre la solicitud asociada, "
        "la fecha de entrega, la persona responsable y las observaciones registradas."
    )
    QUE_PUEDE_HACER = [
        "Consultar las entregas registradas en el sistema.",
        "Ver quién realizó una entrega determinada.",
        "Consultar la fecha y las observaciones de cada entrega."
    ]
    ACCIONES = [
        "Generar plantilla de entrega en PDF.",
        "Eliminar entregas seleccionadas."
    ]
    CONSIDERACIONES = [
        "Las entregas se generan automáticamente desde el proceso de gestión de solicitudes.",
        "No es posible crear entregas manualmente desde esta sección.",
        "Las actas generadas deben conservarse como soporte físico de la entrega realizada, ya que requiere la firma del usuario.",
        "El sistema evita generar actas duplicadas para una misma entrega.",
        "No se recomienda eliminar entregas salvo en casos excepcionales.",
    ]


@admin.register(stock_models.Medicamento)
class MedicamentoAdmin(AdminConAyuda):
    list_display = ('nombre_comercial', 'concentracion')
    search_fields = ('nombre_comercial', 'concentracion')

    DESCRIPCION = (
        "Aquí se administran los medicamentos registrados en el sistema. "
        "Para cada medicamento se almacena su nombre comercial y concentración, "
        "información utilizada en el inventario y en las solicitudes de medicamentos."
    )
    QUE_PUEDE_HACER = [
        "Consultar los medicamentos registrados en el sistema.",
        "Buscar medicamentos por nombre comercial.",
        "Registrar nuevos medicamentos.",
        "Modificar la información de medicamentos existentes."
    ]
    ACCIONES = ["Eliminar medicamentos seleccionados."]
    CONSIDERACIONES = [
        "Antes de registrar un medicamento, verifique que no exista previamente en el sistema.",
        "Mantenga actualizada la información de nombre comercial y concentración.",
        "No se recomienda eliminar medicamentos que tengan relación con solicitudes o registros históricos."
    ]


@admin.register(stock_models.Solicitante)
class SolicitanteAdmin(AdminConAyuda):
    list_display = ('nombre', 'documento', 'telefono', 'direccion_beneficiario','fecha_registro', 'verificado')
    search_fields = ('nombre', 'documento')

    DESCRIPCION = (
        "Aquí se administran los solicitante registrados en el sistema. "
        "Cada solicitante conserva información personal y de contacto utilizada "
        "para la gestión de solicitudes y comunicaciones."
    )
    QUE_PUEDE_HACER = [
        "Consultar los solicitante registrados.",
        "Buscar solicitante por nombre o documento.",
        "Registrar nuevos beneficiarios.",
        "Modificar la información de solicitante existentes."
    ]
    ACCIONES = ["Eliminar solicitante seleccionados."]
    CONSIDERACIONES = [
        "Verifique cuidadosamente la información de contacto antes de guardarla.",
        "Los datos registrados podrán utilizarse para la gestión de solicitudes.",
        "No se recomienda eliminar solicitante que tengan solicitudes asociadas.",
        "Si un solicitante es registrado manualmente desde esta sección, no podrá vincular posteriormente su cuenta de Telegram utilizando el mismo número de documento. En ese caso, deberá eliminarse el registro y permitir que el usuario se registre nuevamente desde el chatbot."
    ]


class DetalleSolicitudInline(admin.TabularInline):
    model = stock_models.DetalleSolicitud
    extra = 1
    autocomplete_fields = ['medicamento']

    fields = (
        'medicamento',
        'tipo_presentacion',
        'cantidad_entregada',
    )


class EntregaInline(admin.TabularInline):
    model = stock_models.Entrega
    max_num = 1
    extra = 0


class FormulaInline(admin.TabularInline):
    model = stock_models.Formula
    extra = 1
    readonly_fields = ('texto_ocr',)
    fields = ('archivo_formula', 'texto_ocr')


@admin.register(stock_models.Solicitud)
class SolicitudAdmin(AdminConAyuda):
    list_display = ('solicitante', 'fecha', 'estado', 'observaciones', 'notificada_aceptacion',
    'notificada_rechazo')
    search_fields = ('solicitante__nombre', 'observaciones')
    list_filter = ('estado', 'fecha', 'notificada_aceptacion','notificada_rechazo', )
    raw_id_fields = ('solicitante',)
    inlines = [FormulaInline, DetalleSolicitudInline, EntregaInline]
    actions = ['download_requests_info', 'notificar_solicitudes_aceptadas', 'notificar_solicitudes_rechazadas' ]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        if obj.estado == stock_models.Solicitud.Estado.ACEPTADA:
            stock_models.Entrega.objects.get_or_create(
                solicitud=obj
            )


    @admin.action(description='Descargar información de solicitudes')
    def download_requests_info(self, request, queryset):
        if queryset.exists():
            return solicitud_actions.download_requests_info(self, request, queryset)
        else:
            self.message_user(request, "No hay solicitudes seleccionadas.", level='warning')

    @admin.action(description='Notificar por Telegram (solicitudes ACEPTADAS)')
    def notificar_solicitudes_aceptadas(self, request, queryset):

        solicitudes_validas = queryset.filter(
            estado=stock_models.Solicitud.Estado.ACEPTADA,
            solicitante__telegram_id__isnull=False,
            notificada_aceptacion=False
        ).exclude(
            solicitante__telegram_id=''
        )

        ya_notificadas = queryset.filter(
            estado=stock_models.Solicitud.Estado.ACEPTADA,
            notificada_aceptacion=True
        ).count()

        total = solicitudes_validas.count()

        if total == 0:
            self.message_user(
                request,
                "No hay solicitudes aceptadas pendientes de notificación.",
                level='warning'
            )
            return

        solicitud_actions.notificar_solicitudes_aceptadas(
            self,
            request,
            solicitudes_validas
        )

        mensaje = f"{total} solicitantes notificados correctamente."

        if ya_notificadas:
            mensaje += f" ({ya_notificadas} ya estaban notificadas y fueron omitidas)."

        self.message_user(
            request,
            mensaje,
            level='success'
        )

    @admin.action(description='Notificar por Telegram (solicitudes RECHAZADAS)')
    def notificar_solicitudes_rechazadas(self, request, queryset):

        solicitudes_validas = queryset.filter(
            estado=stock_models.Solicitud.Estado.RECHAZADA,
            solicitante__telegram_id__isnull=False,
            notificada_rechazo=False
        ).exclude(
            solicitante__telegram_id=''
        )

        ya_notificadas = queryset.filter(
            estado=stock_models.Solicitud.Estado.RECHAZADA,
            notificada_rechazo=True
        ).count()

        total = solicitudes_validas.count()

        if total == 0:
            self.message_user(
                request,
                "No hay solicitudes rechazadas pendientes de notificación.",
                level='warning'
            )
            return

        solicitud_actions.notificar_solicitudes_rechazadas(
            self,
            request,
            solicitudes_validas
        )

        mensaje = f"{total} solicitantes notificados correctamente."

        if ya_notificadas:
            mensaje += f" ({ya_notificadas} ya estaban notificadas y fueron omitidas)."

        self.message_user(
            request,
            mensaje,
            level='success'
        )

    DESCRIPCION = (
        "Aquí se administran las solicitudes de medicamentos registradas en el sistema. "
        "Cada solicitud contiene información del solicitante, su estado, "
        "medicamentos solicitados y documentos asociados."
    )
    QUE_PUEDE_HACER = [
        "Consultar las solicitudes registradas en el sistema.",
        "Modificar la información de solicitudes existentes.",
        "Consultar los medicamentos, fórmulas médicas y entregas asociadas a cada solicitud.",
        "Registrar nuevas solicitudes cuando sea necesario."
    ]
    ACCIONES = [
        "Descargar información de solicitudes en formato CSV.",
        "Enviar notificaciones masivas por Telegram a solicitantes con solicitudes aceptadas.",
        "Eliminar solicitudes seleccionadas."
    ]
    CONSIDERACIONES = [
        "Verifique cuidadosamente y actualice la información antes de cambiar el estado de una solicitud.",
        "Las notificaciones por Telegram solo se enviarán a las solicitudes aceptadas.",
        "Solo las solicitudes aceptadas podrán generar registros de entrega y actas de entrega.",
        "La información descargada en formato CSV puede utilizarse para seguimiento y auditoría."
    ]


@admin.register(stock_models.Formula)
class SolicitudFormulaAdmin(AdminConAyuda):
    list_display = ('solicitud', 'archivo_formula', 'tiene_ocr')
    search_fields = ('solicitud__solicitante__nombre',)
    raw_id_fields = ('solicitud',)
    readonly_fields = ('texto_ocr',)

    @admin.display(boolean=True, description='OCR extraído')
    def tiene_ocr(self, obj):
        return bool(obj.texto_ocr)

    def has_add_permission(self, request):
        return False

    DESCRIPCION = (
        "Aquí se almacenan automáticamente las fórmulas médicas adjuntadas por los usuarios "
        "en sus solicitudes. Para cada fórmula se conserva el archivo original, la solicitud "
        "asociada y el texto extraído automáticamente mediante reconocimiento de caracteres (OCR)."
    )
    QUE_PUEDE_HACER = [
        "Consultar las fórmulas registradas en el sistema.",
        "Visualizar el archivo de la fórmula médica adjunta.",
        "Ver el texto extraído automáticamente de la fórmula mediante OCR.",
        "Verificar si una fórmula fue procesada correctamente."
    ]
    ACCIONES = ["Eliminar formulas seleccionadas."]
    CONSIDERACIONES = [
        "Las fórmulas se registran automáticamente cuando un usuario adjunta una imagen en su solicitud.",
        "No es posible registrar fórmulas manualmente desde esta sección.",
        "No se recomienda eliminar fórmulas salvo en casos excepcionales.",
        "La calidad de la imagen puede afectar la precisión del texto extraído mediante OCR."
    ]


# No mostrar Group
admin.site.unregister(Group)

# Personalización visual del admin
_original_get_app_list = admin.site.get_app_list

def custom_get_app_list(request, app_label=None):
    app_list = _original_get_app_list(request, app_label)
    ocultar = {'django_celery_beat', 'django_celery_results'}
    app_list = [app for app in app_list if app['app_label'] not in ocultar]
    orden = {'stock': 1, 'anuncios': 2, 'politicas': 3, 'auth': 4}
    app_list.sort(key=lambda app: orden.get(app['app_label'], 99))
    return app_list

admin.site.get_app_list = custom_get_app_list

admin.site.site_header = "Panel de Control - Donación de Medicamentos"
admin.site.site_title = "Administración"
admin.site.index_title = "Sistema de Gestión"