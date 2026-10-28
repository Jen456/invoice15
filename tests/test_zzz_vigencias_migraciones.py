"""Migraciones 0014 y 0015 del catálogo de retenciones de ida y vuelta (0013 ↔ 0015) con MigrationExecutor.

Cambiar el esquema hacia atrás no se puede dentro de la transacción de una prueba en SQLite: usa transacciones reales
(transaction=True), que al terminar vacían la base de pruebas, por eso se llama test_zzz_* y se ejecuta al final. En
PostgreSQL las test_zz_* anteriores ya vaciaron la base: el catálogo se recarga con la función de 0004. Cada prueba
vuelve a la hoja con restaurar(), que no depende de que la prueba haya llegado al final.
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


def aplicada(migracion):
    return migracion in MigrationExecutor(connection).loader.applied_migrations


def restaurar():
    """Vuelve a la hoja con el catálogo de 0004 desde donde haya quedado la prueba: un fallo a mitad no queda tapado por
    la guardia de la vuelta de 0015 (vigencias posteriores) ni por la de su ida (310 o 332E editados)."""
    if aplicada(DATOS):
        apps = MigrationExecutor(connection).loader.project_state([DATOS]).apps
        apps.get_model('comprobantes', 'CodigoRetencion').objects.filter(vigente_desde__gt=CORTE).delete()
    M0004.cargar(migrar(ANTES), None)
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


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
        # Vacía (PostgreSQL, tras las test_zz_*) o, si la base llega como la dejaron las migraciones, la de 0004 al deshacer
        # 0015 y 0014.
        assert catalogo(apps) in ([], sorted(M0004.CATALOGO))
        M0004.cargar(apps, None)   # idempotente

        apps = migrar(DATOS)
        assert vigencias(apps, '310') == [(None, date(2026, 7, 31), '1.00', False), (CORTE, None, '1.00', True)]
        assert vigencias(apps, '332E') == [(None, date(2026, 7, 31), '0.00', True), (CORTE, None, '0.00', True)]
        Codigo = apps.get_model('comprobantes', 'CodigoRetencion')
        nueva_310 = Codigo.objects.get(impuesto='1', codigo='310', vigente_desde=CORTE)
        # El cierre del 310 de 0004 movido por fuera del panel (allí es de solo lectura): la vuelta lo reabre igual.
        Codigo.objects.filter(impuesto='1', codigo='310', vigente_desde__isnull=True).update(vigente_hasta=date(2026, 6, 30))

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
        restaurar()


GUARDIAS = {
    '310 con otro porcentaje': ('310', {'porcentaje': Decimal('2.00')}),
    '310 no disponible': ('310', {'activo': False}),
    '310 de porcentaje fijo': ('310', {'porcentaje_editable': False}),
    '332E con otro concepto': ('332E', {'concepto': 'Valores entregados a los socios (editado en el panel)'}),
    '332E con otro porcentaje': ('332E', {'porcentaje': Decimal('1.00')}),
    '332E borrado': ('332E', None),
}


@pytest.mark.parametrize('codigo, cambios', GUARDIAS.values(), ids=list(GUARDIAS))
def test_guardia_de_0015_no_pisa_lo_editado_en_el_panel(codigo, cambios):
    """0015 no se aplica (ni queda registrada) si el 310 o el 332E no tienen los valores de 0004, y no toca el catálogo."""
    try:
        M0004.cargar(migrar(ANTES), None)
        apps = migrar(ESQUEMA)
        editada = apps.get_model('comprobantes', 'CodigoRetencion').objects.filter(impuesto='1', codigo=codigo)
        if cambios:
            editada.update(**cambios)
        else:
            editada.delete()
        antes = catalogo(apps)
        with pytest.raises(RuntimeError, match=f'el código de renta {codigo} no tiene los valores que cargó 0004'):
            migrar(DATOS)
        assert not aplicada(DATOS) and aplicada(ESQUEMA)
        assert catalogo(apps) == antes   # sin fechas a medias: la migración es atómica
        Codigo = apps.get_model('comprobantes', 'CodigoRetencion')
        assert not Codigo.objects.exclude(vigente_desde__isnull=True, vigente_hasta__isnull=True).exists()
    finally:
        restaurar()
