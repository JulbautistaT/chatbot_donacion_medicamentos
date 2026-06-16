from django.contrib import admin
from django.contrib.auth.models import Group
from stock import models as stock_models
from stock.actions import solicitud as solicitud_actions
from stock.actions import plantilla_pdf as pdf_actions


@admin.register(stock_models.DetalleSolicitud)
class DetalleSolicitudAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'medicamento', 'cantidad_entregada')
    search_fields = ('solicitud__solicitante__nombre', 'medicamento__nombre_comercial')
    list_filter = ('solicitud', 'medicamento')
    raw_id_fields = ('solicitud', 'medicamento')

    def has_add_permission(self, request):
        return False

    change_list_template = "admin/change_list.html"

    DESCRIPCION = (
        "Aquí se muestra el detalle de los medicamentos asociados a cada solicitud. "
        "Cada registro indica qué medicamento fue solicitado y la cantidad entregada."
    )

    QUE_PUEDE_HACER = [
        "Consultar los medicamentos asociados a una solicitud.",
        "Ver las cantidades entregadas para cada medicamento.",
        "Buscar información específica mediante filtros y búsquedas."
    ]

    ACCIONES = [
        "Eliminar registros seleccionados."
    ]

    CONSIDERACIONES = [
        "La información de esta sección se genera automáticamente a partir de las solicitudes registradas en el sistema.",
        "No se recomienda crear registros manualmente salvo en casos excepcionales."
    ]

    def changelist_view(self, request, extra_context=None):

        extra_context = extra_context or {}

        extra_context["descripcion"] = self.DESCRIPCION
        extra_context["que_puede_hacer"] = self.QUE_PUEDE_HACER
        extra_context["acciones"] = self.ACCIONES
        extra_context["consideraciones"] = self.CONSIDERACIONES

        return super().changelist_view(
            request,
            extra_context=extra_context
        )


@admin.register(stock_models.Entrega)
class EntregaAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'fecha', 'persona_que_entrega', 'observaciones')
    search_fields = ('persona_que_entrega', 'observaciones')
    list_filter = ('fecha',)          
    raw_id_fields = ('solicitud',)    

    actions = ['generar_acta']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        solicitud = obj.solicitud
        solicitud.estado = stock_models.Solicitud.Estado.ENTREGADA
        solicitud.save()

    @admin.action(description='Generar acta de entrega (PDF)')
    def generar_acta(self, request, queryset):
        solicitudes = stock_models.Solicitud.objects.filter(
            entrega__in=queryset
        )
        return pdf_actions.generar_acta_entrega(solicitudes)



@admin.register(stock_models.Medicamento)
class MedicamentoAdmin(admin.ModelAdmin):
    list_display = ('nombre_comercial', 'concentracion')
    search_fields = ('nombre_comercial', 'concentracion')


@admin.register(stock_models.Solicitante)
class SolicitanteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'documento', 'telefono', 'direccion_beneficiario', 'edad', 'fecha_registro', 'verificado')
    search_fields = ('nombre', 'documento')
    list_filter = ('verificado',)


class DetalleSolicitudInline(admin.TabularInline):
    model = stock_models.DetalleSolicitud
    extra = 1
    raw_id_fields = ['medicamento']
    autocomplete_fields = ['medicamento']


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
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ('solicitante', 'fecha', 'prioridad', 'estado', 'observaciones')
    search_fields = ('solicitante__nombre', 'observaciones')
    list_filter = ('prioridad', 'estado', 'fecha')
    raw_id_fields = ('solicitante',)
    inlines = [FormulaInline, DetalleSolicitudInline, EntregaInline]

    actions = ['download_requests_info', 'notificar_solicitudes_aceptadas']

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
            solicitante__telegram_id__isnull=False
        ).exclude(solicitante__telegram_id='')

        total = solicitudes_validas.count()

        if total == 0:
            self.message_user(request, "No hay solicitudes válidas.", level='warning')
            return

        solicitud_actions.notificar_solicitudes_aceptadas(
            self, request, solicitudes_validas
        )


        self.message_user(
            request,
            f"{total} solicitantes notificados correctamente.",
            level='success'
        )




@admin.register(stock_models.Formula)
class SolicitudFormulaAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'archivo_formula', 'tiene_ocr')
    search_fields = ('solicitud__solicitante__nombre',)
    raw_id_fields = ('solicitud',)
    readonly_fields = ('texto_ocr',)

    @admin.display(boolean=True, description='OCR extraído')
    def tiene_ocr(self, obj):
        return bool(obj.texto_ocr)


# No mostrar Group 
admin.site.unregister(Group)

# Personalizacion visual del admin

_original_get_app_list = admin.site.get_app_list

def custom_get_app_list(request, app_label=None):
    app_list = _original_get_app_list(request, app_label)

    ocultar = {
        'django_celery_beat',
        'django_celery_results',
    }

    app_list = [
        app for app in app_list
        if app['app_label'] not in ocultar
    ]

    orden = {
        'stock': 1,
        'anuncios': 2,
        'politicas': 3,
        'auth': 4,
    }

    app_list.sort(
        key=lambda app: orden.get(app['app_label'], 99)
    )

    return app_list

admin.site.get_app_list = custom_get_app_list

admin.site.site_header = "Panel de Control - Donación de Medicamentos"
admin.site.site_title = "Administración"
admin.site.index_title = "Sistema de Gestión"