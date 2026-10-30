from django.conf import settings
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from core.tenancy.models_base import CurrentCompanyId, TenantManager, TenantModel  # noqa: F401 (API pública)

# Roles de empresa: grupos plantilla gestionados por la plataforma.
ROLE_OWNER = 'Propietario'
ROLE_ADMIN = 'Administrador'
ROLE_ACCOUNTANT = 'Contador'
ROLE_SELLER = 'Vendedor'
ROLE_READONLY = 'Consulta'
ROLE_CLIENT = 'Cliente'
COMPANY_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_ACCOUNTANT, ROLE_SELLER, ROLE_READONLY, ROLE_CLIENT)
STAFF_ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_ACCOUNTANT, ROLE_SELLER, ROLE_READONLY)


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, company__is_active=True)


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships',
                             verbose_name='Usuario')
    company = models.ForeignKey('pos.Company', on_delete=models.CASCADE, related_name='memberships',
                                verbose_name='Empresa')
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name='memberships', verbose_name='Rol')
    is_active = models.BooleanField(default=True, verbose_name='Activa')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='Fecha de alta')

    objects = MembershipQuerySet.as_manager()

    class Meta:
        verbose_name = 'Membresía'
        verbose_name_plural = 'Membresías'
        constraints = [models.UniqueConstraint(fields=['user', 'company'], name='membership_user_company_unica')]
        default_permissions = ()
        permissions = (
            ('view_membership', 'Can view Membresía'),
            ('add_membership', 'Can add Membresía'),
            ('change_membership', 'Can change Membresía'),
            ('delete_membership', 'Can delete Membresía'),
        )

    def __str__(self):
        return f'{self.user} @ {self.company} ({self.group})'

    @property
    def is_client_role(self):
        return self.group.name == ROLE_CLIENT


class AuditLog(models.Model):
    ACTIONS = (
        ('login', 'Inicio de sesión'),
        ('company_switch', 'Cambio de empresa'),
        ('platform_enter', 'Entrada de la plataforma en una empresa'),
        ('membership_add', 'Alta de membresía'),
        ('membership_change', 'Cambio de membresía'),
        ('membership_remove', 'Baja de membresía'),
        ('company_create', 'Alta de empresa'),
        ('company_change', 'Cambio de empresa (datos)'),
        ('signup', 'Registro de empresa'),
        ('email_verified', 'Correo confirmado'),
        ('signup_resend', 'Reenvío del enlace de confirmación'),
        ('plan_payment_start', 'Inicio de pago del plan'),
        ('plan_manual', 'Activación manual de plan'),
        ('plan_period_change', 'Cambio de período de suscripción'),
        ('plan_invoice_request', 'Solicitud de factura de la suscripción'),
        ('plan_company_added', 'Empresa agregada al plan multiempresa'),
        ('billing_setup_step', 'Configuración de facturación: paso guardado'),
        ('billing_point_change', 'Configuración de facturación: establecimiento o punto'),
        ('billing_sequence_change', 'Configuración de facturación: numeración'),
        ('billing_setup_confirm', 'Configuración de facturación confirmada'),
        ('ride_regenerado', 'RIDE regenerado desde el XML autorizado'),
        # Fase contable: Proformas
        ('proforma_enviada', 'Proforma enviada por correo'),
        ('proforma_marcada_enviada', 'Proforma marcada como enviada'),
        ('proforma_aceptada', 'Proforma aceptada'),
        ('proforma_rechazada', 'Proforma rechazada'),
        ('proforma_anulada', 'Proforma anulada'),
        ('proforma_eliminada', 'Borrador de proforma eliminado'),
        ('proforma_facturada', 'Proforma facturada'),
        ('proforma_venta_eliminada', 'Proforma liberada al eliminar su factura'),
        # Fase contable: Compras
        ('purchase_complete', 'Compra: datos del comprobante completados'),
        ('purchase_debt_adjust', 'Compra: cuenta por pagar ajustada al total con IVA'),
        ('purchase_delete', 'Compra eliminada (stock revertido)'),
        ('debt_payment_delete', 'Pago de cuenta por pagar eliminado'),
        ('debt_delete', 'Cuenta por pagar eliminada'),
        ('provider_type_fill', 'Proveedores: tipo de identificación completado por orden'),
        # Fase contable: Ventas
        ('comprobante_anulado_sri', 'Comprobante marcado como anulado en el SRI'),
        ('retencion_recibida_registro', 'Registro de retención recibida'),
        ('retencion_recibida_anulacion', 'Anulación del registro de una retención recibida'),
        ('cxc_cobro_eliminado', 'Cobro eliminado de una cuenta por cobrar'),
        ('regularizacion_datos_origen', 'Regularización de datos de origen (orden con decisión)'),
        # Fase contable: catálogo de retenciones (D0)
        ('catalogo_vigencia_nueva', 'Nueva vigencia en el catálogo de retenciones'),
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='Fecha')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='+', verbose_name='Usuario')
    company = models.ForeignKey('pos.Company', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+', verbose_name='Empresa')
    action = models.CharField(max_length=40, choices=ACTIONS, verbose_name='Acción')
    detail = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Detalle')
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP')

    class Meta:
        verbose_name = 'Registro de auditoría'
        verbose_name_plural = 'Registros de auditoría'
        ordering = ('-created_at',)
        default_permissions = ('view',)

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.get_action_display()}'


def audit(request, action, company=None, **detail):
    from core.security.session import client_ip
    user = getattr(request, 'user', None) if request is not None else None
    AuditLog.objects.create(
        user=user if user is not None and user.is_authenticated else None,
        company=company, action=action, detail=detail,
        ip=(client_ip(request) or None) if request is not None else None,
    )
