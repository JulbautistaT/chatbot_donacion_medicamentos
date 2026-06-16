from django.contrib import admin
from .models import PoliticaDatos

@admin.register(PoliticaDatos)
class PoliticaDatosAdmin(admin.ModelAdmin):
    """Admin configuration for the PoliticaDatos model."""
    list_display = [
        'version', 
        'titulo', 
        'fecha_vigencia', 
        'es_activa'
        ]
    
    list_filter = [
        'es_activa', 
        'fecha_vigencia'
        
        ]
    readonly_fields = [
        'fecha_creacion'
        ]

    change_list_template = "admin/change_list.html"

    DESCRIPCION = (
        "Aquí se administra la política de tratamiento de datos mostrada a los usuarios en el chatbot (Chat de Telegram). El usuario deberá aceptarla para continuar utilizando el servicio."
    )

    QUE_PUEDE_HACER = [
        "Consultar las políticas registradas en el sistema.",
        "Ver la versión actualmente vigente (marcada como Activa)",
        "Crear nuevas versiones de la política de datos.",
        "Modificar el contenido de una política existente -Lo más recomendable para actualizar información."

    ]

    ACCIONES = [
        "Eliminar Política de Datos seleccionada/s"
    ]

    CONSIDERACIONES = [
        "Debe existir al menos una política activa para que el chatbot funcione correctamente.",
        "Antes de desactivar una política, asegúrese de que exista otra versión activa."        
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
    