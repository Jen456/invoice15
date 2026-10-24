"""Archivos que dejan de usarse: la imagen del código de barras de un producto borrado (también en borrados en bloque)."""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.pos.models import Product


@receiver(post_delete, sender=Product, dispatch_uid='fpa_borrar_codigo_barras')
def borrar_codigo_barras(sender, instance, **kwargs):
    if instance.barcode and instance.barcode.name:
        almacen, nombre = instance.barcode.storage, instance.barcode.name
        transaction.on_commit(lambda: almacen.delete(nombre))
