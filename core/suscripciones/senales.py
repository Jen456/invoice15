"""Límites del plan gratuito y devolución de reservas de cupo.

Los límites se comprueban al crear el registro (pre_save), así cubren
formularios, importación desde Excel y cualquier otra vía. Con un plan pagado
vigente no hay límites de inventario.
"""
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.pos.models import CreditNote, Product, Provider, Purchase, Sale


class LimitePlanGratuito(Exception):
    """Se alcanzó un límite del plan gratuito (mensaje para el usuario)."""


def _comprobar(instance, campo, contar, texto):
    from core.suscripciones.servicios import limites_gratuito, tiene_plan
    company = instance.company
    if tiene_plan(company):
        return
    limite = limites_gratuito().get(campo)
    if limite is not None and contar() >= limite:
        raise LimitePlanGratuito(f'El plan gratuito permite hasta {limite} {texto}. '
                                 'Activa un plan en «Plan y pagos» para registrar más.')


@receiver(pre_save, sender=Product, dispatch_uid='fpa_limite_productos')
def limitar_productos(sender, instance, raw=False, **kwargs):
    if raw or instance.pk is not None:
        return
    _comprobar(instance, 'product_limit', lambda: Product.all_companies.filter(company_id=instance.company_id).count(),
               'productos')


@receiver(pre_save, sender=Provider, dispatch_uid='fpa_limite_proveedores')
def limitar_proveedores(sender, instance, raw=False, **kwargs):
    if raw or instance.pk is not None:
        return
    _comprobar(instance, 'provider_limit', lambda: Provider.all_companies.filter(company_id=instance.company_id).count(),
               'proveedores')


@receiver(pre_save, sender=Purchase, dispatch_uid='fpa_limite_compras')
def limitar_compras(sender, instance, raw=False, **kwargs):
    if raw or instance.pk is not None:
        return
    inicio_mes = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _comprobar(instance, 'purchase_limit_month',
               lambda: Purchase.all_companies.filter(company_id=instance.company_id, created_at__gte=inicio_mes).count(),
               'compras por mes')


@receiver(post_delete, sender=Sale, dispatch_uid='fpa_cupo_venta_borrada')
@receiver(post_delete, sender=CreditNote, dispatch_uid='fpa_cupo_nota_borrada')
def devolver_reserva(sender, instance, **kwargs):
    from core.suscripciones.cupo import liberar_de_comprobante
    liberar_de_comprobante(instance)
