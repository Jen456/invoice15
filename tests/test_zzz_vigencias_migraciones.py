"""Migraciones 0014 y 0015 del catálogo de retenciones de ida y vuelta (0013 ↔ 0015) con MigrationExecutor.

Cambiar el esquema hacia atrás no se puede dentro de la transacción de una prueba en SQLite: usa transacciones reales
(transaction=True), que al terminar vacían la base de pruebas, por eso se llama test_zzz_* y se ejecuta al final. En
PostgreSQL las test_zz_* anteriores ya vaciaron la base: el catálogo se recarga con la función de 0004.
"""
import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F

from core.tenancy.context import company_context
from tests import helpers

pytestmark = pytest.mark.django_db(transaction=True)
ANTES = ('comprobantes', '0013_modulo_guias')
ESQUEMA = ('comprobantes', '0014_codigoretencion_vigencias')
DATOS = ('comprobantes', '0015_vigencias_res_28')
M0004 = importlib.import_module('core.comprobantes.migrations.0004_catalogo_retenciones')
CORTE = date(2026, 8, 1)


def migrar(destino):
    """Lleva comprobantes a `destino` y devuelve los modelos históricos de ese estado."""
    MigrationExecutor(connection).migrate([destino])
    return MigrationExecutor(connection).loader.project_state([destino]).apps


def catalogo(apps):
    """Filas del catálogo como las tuplas de 0004: (impuesto, código, concepto, %, editable, común, activo, fuente, orden)."""
    return sorted((c.impuesto, c.codigo, c.concepto, f'{c.porcentaje:.2f}', c.porcentaje_editable, c.comun, c.activo, c.fuente,
                   c.orden) for c in apps.get_model('comprobantes', 'CodigoRetencion').objects.all())


def vigencias(apps, codigo):
    Codigo = apps.get_model('comprobantes', 'CodigoRetencion')
    return [(c.vigente_desde, c.vigente_hasta, f'{c.porcentaje:.2f}', c.porcentaje_editable)
            for c in Codigo.objects.filter(impuesto='1', codigo=codigo).order_by(F('vigente_hasta').asc(nulls_last=True))]


def columnas(tabla):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, tabla)}


def retencion_enlazada(fila_pk):
    """Retención con un detalle que apunta a la fila `fila_pk`, como la deja crear() (modelos actuales: esquema de 0015)."""
    from core.comprobantes.models import Retencion, RetencionDetalle
    from core.pos.models import Provider, Purchase, Receipt
    empresa = helpers.crear_empresa('MIGRACION VIGENCIAS', plan=None)
    usuario = helpers.crear_usuario('emisor.migracion.vigencias')
    with company_context(empresa):
        proveedor = Provider.objects.create(name='TRANSPORTES FICTICIOS S.A.', ruc='0990000009001', mobile='0990000009',
                                            email='transportes@example.com', address='Av. Quito 300')
        compra = Purchase.objects.create(number='901', provider=proveedor, subtotal=Decimal('100.00'))
        secuencia = Receipt.objects.create(voucher_type='07', establishment_code='001', issuing_point_code='002', environment_type=2)
        ret = Retencion.objects.create(receipt=secuencia, voucher_number='000000001', voucher_number_full='001-002-000000001',
                                       employee=usuario, environment_type=2, purchase=compra, provider=proveedor,
                                       tipo_identificacion='04', identificacion=proveedor.ruc, razon_social=proveedor.name,
                                       num_doc_sustento='001001000000123', fecha_doc_sustento=date(2026, 10, 27),
                                       aut_doc_sustento='1' * 49, total_retenido=Decimal('1.00'))
        detalle = RetencionDetalle.objects.create(retencion=ret, impuesto='1', codigo='310', concepto='Transporte',
                                                  base_imponible=Decimal('100.00'), porcentaje=Decimal('1.00'),
                                                  valor_retenido=Decimal('1.00'), codigo_catalogo_id=fila_pk)
    return empresa, detalle.pk


def test_ida_y_vuelta_de_0013_a_0015_con_guardias():
    from core.comprobantes.models import RetencionDetalle
    try:
        apps = migrar(ANTES)
        M0004.cargar(apps, None)   # idempotente; en PostgreSQL la base llega vacía
        assert catalogo(apps) == sorted(M0004.CATALOGO)

        # Guardia de 0015: el 310 editado en /plataforma/ no se pisa (0015 no se aplica y el catálogo queda igual).
        apps = migrar(ESQUEMA)
        Codigo = apps.get_model('comprobantes', 'CodigoRetencion')
        Codigo.objects.filter(impuesto='1', codigo='310').update(porcentaje=Decimal('2.00'))
        with pytest.raises(RuntimeError, match='310 no tiene los valores que cargó 0004'):
            migrar(DATOS)
        assert vigencias(apps, '310') == [(None, None, '2.00', True)]
        Codigo.objects.filter(impuesto='1', codigo='310').update(porcentaje=Decimal('1.00'))

        apps = migrar(DATOS)
        assert vigencias(apps, '310') == [(None, date(2026, 7, 31), '1.00', False), (CORTE, None, '1.00', True)]
        assert vigencias(apps, '332E') == [(None, date(2026, 7, 31), '0.00', True), (CORTE, None, '0.00', True)]
        nueva_310 = apps.get_model('comprobantes', 'CodigoRetencion').objects.get(impuesto='1', codigo='310', vigente_desde=CORTE)

        # Vuelta a 0014 con un detalle nuevo enlazado: queda sin fila, las filas nuevas se borran y las de 0004 se reabren.
        empresa, detalle_pk = retencion_enlazada(nueva_310.pk)
        apps = migrar(ESQUEMA)
        with company_context(empresa):
            detalle = RetencionDetalle.objects.get(pk=detalle_pk)
        assert detalle.codigo_catalogo_id is None and detalle.porcentaje == Decimal('1.00')
        assert vigencias(apps, '310') == [(None, None, '1.00', True)] and vigencias(apps, '332E') == [(None, None, '0.00', True)]

        # Y a 0013: exactamente el catálogo de 0004, sin las columnas nuevas y con su unicidad (impuesto, código).
        apps = migrar(ANTES)
        assert catalogo(apps) == sorted(M0004.CATALOGO)
        assert not {'vigente_desde', 'vigente_hasta', 'ayuda'} & columnas('comprobantes_codigoretencion')
        assert 'codigo_catalogo_id' not in columnas('comprobantes_retenciondetalle')
        with pytest.raises(IntegrityError), transaction.atomic():
            apps.get_model('comprobantes', 'CodigoRetencion').objects.create(impuesto='1', codigo='310', concepto='Duplicado',
                                                                             porcentaje=Decimal('1.00'))

        # Otra vez hacia adelante; con una vigencia creada después de 0015, la vuelta se niega a borrarla.
        apps = migrar(DATOS)
        Codigo = apps.get_model('comprobantes', 'CodigoRetencion')
        Codigo.objects.filter(impuesto='1', codigo='310', vigente_desde=CORTE).update(vigente_hasta=date(2026, 12, 31))
        posterior = Codigo.objects.create(impuesto='1', codigo='310', concepto='Posterior', porcentaje=Decimal('0.00'),
                                          vigente_desde=date(2027, 1, 1))
        with pytest.raises(RuntimeError, match='vigencias creadas después de esta migración \\(códigos 310\\)'):
            migrar(ESQUEMA)
        posterior.delete()
        Codigo.objects.filter(impuesto='1', codigo='310', vigente_desde=CORTE).update(vigente_hasta=None)
        assert vigencias(migrar(ESQUEMA), '310') == [(None, None, '1.00', True)]
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
