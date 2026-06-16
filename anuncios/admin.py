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


    change_list_template = "admin/change_list.html"

    DESCRIPCION = (
        "Aquí se administran los avisos masivos de medicamentos próximos a vencer o para difundir información importante relacionada con medicamentos."
    )

    QUE_PUEDE_HACER = [
        "Consultar los avisos registrados en el sistema.",
        "Crear nuevos avisos para los usuarios del chatbot.",
        "Modificar el contenido de avisos existentes.",
        "Ver cuáles avisos se encuentran activos o inactivos."
    ]

    ACCIONES = [
        "Enviar anuncio masivo.",
        "Desactivar anuncios seleccionados.",
        "Eliminar anuncios seleccionados."
    ]

    CONSIDERACIONES = [
        "Antes de enviar anuncios masivos, asegúrese de que el o los avisos se encuentren activos.",
        "Revise el contenido del aviso antes de enviarlo a los usuarios.",
        "Desactive o elimine los avisos que ya no sean necesarios."
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