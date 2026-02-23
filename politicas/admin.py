from django.contrib import admin
from .models import PoliticaDatos, AceptacionPolitica

@admin.register(PoliticaDatos)
class PoliticaDatosAdmin(admin.ModelAdmin):
    list_display = ['version', 'titulo', 'fecha_vigencia', 'es_activa']
    list_filter = ['es_activa', 'fecha_vigencia']
    readonly_fields = ['fecha_creacion']

@admin.register(AceptacionPolitica)
class AceptacionPoliticaAdmin(admin.ModelAdmin):
    list_display = [
        'telegram_chat_id', 'politica', 'fecha_consentimiento', 
        'hora_consentimiento', 'acepto', 'fecha_hora_completa'
    ]
    list_filter = ['politica', 'fecha_consentimiento', 'acepto']
    search_fields = ['telegram_chat_id']
    readonly_fields = ['fecha_consentimiento', 'hora_consentimiento', 'fecha_hora_completa']
