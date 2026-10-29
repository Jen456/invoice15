"""Señales de Proformas: al eliminar una venta (solo se puede si no salió al SRI), su proforma vuelve a «aceptada» o
«enviada». pre_delete corre dentro de la transacción del borrado y antes del SET NULL de `Proforma.venta`."""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from core.pos.models import Sale


@receiver(pre_delete, sender=Sale, dispatch_uid='fpa_proforma_libera_venta')
def liberar_proforma(sender, instance, **kwargs):
    from core.proformas import servicios
    servicios.liberar_por_venta_eliminada(instance)
