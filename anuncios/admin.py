from django.contrib import admin
from anuncios import models as anuncios_models
from anuncios.actions import anuncio as anuncio_actions


@admin.register(anuncios_models.Anuncio)
class AnuncioAdmin(admin.ModelAdmin):
    list_display = (
        'medicamento',
        'cantidad',
        'fecha_anuncio',
        'activo'
    )

    search_fields = (
        'medicamento__nombre_comercial',
        'notas_adicionales'
    )

    list_filter = (
        'activo',
        'fecha_anuncio'
    )

    autocomplete_fields = ['medicamento']

    actions = [
        'enviar_anuncio_masivo',
        'desactivar_anuncios'
    ]

    @admin.action(description='Enviar anuncio masivo')
    def enviar_anuncio_masivo(self, request, queryset):
        anuncios_validos = queryset.filter(activo=True)

        if not anuncios_validos.exists():
            self.message_user(
                request,
                "No hay anuncios activos seleccionados.",
                level='warning'
            )
            return

        anuncio_actions.enviar_anuncio_masivo(
            self,
            request,
            anuncios_validos
        )

    @admin.action(description='Desactivar anuncios seleccionados')
    def desactivar_anuncios(self, request, queryset):
        updated = queryset.update(activo=False)

        self.message_user(
            request,
            f"{updated} anuncios desactivados correctamente."
        )