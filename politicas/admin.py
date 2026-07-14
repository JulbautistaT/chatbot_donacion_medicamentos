from django.contrib import admin, messages
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
        "Eliminar Política de Datos seleccionada/s (no aplica a la política activa)"
    ]

    CONSIDERACIONES = [
        "Siempre debe existir exactamente una política activa: el sistema no permite dejar ninguna activa.",
        "Al marcar una política como activa, la que estaba activa se desactiva automáticamente.",
        "No es posible eliminar la política activa; active otra versión antes de eliminarla.",
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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        desactivadas = getattr(obj, 'desactivadas_automaticamente', [])
        if desactivadas:
            versiones = ', '.join(f"v{v}" for v in desactivadas)
            self.message_user(
                request,
                f"⚠️ Se desactivó automáticamente la política {versiones}, ya que solo "
                "puede haber una política activa a la vez.",
                level=messages.WARNING,
            )

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.es_activa:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        if obj.es_activa:
            self.message_user(
                request,
                f"⚠️ No se eliminó la política v{obj.version} porque está activa: "
                "siempre debe existir una política activa. Active otra versión antes "
                "de eliminarla.",
                level=messages.WARNING,
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        activas = list(queryset.filter(es_activa=True))
        if activas:
            versiones = ', '.join(f"v{p.version}" for p in activas)
            self.message_user(
                request,
                f"⚠️ No se eliminó la política {versiones} porque está activa: "
                "siempre debe existir una política activa. Active otra versión antes "
                "de eliminarla.",
                level=messages.WARNING,
            )
        super().delete_queryset(request, queryset.exclude(es_activa=True))
