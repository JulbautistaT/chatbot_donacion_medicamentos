from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from .models import DetalleSolicitud, MedicamentoDonado
import logging

logger = logging.getLogger(__name__)


def create_log_entry(obj, action_flag, change_message, user=None):
    """Create a LogEntry for model changes."""
    if user is None:
        # Get or create a system user for automated changes
        user, _ = User.objects.get_or_create(
            username='system_signal',
            defaults={
                'first_name': 'Sistema',
                'last_name': 'Automatico',
                'is_staff': False,
                'is_active': False
            }
        )
    
    LogEntry.objects.create(
        user_id=user.pk,
        content_type_id=ContentType.objects.get_for_model(obj).pk,
        object_id=obj.pk,
        object_repr=str(obj),
        action_flag=action_flag,
        change_message=change_message
    )


@receiver(pre_save, sender=DetalleSolicitud)
def store_previous_cantidad_entregada(sender, instance, **kwargs):
    """Store the previous cantidad_entregada value before saving."""
    if instance.pk:
        try:
            previous = DetalleSolicitud.objects.get(pk=instance.pk)
            instance._previous_cantidad_entregada = previous.cantidad_entregada
        except DetalleSolicitud.DoesNotExist:
            instance._previous_cantidad_entregada = 0
    else:
        instance._previous_cantidad_entregada = 0


@receiver(post_save, sender=DetalleSolicitud)
def update_medicamento_donado_quantity(sender, instance, created, **kwargs):
    """
    Update MedicamentoDonado quantity when DetalleSolicitud cantidad_entregada changes.
    Decreases the quantity of available MedicamentoDonado when cantidad_entregada increases.
    """
    # Validate that cantidad_entregada doesn't exceed cantidad_solicitada
    if instance.cantidad_entregada > instance.cantidad_solicitada:
        logger.error(f"DetalleSolicitud {instance.pk}: cantidad_entregada ({instance.cantidad_entregada}) "
                    f"exceeds cantidad_solicitada ({instance.cantidad_solicitada}). No inventory changes will be made.")
        return
    
    # Get the previous cantidad_entregada value
    previous_cantidad_entregada = getattr(instance, '_previous_cantidad_entregada', 0)
    current_cantidad_entregada = instance.cantidad_entregada
    
    # Calculate the difference
    cantidad_difference = current_cantidad_entregada - previous_cantidad_entregada
    
    if cantidad_difference != 0:
        logger.info(f"DetalleSolicitud {instance.pk}: cantidad_entregada changed from {previous_cantidad_entregada} to {current_cantidad_entregada}")
        
        with transaction.atomic():
            # Find available MedicamentoDonado for this medicamento
            medicamento_donado_query = MedicamentoDonado.objects.filter(
                medicamento=instance.medicamento,
                estado=MedicamentoDonado.Estado.DISPONIBLE,
                cantidad__gt=0
            ).order_by('fecha_vencimiento')  # Use oldest first (FIFO)
            
            remaining_to_discount = cantidad_difference
            
            for medicamento_donado_obj in medicamento_donado_query:
                if remaining_to_discount <= 0:
                    break
                
                if cantidad_difference > 0:  # Increasing cantidad_entregada - discount from inventory
                    discount_amount = min(remaining_to_discount, medicamento_donado_obj.cantidad)
                    old_quantity = medicamento_donado_obj.cantidad
                    old_estado = medicamento_donado_obj.estado
                    
                    medicamento_donado_obj.cantidad -= discount_amount
                    remaining_to_discount -= discount_amount
                    
                    # Update estado if quantity reaches 0
                    if medicamento_donado_obj.cantidad == 0:
                        medicamento_donado_obj.estado = MedicamentoDonado.Estado.ENTREGADO
                    
                    medicamento_donado_obj.save()
                    
                    # Create log entry for the change
                    change_message = (
                        f"Cantidad reducida por entrega automática: {old_quantity} → {medicamento_donado_obj.cantidad} "
                        f"(-{discount_amount}). DetalleSolicitud ID: {instance.pk}"
                    )
                    if old_estado != medicamento_donado_obj.estado:
                        change_message += f". Estado cambiado: {old_estado} → {medicamento_donado_obj.estado}"
                    
                    create_log_entry(medicamento_donado_obj, CHANGE, change_message)
                    
                    logger.info(f"MedicamentoDonado {medicamento_donado_obj.pk}: quantity decreased by {discount_amount}, new quantity: {medicamento_donado_obj.cantidad}")
                
                elif cantidad_difference < 0:  # Decreasing cantidad_entregada - return to inventory
                    return_amount = min(abs(remaining_to_discount), abs(cantidad_difference))
                    old_quantity = medicamento_donado_obj.cantidad
                    old_estado = medicamento_donado_obj.estado
                    
                    medicamento_donado_obj.cantidad += return_amount
                    remaining_to_discount += return_amount
                    
                    # Update estado back to available if it was entregado
                    if medicamento_donado_obj.estado == MedicamentoDonado.Estado.ENTREGADO and medicamento_donado_obj.cantidad > 0:
                        medicamento_donado_obj.estado = MedicamentoDonado.Estado.DISPONIBLE
                    
                    medicamento_donado_obj.save()
                    
                    # Create log entry for the change
                    change_message = (
                        f"Cantidad restaurada por devolución automática: {old_quantity} → {medicamento_donado_obj.cantidad} "
                        f"(+{return_amount}). DetalleSolicitud ID: {instance.pk}"
                    )
                    if old_estado != medicamento_donado_obj.estado:
                        change_message += f". Estado cambiado: {old_estado} → {medicamento_donado_obj.estado}"
                    
                    create_log_entry(medicamento_donado_obj, CHANGE, change_message)
                    
                    logger.info(f"MedicamentoDonado {medicamento_donado_obj.pk}: quantity increased by {return_amount}, new quantity: {medicamento_donado_obj.cantidad}")
            
            if remaining_to_discount > 0 and cantidad_difference > 0:
                logger.warning(f"Not enough stock available. Remaining to discount: {remaining_to_discount}")
            elif remaining_to_discount < 0:
                logger.warning(f"Could not return all quantity to stock. Remaining to return: {abs(remaining_to_discount)}")