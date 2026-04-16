from django.contrib import admin
from stock import models as stock_models
from stock.actions import solicitud as solicitud_actions


class MedicamentoDonadoInline(admin.TabularInline):
    model = stock_models.MedicamentoDonado
    extra = 1
    raw_id_fields = ['medicamento', 'donacion']


@admin.register(stock_models.Donacion)
class DonacionAdmin(admin.ModelAdmin):
    list_display = ('fecha_donacion', 'donante', 'observaciones')
    search_fields = ('donante__nombre', 'observaciones')
    list_filter = ('fecha_donacion',)
    raw_id_fields = ('donante',)
    inlines = [MedicamentoDonadoInline]


@admin.register(stock_models.DetalleSolicitud)
class DetalleSolicitudAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'medicamento', 'cantidad_solicitada', 'cantidad_entregada')
    search_fields = ('solicitud__solicitante__nombre', 'medicamento__nombre_comercial')
    list_filter = ('solicitud', 'medicamento')
    raw_id_fields = ('solicitud', 'medicamento')


@admin.register(stock_models.Donante)
class DonanteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_donante', 'telefono', 'email', 'verificado')
    search_fields = ('nombre', 'email')
    list_filter = ('tipo_donante', 'verificado')


@admin.register(stock_models.Entrega)
class EntregaAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'fecha', 'persona_que_entrega', 'observaciones')
    search_fields = ('persona_que_entrega', 'observaciones')
    list_filter = ('fecha',)
    raw_id_fields = ('solicitud',)


@admin.register(stock_models.Medicamento)
class MedicamentoAdmin(admin.ModelAdmin):
    list_display = ('nombre_comercial', 'concentracion', 'forma_farmaceutica', 'condiciones_almacenamiento')
    search_fields = ('nombre_comercial', 'concentracion', 'forma_farmaceutica')



@admin.register(stock_models.MedicamentoDonado)
class MedicamentoDonadoAdmin(admin.ModelAdmin):
    list_display = ('donacion', 'medicamento', 'fecha_vencimiento', 'lote', 'cantidad', 'estado')
    search_fields = ('medicamento__nombre_comercial', 'lote')
    list_filter = ('estado', 'fecha_vencimiento')
    raw_id_fields = ('donacion', 'medicamento')


@admin.register(stock_models.Solicitante)
class SolicitanteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'documento', 'telefono', 'direccion_beneficiario', 'edad', 'fecha_registro', 'verificado')
    search_fields = ('nombre', 'documento')
    list_filter = ('verificado',)


class DetalleSolicitudInline(admin.TabularInline):
    model = stock_models.DetalleSolicitud
    extra = 1
    raw_id_fields = ['medicamento']


class EntregaInline(admin.TabularInline):
    model = stock_models.Entrega
    extra = 1


class FormulaInline(admin.TabularInline):
    model = stock_models.Formula
    extra = 1
    readonly_fields = ('texto_ocr',)
    fields = ('archivo_formula', 'texto_ocr')


@admin.register(stock_models.Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ('solicitante', 'solicitud_propia', 'fecha', 'prioridad', 'estado', 'observaciones')
    search_fields = ('solicitante__nombre', 'observaciones')
    list_filter = ('prioridad', 'solicitud_propia', 'estado', 'fecha')
    raw_id_fields = ('solicitante',)
    inlines = [FormulaInline, DetalleSolicitudInline, EntregaInline]

    actions = ['download_requests_info', 'notificar_solicitudes_aceptadas']

    @admin.action(description='Descargar información de solicitudes')
    def download_requests_info(self, request, queryset):
        """Custom action to download requests information."""
        if queryset.exists():
            return solicitud_actions.download_requests_info(self, request, queryset)
        else:
            self.message_user(request, "No requests selected for download.", level='warning')

    @admin.action(description='Notificar por Telegram a solicitantes (solicitudes ACEPTADAS)')
    def notificar_solicitudes_aceptadas(self, request, queryset):
        """Sends a Telegram message to each solicitante with an ACEPTADA solicitud."""
        solicitud_actions.notificar_solicitudes_aceptadas(self, request, queryset)


@admin.register(stock_models.Formula)
class SolicitudFormulaAdmin(admin.ModelAdmin):
    list_display = ('solicitud', 'archivo_formula', 'tiene_ocr')
    search_fields = ('solicitud__solicitante__nombre',)
    raw_id_fields = ('solicitud',)
    readonly_fields = ('texto_ocr',)

    @admin.display(boolean=True, description='OCR extraído')
    def tiene_ocr(self, obj):
        return bool(obj.texto_ocr)
