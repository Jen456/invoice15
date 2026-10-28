"""Proveedores sin los datos del ATS: informe y, con decisión escrita, tipo de identificación y de sujeto (§3.9).

    python manage.py proveedores_incompletos [--empresa ID | --todas] [--csv RUTA]
    python manage.py proveedores_incompletos --empresa ID --aplicar --decision "motivo y quién autorizó" --csv RUTA

Ensayo por defecto (no escribe nada). Con --aplicar llena SOLO tipo_identificacion y tipo_sujeto cuando no hay ambigüedad
(RUC válido de 13 dígitos o cédula válida de 10: proveedores.sugerencia). Nunca toca la parte relacionada ni el número.
Un registro de auditoría provider_type_fill por empresa, con la decisión y la ruta del informe. No se ejecuta en
producción en esta fase.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.pos.management.commands import _ensayo

COLUMNAS = ['empresa', 'proveedor', 'nombre', 'identificacion', 'faltantes', 'tipo_identificacion', 'tipo_sujeto', 'accion']


class Command(BaseCommand):
    help = 'Informe de proveedores sin datos del ATS; con --aplicar (y --decision, --csv) llena el tipo de identificación.'

    def add_arguments(self, parser):
        _ensayo.agregar_opciones(parser)

    def handle(self, *args, **opciones):
        from core.pos.models import Provider
        from core.pos.proveedores import sugerencia
        from core.tenancy.context import company_context
        from core.tenancy.models import audit
        _ensayo.comprobar(opciones)
        aplicar = opciones['aplicar']
        lista = _ensayo.empresas(opciones)
        informe = _ensayo.Informe(opciones['csv'], COLUMNAS)
        total = llenados = 0
        try:
            for empresa in lista:
                with company_context(empresa):
                    incompletos = [p for p in Provider.objects.order_by('pk') if p.faltantes_ats()]
                    cambios = []
                    for proveedor in incompletos:
                        propuesta = sugerencia(proveedor) if not proveedor.tipo_identificacion else None
                        if propuesta:
                            cambios.append((proveedor, propuesta))
                            accion = 'llenado' if aplicar else 'se llenaría'
                        else:
                            accion = 'sin cambios: revisar a mano'
                        informe.agregar({'empresa': empresa.pk, 'proveedor': proveedor.pk, 'nombre': proveedor.name,
                                         'identificacion': proveedor.ruc,
                                         'faltantes': ', '.join(c for c, _ in proveedor.faltantes_ats()),
                                         'tipo_identificacion': (propuesta or {}).get('tipo_identificacion', ''),
                                         'tipo_sujeto': (propuesta or {}).get('tipo_sujeto', ''), 'accion': accion})
                    total += len(incompletos)
                    if aplicar and cambios:
                        with transaction.atomic():
                            ids = []
                            for proveedor, propuesta in cambios:
                                filas = Provider.objects.filter(pk=proveedor.pk, tipo_identificacion='').update(
                                    tipo_identificacion=propuesta['tipo_identificacion'],
                                    tipo_sujeto=proveedor.tipo_sujeto or propuesta['tipo_sujeto'])
                                if filas:
                                    ids.append(proveedor.pk)
                            if ids:
                                audit(None, 'provider_type_fill', empresa, proveedores=ids, cantidad=len(ids),
                                      decision=opciones['decision'].strip(), informe=str(opciones['csv']))
                            llenados += len(ids)
                    self.stdout.write(f'Empresa {empresa.pk} ({empresa.business_name}): {len(incompletos)} proveedores '
                                      f'incompletos; {len(cambios)} sin ambigüedad.')
        finally:
            informe.cerrar()
        modo = f'aplicado: {llenados} proveedores completados' if aplicar else 'ensayo: no se cambió nada'
        self.stdout.write(f'Total: {total} proveedores incompletos ({modo}).')
