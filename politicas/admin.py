from django.contrib import admin
from .models import PoliticaDatos

@admin.register(PoliticaDatos)
class PoliticaDatosAdmin(admin.ModelAdmin):
    """Admin configuration for the PoliticaDatos model."""
    list_display = ['version', 'titulo', 'fecha_vigencia', 'es_activa']
    list_filter = ['es_activa', 'fecha_vigencia']
    readonly_fields = ['fecha_creacion']

