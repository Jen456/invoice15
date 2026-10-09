"""Modelo base y gestor de los datos que pertenecen a una empresa."""
from django.db import models
from django.db.models import Expression

from core.tenancy.context import TenantScopeError, current_company_id, is_platform_scope, require_company


class CurrentCompanyId(Expression):
    """Identificador de la empresa activa, resuelto al compilar la consulta.

    Las QuerySets que se construyen al importar (p. ej. el queryset de un
    ModelChoiceField) guardan esta expresión y no un valor: al ejecutarse en una
    petición usan la empresa de esa petición, y sin empresa activa fallan.
    """
    output_field = models.IntegerField()

    def as_sql(self, compiler, connection):
        company_id = current_company_id()
        if company_id is None:
            raise TenantScopeError('Consulta de datos de empresa sin empresa activa')
        return '%s', [company_id]

    def get_group_by_cols(self):
        return []


class TenantManager(models.Manager):
    """Gestor por defecto: solo ve las filas de la empresa activa (falla cerrado)."""

    def get_queryset(self):
        return super().get_queryset().filter(company_id=CurrentCompanyId())


class TenantModel(models.Model):
    company = models.ForeignKey('pos.Company', on_delete=models.PROTECT, editable=False,
                                related_name='+', verbose_name='Empresa')

    objects = TenantManager()
    all_companies = models.Manager()  # acceso explícito a todas las empresas (plataforma, migraciones)

    class Meta:
        abstract = True
        base_manager_name = 'all_companies'

    def tenant_fk_fields(self):
        for field in self._meta.concrete_fields:
            if field.is_relation and field.many_to_one and field.name != 'company' \
                    and issubclass(field.related_model, TenantModel):
                yield field

    def check_tenant_references(self):
        """Toda referencia a otro dato de empresa debe ser de la misma empresa.

        Cubre las vistas que asignan `<campo>_id` directamente desde el POST.
        """
        for field in self.tenant_fk_fields():
            value = getattr(self, field.attname)
            if value is None:
                continue
            exists = field.related_model.all_companies.filter(pk=value, company_id=self.company_id).exists()
            if not exists:
                raise TenantScopeError(f'{self._meta.label}.{field.name} apunta a un dato de otra empresa')

    def save(self, *args, **kwargs):
        if self.company_id is None:
            self.company = require_company()
        elif not is_platform_scope() and self.company_id != current_company_id():
            raise TenantScopeError(f'{self._meta.label} pertenece a otra empresa')
        self.check_tenant_references()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not is_platform_scope() and self.company_id != current_company_id():
            raise TenantScopeError(f'{self._meta.label} pertenece a otra empresa')
        return super().delete(*args, **kwargs)
