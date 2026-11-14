"""Esquema del bloque 2 del cierre contable (libro diario y apertura, contable/bloque-2-especificacion.md, «Modelo de datos del
bloque»): lo que garantizan la base y las guardas de modelo por sí solas, sin los servicios.

- Cada restricción de la base (CHECK y UNIQUE, también las parciales) de las 19 tablas y de las dos columnas de `Cuenta`,
  una a una: la base rechaza la fila que la viola, con el nombre de la restricción, y admite la que queda fuera de la
  condición de una parcial. Una prueba comprueba que ninguna restricción declarada se queda sin su caso. En PostgreSQL
  algunas se prueban con los disparadores apagados (en un punto de guardado que se deshace): el disparador rechaza antes
  lo mismo y taparía la restricción.
- Guardas de modelo del libro (`Asiento`, `LineaAsiento`, `EventoApertura`, `Contabilizacion` confirmada).
- Recorridos ast: ninguna FK de los modelos de los bloques 2 a 6 hacia el usuario ni hacia la operación; `bulk_create` y
  `bulk_update` solo en MODULOS_CON_LOTES; `escritura_interna` solo en diario.py.
- Vocabularios que crecen sin `choices` ni CHECK cerrado (decisión común 14), permisos declarados y repartidos, acciones de
  auditoría del bloque y borrar al usuario autor.

Corre en SQLite y en PostgreSQL (los disparadores tienen además tests/test_zz_libro_inmutable_pg.py)."""
import ast
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone

from core.contabilidad import lotes
from core.contabilidad.modelos_libro import LibroInmutable, escritura_interna
from core.contabilidad.models import (AplicacionAuxiliar, Asiento, AuxiliarApertura, CoberturaPeriodo, Contabilizacion, Cuenta,
                                      EventoApertura, LineaAsiento, VinculoHistorico)
from core.security.models import Module
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog)
from core.user.models import User
from tests import ayudas_contables as ac

pytestmark = pytest.mark.django_db

BASE = Path(settings.BASE_DIR)
ASIENTO = 'contabilidad_asiento'
_n = count(1)


@pytest.fixture
def f(empresa):
    """Una fila válida de cada tabla del bloque en la empresa A, con la empresa activa durante la prueba."""
    filas = ac.filas_de_cada_tabla(empresa)
    with company_context(empresa):
        yield SimpleNamespace(**filas, empresa=empresa)


# ---------------------------------------------------------------- ayudas de los casos

def upd(obj, **cambios):
    """UPDATE por el QuerySet (sin pasar por save): para las tablas que admiten cambios."""
    return type(obj).objects.filter(pk=obj.pk).update(**cambios)


def copia(obj, lote=False, **cambios):
    """Inserta una copia de la fila con esos cambios (por nombre de campo; una FK admite la instancia). Con `lote`, por
    `bulk_create`: sin las guardas de `save()`, para que sea la base la que decida."""
    modelo = type(obj)
    datos = {c.attname: getattr(obj, c.attname) for c in modelo._meta.concrete_fields if not c.primary_key}
    for nombre, valor in cambios.items():
        campo = modelo._meta.get_field(nombre)
        datos[campo.attname] = valor.pk if isinstance(valor, models.Model) else valor
    nuevo = modelo(**datos)
    if lote:
        return modelo.objects.bulk_create([nuevo])[0]
    nuevo.save()
    return nuevo


def asiento_nuevo(f, **cambios):
    """Un asiento abierto copiado del de la base, con número, clave y origen propios (para que solo choque lo que el caso
    busca). En PostgreSQL solo vive dentro del punto de guardado del caso, que siempre se deshace."""
    n = next(_n)
    datos = dict(sellado=False, numero=900 + n, clave=None, origen_id=10_000 + n)
    datos.update(cambios)
    return copia(f.asiento, lote=True, **datos)


def linea_nueva(f, asiento, **cambios):
    datos = dict(asiento=asiento, orden=1)
    datos.update(cambios)
    return copia(f.linea_asiento, **datos)


def apertura_confirmada(f, **cambios):
    datos = dict(estado='confirmada', confirmado_en=timezone.now(), asiento=f.asiento, total_debe=Decimal('100.00'),
                 total_haber=Decimal('100.00'), clave=ac.clave('apertura'))
    datos.update(cambios)
    return copia(f.apertura, **datos)


def anulada(**cambios):
    return dict(estado='anulado', anulado_en=timezone.now(), motivo_anulacion='Anulado en la prueba', **cambios)


def otro_documento(**cambios):
    return dict(documento_numero=f'001-001-{900_000 + next(_n):09d}', **cambios)


def inventario(f, **cambios):
    datos = dict(naturaleza='inventario', producto_id=77, cantidad=1, costo_unitario=Decimal('2.000000'), tercero_nombre='',
                 tercero_identificacion='', documento_numero='', documento_tipo='')
    datos.update(cambios)
    return copia(f.auxiliar, **datos)


def tributario(f, **cambios):
    datos = dict(naturaleza='tributario', concepto='otro', periodo=date(2025, 12, 1), casillero='1', tercero_nombre='',
                 tercero_identificacion='', documento_numero='', documento_tipo='')
    datos.update(cambios)
    return copia(f.auxiliar, **datos)


def dos_veces(accion):
    def ambas(f):
        accion(f)
        accion(f)
    return ambas


def asiento_de_apertura(f, origen_id):
    return asiento_nuevo(f, tipo='apertura', origen_tipo='apertura', origen_id=origen_id, evento='confirmacion')


def dos_lineas_con_el_mismo_orden(f):
    abierto = asiento_nuevo(f)
    linea_nueva(f, abierto)
    linea_nueva(f, abierto)


def dos_sustitutas_vivas(f, segunda):
    vigente = apertura_confirmada(f)
    upd(f.apertura, sustituye=vigente)   # el borrador sustituye a la confirmada
    segunda(vigente)


def otra_apertura_tras_reversar(f):
    vieja = ac.asiento_directo(f.empresa, [(f.cuentas['caja'], 5, 0), (f.cuentas['capital'], 0, 5)], tipo='apertura',
                               origen=('apertura', 1, 'confirmacion'))
    ac.reverso_directo(f.empresa, vieja)
    asiento_de_apertura(f, 2)   # la reversada ya no cuenta


# (restricción, acción que la viola, tablas cuyos disparadores la taparían en PostgreSQL)
VIOLACIONES = [
    # Cuenta (bloque 1, columnas del bloque 2)
    ('cuenta_clase_valida', lambda f: upd(f.cuentas['caja'], clase='otra'), ()),
    ('cuenta_auxiliar_solo_movimiento', lambda f: upd(f.cuentas['activo'], auxiliar='cliente'), ()),
    # InicioContable
    ('inicio_contable_unico', lambda f: copia(f.inicio), ()),
    ('inicio_contable_desde_tras_corte', lambda f: upd(f.inicio, contabilidad_desde=date(2025, 12, 31)), ()),
    ('inicio_contable_saldos_sin_historial', lambda f: upd(f.inicio, historial_desde=date(2026, 1, 1)), ()),
    ('inicio_contable_historial_coherente', lambda f: upd(f.inicio, modalidad='historial'), ()),   # sin fechas
    ('inicio_contable_historial_coherente', lambda f: upd(f.inicio, modalidad='historial', historial_desde=date(2026, 1, 2),
                                                          historial_hasta=date(2026, 3, 31)), ()),
    ('inicio_contable_historial_coherente', lambda f: upd(f.inicio, modalidad='historial', historial_desde=date(2026, 1, 1),
                                                          historial_hasta=date(2025, 12, 31)), ()),
    # EjercicioContable
    ('ejercicio_anio_unico', lambda f: copia(f.ejercicio, ultimo_numero=0), ()),
    ('ejercicio_anio_valido', lambda f: upd(f.ejercicio, anio=1999), ()),
    ('ejercicio_anio_valido', lambda f: upd(f.ejercicio, anio=2101), ()),
    ('ejercicio_cerrado_con_fecha', lambda f: upd(f.ejercicio, estado='cerrado'), ()),
    ('ejercicio_cerrado_con_fecha', lambda f: upd(f.ejercicio, cerrado_en=timezone.now()), ()),
    # PeriodoContable
    ('periodo_mes_unico', lambda f: copia(f.periodo), ()),
    ('periodo_mes_valido', lambda f: upd(f.periodo, mes=13), ()),
    ('periodo_mes_valido', lambda f: upd(f.periodo, mes=0), ()),
    # Asiento
    ('asiento_numero_unico', lambda f: asiento_nuevo(f, numero=f.asiento.numero), ()),
    ('asiento_origen_vigente_unico', lambda f: asiento_nuevo(f, origen_id=f.asiento.origen_id), ()),
    ('asiento_apertura_unica', lambda f: (asiento_de_apertura(f, 1), asiento_de_apertura(f, 2)), ()),
    ('asiento_un_reverso', dos_veces(lambda f: asiento_nuevo(f, tipo='reverso', reversa_de=f.asiento, origen_id=f.asiento.origen_id)),
     ()),
    ('asiento_clave_unica', lambda f: asiento_nuevo(f, clave=f.asiento.clave), ()),
    ('asiento_cuadrado', lambda f: asiento_nuevo(f, total_haber=Decimal('90.00')), ()),
    ('asiento_cuadrado', lambda f: asiento_nuevo(f, total_debe=0, total_haber=0), ()),
    ('asiento_cuadrado', lambda f: asiento_nuevo(f, lineas_n=1), ()),
    ('asiento_reverso_con_original', lambda f: asiento_nuevo(f, tipo='reverso'), ()),
    ('asiento_reverso_con_original', lambda f: asiento_nuevo(f, tipo='manual', reversa_de=f.asiento), ()),
    ('asiento_reverso_no_se_reversa', lambda f: asiento_nuevo(f, tipo='reverso', reversa_de=f.asiento, reversado_por=f.asiento,
                                                              reversado_en=timezone.now()), (ASIENTO,)),
    ('asiento_reversado_con_fecha', lambda f: asiento_nuevo(f, reversado_por=f.asiento), (ASIENTO,)),
    ('asiento_reversado_con_fecha', lambda f: asiento_nuevo(f, reversado_en=timezone.now()), (ASIENTO,)),
    ('asiento_motivo_obligatorio', lambda f: asiento_nuevo(f, tipo='manual', motivo=''), ()),
    ('asiento_motivo_obligatorio', lambda f: asiento_nuevo(f, tipo='ajuste', motivo=''), ()),
    ('asiento_origen_obligatorio', lambda f: asiento_nuevo(f, tipo='origen', origen_id=None), ()),
    ('asiento_origen_obligatorio', lambda f: asiento_nuevo(f, tipo='apertura', origen_tipo=''), ()),
    ('asiento_origen_obligatorio', lambda f: asiento_nuevo(f, tipo='cierre', evento=''), ()),
    ('asiento_con_autor', lambda f: asiento_nuevo(f, creado_por_nombre=''), ()),
    # LineaAsiento (en un asiento abierto nuevo)
    ('linea_asiento_orden_unico', dos_lineas_con_el_mismo_orden, ()),
    ('linea_asiento_un_lado', lambda f: linea_nueva(f, asiento_nuevo(f), debe=Decimal('10'), haber=Decimal('10')), ()),
    ('linea_asiento_un_lado', lambda f: linea_nueva(f, asiento_nuevo(f), debe=0, haber=0), ()),
    ('linea_asiento_un_lado', lambda f: linea_nueva(f, asiento_nuevo(f), debe=Decimal('-5'), haber=0), ()),
    ('linea_asiento_tercero_con_tipo', lambda f: linea_nueva(f, asiento_nuevo(f), tercero_id=5), ()),
    # SaldoCuentaMes
    ('saldo_cuenta_mes_unico', lambda f: copia(f.saldo), ()),
    # Sin violar a la vez el desglose (que el debe o el haber no bajen de lo de apertura y cierre).
    ('saldo_cuenta_mes_no_negativo', lambda f: upd(f.saldo, apertura_debe=Decimal('-1')), ()),
    ('saldo_cuenta_mes_no_negativo', lambda f: upd(f.saldo, cierre_haber=Decimal('-1')), ()),
    ('saldo_cuenta_mes_desglose_debe', lambda f: upd(f.saldo, apertura_debe=Decimal('60'), cierre_debe=Decimal('50')), ()),
    ('saldo_cuenta_mes_desglose_haber', lambda f: upd(f.saldo, apertura_haber=Decimal('1')), ()),
    # Contabilizacion
    ('expediente_origen_unico', lambda f: copia(f.expediente), ()),
    ('expediente_clave_unica', lambda f: (upd(f.expediente, clave='expediente-0001'),
                                          copia(f.expediente, origen_id=None, clave='expediente-0001')), ()),
    ('expediente_asiento_unico', lambda f: (upd(f.expediente, asiento=f.asiento),
                                            copia(f.expediente, origen_id=None, asiento=f.asiento)), ()),
    ('expediente_estado_valido', lambda f: upd(f.expediente, estado='inventado'), ()),
    ('expediente_confirmado_con_asiento', lambda f: upd(f.expediente, estado='confirmado'), ()),
    ('expediente_sin_efecto_con_causa', lambda f: upd(f.expediente, estado='sin_efecto'), ()),
    # RegistroClave
    ('registro_clave_unica', lambda f: copia(f.registro_clave), ()),
    # Apertura
    ('apertura_clave_unica', lambda f: copia(f.apertura, estado='descartada', motivo='Copia descartada'), ()),
    ('apertura_clave_confirmacion_unica', lambda f: (upd(f.apertura, clave_confirmacion='confirmar-0001'), copia(
        f.apertura, estado='descartada', motivo='Copia', clave=ac.clave(), clave_confirmacion='confirmar-0001')), ()),
    ('apertura_una_confirmada', dos_veces(apertura_confirmada), ()),
    ('apertura_una_en_preparacion', lambda f: copia(f.apertura, clave=ac.clave()), ()),
    ('apertura_una_en_preparacion', lambda f: copia(f.apertura, estado='en_revision', clave=ac.clave()), ()),
    ('apertura_una_sustituta', lambda f: dos_sustitutas_vivas(f, lambda vigente: apertura_confirmada(
        f, estado='reversada', sustituye=vigente, asiento_reverso=f.asiento, motivo='Reversada en la prueba')), ()),
    ('apertura_moneda_usd', lambda f: upd(f.apertura, moneda='EUR'), ()),
    ('apertura_confirmada_completa', lambda f: upd(f.apertura, estado='confirmada'), ()),
    ('apertura_confirmada_completa', lambda f: upd(f.apertura, estado='confirmada', confirmado_en=timezone.now()), ()),
    ('apertura_confirmada_completa', lambda f: upd(f.apertura, estado='confirmada', confirmado_en=timezone.now(),
                                                   asiento=f.asiento), ()),   # totales nulos
    ('apertura_confirmada_completa', lambda f: upd(f.apertura, estado='confirmada', confirmado_en=timezone.now(),
                                                   asiento=f.asiento, total_debe=Decimal('100'), total_haber=Decimal('90')), ()),
    ('apertura_sin_saldos_declarada', lambda f: upd(f.apertura, sin_saldos=True), ()),
    ('apertura_sin_saldos_declarada', lambda f: upd(f.apertura, sin_saldos=True, fuente='inicio_actividades'), ()),
    ('apertura_cerrada_con_reverso', lambda f: upd(f.apertura, estado='reversada', confirmado_en=timezone.now(), asiento=f.asiento,
                                                   total_debe=Decimal('100'), total_haber=Decimal('100'), motivo='Reverso'), ()),
    ('apertura_cierre_con_motivo', lambda f: upd(f.apertura, estado='descartada'), ()),
    # LineaApertura
    ('linea_apertura_orden_unico', lambda f: copia(f.linea_apertura, cuenta=None), ()),
    ('linea_apertura_cuenta_unica', lambda f: copia(f.linea_apertura, orden=99), ()),
    ('linea_apertura_debe_no_negativo', lambda f: upd(f.linea_apertura, debe=Decimal('-1')), ()),
    ('linea_apertura_haber_no_negativo', lambda f: upd(f.linea_apertura, haber=Decimal('-1')), ()),
    ('linea_apertura_un_lado', lambda f: upd(f.linea_apertura, haber=Decimal('5')), ()),
    ('linea_apertura_retirada_sin_importes', lambda f: upd(f.linea_apertura, retirada=True), ()),
    # ImportacionApertura y RespaldoApertura
    ('importacion_apertura_clave_unica', lambda f: copia(f.importacion_apertura), ()),
    ('respaldo_apertura_clave_unica', lambda f: copia(f.respaldo_apertura), ()),
    # AjusteApertura
    ('ajuste_apertura_numero_unico', lambda f: copia(f.ajuste_apertura, clave=ac.clave()), ()),
    ('ajuste_apertura_clave_unica', lambda f: copia(f.ajuste_apertura, numero=2), ()),
    ('ajuste_apertura_con_motivo', lambda f: upd(f.ajuste_apertura, motivo=''), ()),
    ('ajuste_apertura_reverso_coherente', lambda f: upd(f.ajuste_apertura, estado='reversado'), ()),
    ('ajuste_apertura_reverso_coherente', lambda f: upd(f.ajuste_apertura, asiento_reverso=f.asiento), ()),
    # AuxiliarApertura
    ('auxiliar_apertura_saldo_positivo', lambda f: upd(f.auxiliar, saldo_inicial=0), ()),
    ('auxiliar_apertura_anulado_con_fecha', lambda f: upd(f.auxiliar, estado='anulado', motivo_anulacion='x'), ()),
    ('auxiliar_apertura_anulado_con_fecha', lambda f: upd(f.auxiliar, anulado_en=timezone.now()), ()),
    ('auxiliar_apertura_anulado_con_motivo', lambda f: upd(f.auxiliar, estado='anulado', anulado_en=timezone.now()), ()),
    ('auxiliar_apertura_tercero_con_nombre', lambda f: upd(f.auxiliar, tercero_nombre=''), ()),
    ('auxiliar_apertura_tercero_con_nombre', lambda f: upd(f.auxiliar_proveedor, tercero_nombre=''), ()),
    ('auxiliar_apertura_inventario_completo', lambda f: upd(f.auxiliar_banco, naturaleza='inventario'), ()),
    ('auxiliar_apertura_inventario_completo', lambda f: upd(f.auxiliar_banco, naturaleza='inventario', producto_id=5,
                                                            costo_unitario=1), ()),   # sin cantidad
    ('auxiliar_apertura_inventario_completo', lambda f: upd(f.auxiliar_banco, naturaleza='inventario', producto_id=5,
                                                            cantidad=2), ()),          # sin costo
    ('auxiliar_apertura_tributario_completo', lambda f: upd(f.auxiliar_banco, naturaleza='tributario'), ()),
    ('auxiliar_apertura_tributario_completo', lambda f: upd(f.auxiliar_banco, naturaleza='tributario', concepto='otro'), ()),
    ('auxiliar_apertura_cxc_de_cliente', lambda f: upd(f.auxiliar_proveedor, cxc_id=5), ()),
    ('auxiliar_apertura_cxp_de_proveedor', lambda f: upd(f.auxiliar, cxp_id=5), ()),
    ('auxiliar_apertura_documento_unico', lambda f: copia(f.auxiliar), ()),
    ('auxiliar_apertura_clave_acceso_unica', lambda f: (upd(f.auxiliar, clave_acceso='1' * 49),
                                                        copia(f.auxiliar, clave_acceso='1' * 49, **otro_documento())), ()),
    ('auxiliar_apertura_producto_unico', dos_veces(inventario), ()),
    ('auxiliar_apertura_banco_unico', lambda f: copia(f.auxiliar_banco), ()),
    ('auxiliar_apertura_tributario_unico', dos_veces(tributario), ()),
    ('auxiliar_apertura_cxc_unico', lambda f: (upd(f.auxiliar, cxc_id=11), copia(f.auxiliar, cxc_id=11, **otro_documento())), ()),
    ('auxiliar_apertura_cxp_unico', lambda f: (upd(f.auxiliar_proveedor, cxp_id=12),
                                               copia(f.auxiliar_proveedor, cxp_id=12, **otro_documento())), ()),
    ('auxiliar_apertura_importado_unico', lambda f: (upd(f.auxiliar, documento_importado_id=13),
                                                     copia(f.auxiliar, documento_importado_id=13, **otro_documento())), ()),
    ('auxiliar_apertura_un_sucesor', dos_veces(lambda f: copia(f.auxiliar, antecesor=f.auxiliar, raiz=f.auxiliar,
                                                                **otro_documento())), ()),
    # PartidaBancoApertura
    ('partida_banco_apertura_importe_positivo', lambda f: upd(f.partida_banco, importe=0), ()),
    # AplicacionAuxiliar
    ('aplicacion_auxiliar_clave_unica', lambda f: copia(f.aplicacion), ()),
    ('aplicacion_auxiliar_importe_positivo', lambda f: upd(f.aplicacion, importe=0), ()),
    ('aplicacion_auxiliar_descargo_completo', lambda f: upd(f.aplicacion, tipo='otro_descargo', subtipo='ajuste', nota='x'), ()),
    ('aplicacion_auxiliar_descargo_completo', lambda f: upd(f.aplicacion, tipo='otro_descargo', medio='', nota='x'), ()),
    ('aplicacion_auxiliar_descargo_completo', lambda f: upd(f.aplicacion, tipo='otro_descargo', medio='', subtipo='ajuste'), ()),
    ('aplicacion_auxiliar_anulada_con_fecha', lambda f: upd(f.aplicacion, estado='anulado', motivo_anulacion='x'), ()),
    ('aplicacion_auxiliar_anulada_con_motivo', lambda f: upd(f.aplicacion, estado='anulado', anulado_en=timezone.now()), ()),
    # VinculoHistorico
    ('vinculo_historico_documento_unico', lambda f: copia(f.vinculo_historico, clave=ac.clave()), ()),
    ('vinculo_historico_auxiliar_unico', lambda f: (upd(f.vinculo_historico, destino='auxiliar_apertura', auxiliar=f.auxiliar),
                                                    copia(f.vinculo_historico, clave=ac.clave(), documento_importado_id=2,
                                                          destino='auxiliar_apertura', auxiliar=f.auxiliar)), ()),
    ('vinculo_historico_clave_unica', lambda f: copia(f.vinculo_historico, documento_importado_id=2), ()),
    ('vinculo_historico_destino_auxiliar', lambda f: upd(f.vinculo_historico, destino='auxiliar_apertura'), ()),
    ('vinculo_historico_destino_auxiliar', lambda f: upd(f.vinculo_historico, auxiliar=f.auxiliar), ()),
    # CoberturaPeriodo
    ('cobertura_periodo_unica', lambda f: copia(f.cobertura), ()),
]

# Lo mismo que no viola: lo que queda fuera de la condición de una restricción parcial, o el caso válido de un CHECK.
ADMITIDAS = [
    ('inicio_contable_historial_coherente', lambda f: upd(f.inicio, modalidad='historial', historial_desde=date(2026, 1, 1),
                                                          historial_hasta=date(2026, 3, 31), operaciones_desde=date(2026, 4, 1))),
    ('ejercicio_cerrado_con_fecha', lambda f: upd(f.ejercicio, estado='cerrado', cerrado_en=timezone.now())),
    ('asiento_origen_vigente_unico', lambda f: asiento_nuevo(f, tipo='reverso', reversa_de=f.asiento,
                                                             origen_id=f.asiento.origen_id)),   # el reverso no cuenta
    ('asiento_apertura_unica', otra_apertura_tras_reversar),
    ('asiento_clave_unica', lambda f: (asiento_nuevo(f), asiento_nuevo(f))),               # sin clave no choca
    ('expediente_origen_unico', lambda f: (copia(f.expediente, origen_id=None), copia(f.expediente, origen_id=None))),
    ('apertura_una_confirmada', lambda f: (apertura_confirmada(f), apertura_confirmada(
        f, estado='sustituida', asiento_reverso=f.asiento, motivo='Sustituida en la prueba'))),
    ('apertura_una_en_preparacion', lambda f: copia(f.apertura, estado='descartada', motivo='Descartada', clave=ac.clave())),
    ('apertura_una_sustituta', lambda f: dos_sustitutas_vivas(f, lambda vigente: copia(
        f.apertura, estado='descartada', motivo='Descartada', clave=ac.clave(), sustituye=vigente))),
    ('apertura_confirmada_completa', lambda f: upd(f.apertura, estado='confirmada', confirmado_en=timezone.now(), sin_saldos=True,
                                                   fuente='inicio_actividades', fuente_detalle='Empieza sus actividades')),
    ('linea_apertura_cuenta_unica', lambda f: (copia(f.linea_apertura, orden=98, cuenta=None),
                                               copia(f.linea_apertura, orden=97, cuenta=None))),
    ('linea_apertura_un_lado', lambda f: upd(f.linea_apertura, debe=None, haber=None)),
    ('linea_apertura_retirada_sin_importes', lambda f: upd(f.linea_apertura, retirada=True, debe=None)),
    ('auxiliar_apertura_documento_unico', lambda f: (copia(f.auxiliar, **anulada()), copia(f.auxiliar, documento_numero=''),
                                                     copia(f.auxiliar, documento_numero=''))),
    ('auxiliar_apertura_producto_unico', lambda f: (inventario(f), inventario(f, almacen='bodega 2'), inventario(f, **anulada()))),
    ('auxiliar_apertura_banco_unico', lambda f: (copia(f.auxiliar_banco, banco_numero='0002'),
                                                 copia(f.auxiliar_banco, **anulada()))),
    ('auxiliar_apertura_clave_acceso_unica', lambda f: (upd(f.auxiliar, clave_acceso='1' * 49),
                                                        copia(f.auxiliar, clave_acceso='1' * 49, **otro_documento(**anulada())))),
    ('auxiliar_apertura_tributario_unico', lambda f: (tributario(f), tributario(f, casillero='2'), tributario(f, **anulada()))),
    ('auxiliar_apertura_cxc_unico', lambda f: (upd(f.auxiliar, cxc_id=11), copia(f.auxiliar, cxc_id=11, **otro_documento(**anulada())))),
    ('auxiliar_apertura_cxp_unico', lambda f: (upd(f.auxiliar_proveedor, cxp_id=12),
                                               copia(f.auxiliar_proveedor, cxp_id=12, **otro_documento(**anulada())))),
    ('auxiliar_apertura_importado_unico', lambda f: (upd(f.auxiliar, documento_importado_id=13),
                                                     copia(f.auxiliar, documento_importado_id=13, **otro_documento(**anulada())))),
    ('auxiliar_apertura_un_sucesor', lambda f: (copia(f.auxiliar, antecesor=f.auxiliar, raiz=f.auxiliar, **otro_documento()),
                                                copia(f.auxiliar, antecesor=f.auxiliar, raiz=f.auxiliar,
                                                      **otro_documento(**anulada())))),
    ('aplicacion_auxiliar_descargo_completo', lambda f: upd(f.aplicacion, tipo='otro_descargo', medio='', subtipo='ajuste',
                                                            nota='Ajuste acordado')),
    ('vinculo_historico_documento_unico', lambda f: copia(f.vinculo_historico, clave=ac.clave(), **anulada())),
    ('vinculo_historico_auxiliar_unico', lambda f: (upd(f.vinculo_historico, destino='auxiliar_apertura', auxiliar=f.auxiliar),
                                                    copia(f.vinculo_historico, clave=ac.clave(), documento_importado_id=2,
                                                          destino='auxiliar_apertura', auxiliar=f.auxiliar, **anulada()))),
]


def restriccion(nombre):
    for modelo in (*ac.MODELOS_DEL_BLOQUE, Cuenta):
        for r in modelo._meta.constraints:
            if r.name == nombre:
                return r
    raise LookupError(nombre)


@pytest.mark.parametrize('nombre, accion, tablas', VIOLACIONES, ids=[f'{c[0]}-{i}' for i, c in enumerate(VIOLACIONES)])
def test_la_base_rechaza_lo_que_viola_cada_restriccion(f, nombre, accion, tablas):
    with ac.sin_disparadores(*tablas) if tablas else nullcontext():
        with pytest.raises(IntegrityError) as error, transaction.atomic():
            accion(f)
    mensaje = str(error.value)
    if connection.vendor == 'postgresql':
        assert f'"{nombre}"' in mensaje, mensaje
    elif isinstance(restriccion(nombre), models.CheckConstraint):
        assert mensaje == f'CHECK constraint failed: {nombre}', mensaje
    else:
        assert mensaje.startswith('UNIQUE constraint failed'), mensaje


@pytest.mark.parametrize('nombre, accion', ADMITIDAS, ids=[f'{c[0]}-{i}' for i, c in enumerate(ADMITIDAS)])
def test_lo_que_queda_fuera_de_la_condicion_se_admite(f, nombre, accion):
    restriccion(nombre)
    with transaction.atomic():
        accion(f)
        transaction.set_rollback(True)   # un asiento abierto no puede quedar al terminar (PostgreSQL)


def test_cada_restriccion_declarada_tiene_su_caso():
    nuestras = {r.name for m in ac.MODELOS_DEL_BLOQUE for r in m._meta.constraints}
    nuestras |= {'cuenta_clase_valida', 'cuenta_auxiliar_solo_movimiento'}
    probadas = {nombre for nombre, *_ in VIOLACIONES}
    assert nuestras == probadas, (sorted(nuestras - probadas), sorted(probadas - nuestras))
    # Las parciales tienen además su caso admitido o lo tienen por construcción (una por empresa).
    parciales = {r.name for m in ac.MODELOS_DEL_BLOQUE for r in m._meta.constraints
                 if isinstance(r, models.UniqueConstraint) and r.condition is not None}
    sin_caso = parciales - {nombre for nombre, _ in ADMITIDAS}
    # Su única condición es «no nulo»: dos nulos nunca chocan en una restricción única.
    assert sin_caso == {'asiento_un_reverso', 'apertura_clave_confirmacion_unica', 'expediente_clave_unica',
                        'expediente_asiento_unico'}, sorted(sin_caso)


def test_cuenta_nueva_sin_clase_ni_auxiliar(f):
    """Las dos columnas nuevas de Cuenta nacen vacías en Python y en la base (db_default), y el plan mínimo las declara."""
    nueva = Cuenta.objects.create(codigo='9.9.99', nombre='Sin declarar', tipo='movimiento')
    assert (nueva.clase, nueva.auxiliar) == ('', '')
    nueva.refresh_from_db()
    assert (nueva.clase, nueva.auxiliar) == ('', '')
    assert (f.cuentas['clientes'].clase, f.cuentas['clientes'].auxiliar) == ('activo', 'cliente')
    for campo in ('clase', 'auxiliar'):
        assert Cuenta._meta.get_field(campo).db_default == ''


# ---------------------------------------------------------------- guardas de modelo

class TestGuardasDelLibro:

    def test_asiento_guardado_solo_cambia_el_sello_y_el_reverso(self, f):
        asiento = Asiento.objects.get(pk=f.asiento.pk)
        asiento.concepto = 'Cambiado'
        for intento in ({}, {'update_fields': ['concepto']}, {'update_fields': ['sellado', 'concepto']}):
            with pytest.raises(LibroInmutable):
                asiento.save(**intento)
        assert Asiento.objects.get(pk=f.asiento.pk).concepto == 'Asiento de prueba'

    def test_asiento_nuevo_nace_abierto_y_sin_reverso(self, f):
        datos = {c.attname: getattr(f.asiento, c.attname) for c in Asiento._meta.concrete_fields if not c.primary_key}
        datos.update(numero=999, clave=None, origen_id=77)
        for cambio in ({'sellado': True}, {'reversado_por_id': f.asiento.pk, 'reversado_en': timezone.now()}):
            with pytest.raises(LibroInmutable):
                Asiento(**{**datos, 'sellado': False, **cambio}).save()
        with pytest.raises(LibroInmutable):
            Asiento(**{**datos, 'sellado': False}).save(update_fields=['sellado'])
        assert not Asiento.objects.filter(numero=999).exists()

    def test_un_id_repetido_no_actualiza_el_asiento_que_existe(self, f):
        datos = {c.attname: getattr(f.asiento, c.attname) for c in Asiento._meta.concrete_fields}
        datos.update(sellado=False, concepto='Intrusa', numero=998, clave=None, origen_id=78)
        with pytest.raises(IntegrityError), transaction.atomic():
            Asiento(**datos).save()   # mismo id: force_insert, nunca UPDATE
        assert Asiento.objects.get(pk=f.asiento.pk).concepto == 'Asiento de prueba'

    def test_sello_y_reverso_por_save(self, f):
        with transaction.atomic():
            abierto = ac.asiento_directo(f.empresa, [(f.cuentas['caja'], 3, 0), (f.cuentas['capital'], 0, 3)], sellar=False)
            abierto.sellado = True
            abierto.save(update_fields=['sellado'])
        reverso = ac.reverso_directo(f.empresa, f.asiento)
        original = Asiento.objects.get(pk=f.asiento.pk)
        assert original.reversado_por_id == reverso.pk and original.reversado_en is not None
        assert reverso.tipo == 'reverso' and reverso.reversa_de_id == original.pk

    def test_borrar_un_asiento_o_una_linea_lanza(self, f):
        for objeto in (Asiento.objects.get(pk=f.asiento.pk), LineaAsiento.objects.get(pk=f.linea_asiento.pk),
                       EventoApertura.objects.get(pk=f.evento.pk)):
            with pytest.raises(LibroInmutable):
                objeto.delete()
        with pytest.raises(LibroInmutable):
            f.asiento.lineas.all().delete()   # gestor relacionado: el mismo QuerySet
        assert LineaAsiento.objects.filter(asiento=f.asiento).count() == 2

    @pytest.mark.parametrize('gestor', ['objects', 'all_companies'])
    def test_queryset_del_asiento_fuera_del_contexto_interno(self, f, gestor):
        consulta = getattr(Asiento, gestor).filter(pk=f.asiento.pk)
        with pytest.raises(LibroInmutable):
            consulta.update(sellado=True)
        with pytest.raises(LibroInmutable):
            consulta.delete()
        with pytest.raises(LibroInmutable):
            getattr(Asiento, gestor).bulk_update([f.asiento], ['sellado'])
        assert not hasattr(getattr(Asiento, gestor), 'delete')   # como en Django: delete solo en el QuerySet

    def test_contexto_interno_solo_sello_y_reverso_y_nunca_borrar(self, f):
        with transaction.atomic():
            abierto = ac.asiento_directo(f.empresa, [(f.cuentas['caja'], 4, 0), (f.cuentas['capital'], 0, 4)], sellar=False)
            with escritura_interna():
                assert Asiento.objects.filter(pk=abierto.pk).update(sellado=True) == 1
                with pytest.raises(LibroInmutable):
                    Asiento.objects.filter(pk=abierto.pk).update(concepto='Otro')
                with pytest.raises(LibroInmutable):
                    Asiento.objects.bulk_update([abierto], ['concepto'])
                with pytest.raises(LibroInmutable):
                    Asiento.objects.filter(pk=abierto.pk).delete()
                with pytest.raises(LibroInmutable):
                    LineaAsiento.objects.filter(asiento=abierto).update(concepto='Otro')   # las líneas, nunca
            with pytest.raises(LibroInmutable):   # al salir, cerrado otra vez
                Asiento.objects.filter(pk=abierto.pk).update(sellado=True)
        assert Asiento.objects.get(pk=abierto.pk).sellado is True

    def test_lineas_y_eventos_solo_se_insertan(self, f):
        for objeto, campo in ((LineaAsiento.objects.get(pk=f.linea_asiento.pk), 'concepto'),
                              (EventoApertura.objects.get(pk=f.evento.pk), 'accion')):
            modelo = type(objeto)
            setattr(objeto, campo, 'cambiado')
            for intento in ({}, {'update_fields': [campo]}):
                with pytest.raises(LibroInmutable):
                    objeto.save(**intento)
            for gestor in (modelo.objects, modelo.all_companies):
                with pytest.raises(LibroInmutable):
                    gestor.filter(pk=objeto.pk).update(**{campo: 'cambiado'})
                with pytest.raises(LibroInmutable):
                    gestor.filter(pk=objeto.pk).delete()
                with pytest.raises(LibroInmutable):
                    gestor.bulk_update([objeto], [campo])
            with escritura_interna(), pytest.raises(LibroInmutable):
                modelo.objects.filter(pk=objeto.pk).update(**{campo: 'cambiado'})
        assert EventoApertura.objects.get(pk=f.evento.pk).accion == 'creada'

    def test_expediente_confirmado_no_cambia_lo_contabilizado(self, f):
        expediente = Contabilizacion.objects.get(pk=f.expediente.pk)
        # Antes de confirmar todo cambia, y la confirmación fija lo contabilizado en el mismo save.
        expediente.hecho, expediente.propuesta = {'importe': Decimal('10.00'), 'fecha': date(2026, 1, 10)}, [{'linea': 1}]
        expediente.save()
        expediente.estado, expediente.asiento, expediente.huella_origen = 'confirmado', f.asiento, 'a' * 64
        expediente.tesoreria_cuenta = f.cuentas['caja']
        expediente.save()
        # Confirmado: reasignar lo mismo (aunque sea Decimal o fecha) no es un cambio; la divergencia va aparte.
        expediente.hecho = {'importe': Decimal('10.00'), 'fecha': date(2026, 1, 10)}
        expediente.huella_actual, expediente.hecho_actual, expediente.divergente = 'b' * 64, {'importe': '12.00'}, True
        expediente.excepciones = [{'codigo': 'cuenta_de_apertura_cambiada', 'nivel': 'informa'}]
        expediente.save()
        expediente.save(update_fields=['huella_actual', 'divergente'])
        Contabilizacion.objects.filter(pk=expediente.pk).update(divergente=False, intentos=2)
        for campo, valor in (('hecho', {'importe': '11.00'}), ('propuesta', []), ('huella_origen', 'c' * 64),
                             ('tesoreria_cuenta', f.cuentas['bancos'])):
            cargado = Contabilizacion.objects.get(pk=expediente.pk)
            setattr(cargado, campo, valor)
            for intento in ({}, {'update_fields': [campo]}):
                with pytest.raises(LibroInmutable):
                    cargado.save(**intento)
            valor_db = valor.pk if isinstance(valor, models.Model) else valor
            columna = Contabilizacion._meta.get_field(campo).attname
            with pytest.raises(LibroInmutable):
                Contabilizacion.objects.filter(pk=expediente.pk).update(**{columna: valor_db})
            with pytest.raises(LibroInmutable):
                Contabilizacion.objects.bulk_update([cargado], [campo])
        guardado = Contabilizacion.objects.get(pk=expediente.pk)
        assert guardado.hecho == {'importe': '10.00', 'fecha': '2026-01-10'} and guardado.huella_origen == 'a' * 64
        assert guardado.tesoreria_cuenta_id == f.cuentas['caja'].pk and guardado.intentos == 2

    def test_borrar_al_usuario_autor_no_toca_el_libro(self, f, empresa_b):
        """Sin FK hacia el usuario (decisión común 16) el colector de Django no ve el libro: ningún UPDATE llega a un
        asiento ni a un evento (en PostgreSQL el disparador lo rechazaría) y el nombre se conserva. Con otra empresa
        activa también: el colector no tiene nada que buscar en las tablas contables."""
        for n, contexto in enumerate((company_context(f.empresa), company_context(empresa_b), nullcontext())):
            usuario = User.objects.create(username=f'autor.libro.{n}', names='Autor', email=f'autor{n}@example.com')
            asiento = ac.asiento_directo(f.empresa, [(f.cuentas['caja'], 7, 0), (f.cuentas['capital'], 0, 7)],
                                         autor=ac.autor(usuario))
            evento = EventoApertura.objects.create(apertura=f.apertura, accion='prueba', usuario_id=usuario.pk,
                                                   usuario_nombre=usuario.username)
            antes, id_usuario = Asiento.objects.filter(pk=asiento.pk).values().get(), usuario.pk
            with contexto:
                usuario.delete()
            assert not User.objects.filter(pk=id_usuario).exists()
            assert Asiento.objects.filter(pk=asiento.pk).values().get() == antes
            assert (antes['creado_por_id'], antes['creado_por_nombre']) == (id_usuario, f'autor.libro.{n}')
            assert EventoApertura.objects.filter(pk=evento.pk, usuario_id=id_usuario, usuario_nombre=f'autor.libro.{n}').exists()


# ---------------------------------------------------------------- recorridos ast

APPS_PERMITIDAS = {'contabilidad', 'tributario'}   # y pos.Company (decisión común 16c)
RELACIONES = ('ForeignKey', 'OneToOneField', 'ManyToManyField')


def archivos_de_modelos_por_bloque():
    """Los archivos de modelos de los bloques 2 a 6 (decisión común 1): core/contabilidad/modelos_*.py y los de
    core/tributario que sigan esa forma."""
    return sorted([*(BASE / 'core' / 'contabilidad').glob('modelos_*.py'), *(BASE / 'core' / 'tributario').glob('modelos_*.py')])


def destinos_de_relaciones(fuente):
    """[(línea, destino)] de cada ForeignKey/OneToOneField/ManyToManyField del archivo, y si el destino está permitido:
    un texto `app.Modelo` de contabilidad, tributario o `pos.Company`; un texto sin app (`'self'`, `'Cuenta'`: un modelo de
    la misma app); o el nombre de una clase definida en el mismo archivo. Cualquier otra cosa (`settings.AUTH_USER_MODEL`,
    una clase importada de otra app) no se deja pasar: no se puede comprobar adónde apunta."""
    arbol = ast.parse(fuente)
    locales = {n.name for n in arbol.body if isinstance(n, ast.ClassDef)}
    destinos = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = nodo.func.attr if isinstance(nodo.func, ast.Attribute) else getattr(nodo.func, 'id', None)
        if nombre not in RELACIONES:
            continue
        objetivo = nodo.args[0] if nodo.args else next((k.value for k in nodo.keywords if k.arg == 'to'), None)
        if isinstance(objetivo, ast.Constant) and isinstance(objetivo.value, str):
            app, _, modelo = objetivo.value.rpartition('.')
            permitido = not app or app in APPS_PERMITIDAS or (app, modelo.lower()) == ('pos', 'company')
            destinos.append((nodo.lineno, objetivo.value, permitido))
        else:
            destinos.append((nodo.lineno, ast.unparse(objetivo), isinstance(objetivo, ast.Name) and objetivo.id in locales))
    return destinos


class TestRecorridos:

    def test_ninguna_fk_de_los_bloques_hacia_la_operacion_ni_hacia_el_usuario(self):
        archivos = archivos_de_modelos_por_bloque()
        assert {a.name for a in archivos} >= {'modelos_libro.py', 'modelos_apertura.py'}
        malas = [f'{a.relative_to(BASE)}:{linea} → {destino}' for a in archivos
                 for linea, destino, permitido in destinos_de_relaciones(a.read_text(encoding='utf-8')) if not permitido]
        assert not malas, malas
        # Y en el registro real, por si una relación llega de otra forma (herencia, add_to_class).
        modulos = {'.'.join(a.relative_to(BASE).with_suffix('').parts) for a in archivos}
        modelos = [m for m in apps.get_models() if m.__module__ in modulos]
        assert {m.__name__ for m in modelos} >= {m.__name__ for m in ac.MODELOS_DEL_BLOQUE}
        relaciones = [(m.__name__, c.name, c.related_model._meta.label) for m in modelos for c in m._meta.get_fields()
                      if c.is_relation and c.concrete and c.related_model is not None]
        fuera = [r for r in relaciones if r[2].split('.')[0] not in APPS_PERMITIDAS and r[2] != 'pos.Company']
        assert not fuera, fuera

    def test_el_recorrido_detecta_lo_prohibido(self):
        fuente = '''
from django.conf import settings
from django.db import models
from core.pos.models import Sale
class X(models.Model):
    a = models.ForeignKey('pos.Sale', on_delete=models.PROTECT)
    b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    c = models.OneToOneField(to='importacion.DocumentoImportado', on_delete=models.PROTECT)
    d = models.ForeignKey(Sale, on_delete=models.PROTECT)
    e = models.ForeignKey('pos.Company', on_delete=models.PROTECT)
    f = models.ForeignKey('Cuenta', on_delete=models.PROTECT)
    g = models.ForeignKey('self', on_delete=models.PROTECT)
    h = models.ManyToManyField('auth.Group')
    i = models.ForeignKey(X, on_delete=models.PROTECT)
'''
        malos = sorted(d for _, d, permitido in destinos_de_relaciones(fuente) if not permitido)
        assert malos == ['Sale', 'auth.Group', 'importacion.DocumentoImportado', 'pos.Sale', 'settings.AUTH_USER_MODEL']

    @staticmethod
    def llamadas_por_lotes(fuente):
        """Líneas con `….bulk_create(` o `….bulk_update(`; no cuenta `super().bulk_update(…)`, que es la guarda del QuerySet
        del libro pasándole el envío a Django."""
        def de_super(llamada):
            receptor = llamada.func.value
            return isinstance(receptor, ast.Call) and getattr(receptor.func, 'id', None) == 'super'
        return sorted(n.lineno for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and n.func.attr in ('bulk_create', 'bulk_update') and not de_super(n))

    def test_bulk_create_y_bulk_update_solo_en_modulos_con_lotes(self):
        assert len(set(lotes.MODULOS_CON_LOTES)) == len(lotes.MODULOS_CON_LOTES) and lotes.TAMANO_LOTE == 1000
        assert all(m.startswith(('core.contabilidad.', 'core.tributario.')) for m in lotes.MODULOS_CON_LOTES)
        encontrados, malos = set(), []
        for app in ('contabilidad', 'tributario'):
            for ruta in sorted((BASE / 'core' / app).rglob('*.py')):
                if 'migrations' in ruta.parts:
                    continue
                modulo = '.'.join(ruta.relative_to(BASE).with_suffix('').parts)
                lineas = self.llamadas_por_lotes(ruta.read_text(encoding='utf-8'))
                if lineas:
                    encontrados.add(modulo)
                    if modulo not in lotes.MODULOS_CON_LOTES:
                        malos.append(f'{modulo}: líneas {lineas}')
        assert not malos, malos
        assert 'core.contabilidad.importar_cuentas' in encontrados   # el recorrido encuentra los que ya existen

    def test_el_recorrido_de_lotes_ve_todas_las_formas(self):
        fuente = ('from core.contabilidad.models import LineaAsiento as L\n'
                  'L.objects.bulk_create(filas, batch_size=1000)\n'
                  'def f(m):\n    return m.all_companies.bulk_update(objs, ["x"])\n'
                  'qs = L.objects.all(); qs.bulk_create([])\n'
                  'class Q:\n    def bulk_update(self, objs, fields):\n        return super().bulk_update(objs, fields)\n')
        assert self.llamadas_por_lotes(fuente) == [2, 4, 5]

    def test_escritura_interna_solo_en_diario(self):
        permitidos = {'core/contabilidad/modelos_libro.py', 'core/contabilidad/diario.py'}
        usos = []
        for ruta in sorted((BASE / 'core').rglob('*.py')):
            if 'migrations' in ruta.parts:
                continue
            relativa = ruta.relative_to(BASE).as_posix()
            arbol = ast.parse(ruta.read_text(encoding='utf-8'))
            if any((isinstance(n, ast.Name) and n.id == 'escritura_interna')
                   or (isinstance(n, ast.FunctionDef) and n.name == 'escritura_interna')
                   or (isinstance(n, ast.Attribute) and n.attr == 'escritura_interna')
                   or (isinstance(n, ast.alias) and n.name == 'escritura_interna') for n in ast.walk(arbol)):
                usos.append(relativa)
        assert set(usos) <= permitidos, sorted(set(usos) - permitidos)
        assert 'core/contabilidad/modelos_libro.py' in usos


# ---------------------------------------------------------------- vocabularios, permisos y auditoría

def test_vocabularios_que_crecen_sin_choices_ni_check_cerrado():
    """Decisión común 14: ampliarlos no genera un AlterField. Los que el bloque declara: AplicacionAuxiliar.tipo (y su
    subtipo) y CoberturaPeriodo.fuente_tipo; también los orígenes y eventos, que amplían los bloques siguientes."""
    abiertos = [(AplicacionAuxiliar, 'tipo'), (AplicacionAuxiliar, 'subtipo'), (AplicacionAuxiliar, 'medio'),
                (CoberturaPeriodo, 'fuente_tipo'), (Asiento, 'origen_tipo'), (Asiento, 'evento'),
                (Contabilizacion, 'origen_tipo'), (Contabilizacion, 'evento'), (EventoApertura, 'accion'),
                (LineaAsiento, 'documento_tipo'), (LineaAsiento, 'componente'), (LineaAsiento, 'concepto_tributario')]

    def lookups(q):
        for hijo in q.children:
            if isinstance(hijo, models.Q):
                yield from lookups(hijo)
            else:
                yield hijo[0]
    for modelo, campo in abiertos:
        assert modelo._meta.get_field(campo).choices is None, (modelo.__name__, campo)
        cerrados = [r.name for r in modelo._meta.constraints if isinstance(r, models.CheckConstraint)
                    and f'{campo}__in' in set(lookups(r.condition))]
        assert not cerrados, (modelo.__name__, campo, cerrados)


DEL_BLOQUE = {'view_asiento', 'view_apertura', 'add_apertura', 'change_confirmacion_apertura', 'add_aplicacionauxiliar',
              'change_aplicacionauxiliar'}
DECLARADOS = {'add_asiento', 'change_asiento', 'change_reverso_asiento', 'view_periodocontable', 'change_periodocontable',
              'change_reapertura_periodocontable', 'change_ejerciciocontable', 'change_reapertura_ejerciciocontable'}


def test_permisos_declarados_y_repartidos_por_rol():
    """Los seis que el bloque reparte cuelgan del módulo del kardex y llegan a cada rol según el reparto de la
    especificación; los declarados para bloques posteriores existen pero no cuelgan de ningún módulo ni los tiene nadie.
    Los codenames de escritura empiezan por add_ o change_ (así no llegan a Consulta) y no se repiten en otra app."""
    existentes = set(Permission.objects.filter(content_type__app_label='contabilidad').values_list('codename', flat=True))
    assert DEL_BLOQUE | DECLARADOS <= existentes
    assert all(c.startswith(('view_', 'add_', 'change_')) for c in DEL_BLOQUE | DECLARADOS)
    assert not Permission.objects.filter(codename__in=DEL_BLOQUE | DECLARADOS).exclude(content_type__app_label='contabilidad').exists()
    assert list(Module.objects.filter(permissions__codename__in=DEL_BLOQUE).distinct().values_list('url', flat=True)) == [
        '/contabilidad/kardex/']
    assert not Module.objects.filter(permissions__codename__in=DECLARADOS).exists()

    def del_bloque(rol):
        return set(Group.objects.get(name=rol).permissions.filter(codename__in=DEL_BLOQUE | DECLARADOS)
                   .values_list('codename', flat=True))
    assert del_bloque(ROLE_OWNER) == del_bloque(ROLE_ADMIN) == del_bloque(ROLE_ACCOUNTANT) == DEL_BLOQUE
    assert del_bloque(ROLE_READONLY) == {'view_asiento', 'view_apertura'}
    assert del_bloque(ROLE_SELLER) == del_bloque(ROLE_CLIENT) == set()


ACCIONES_DEL_BLOQUE = (
    'cuentas_clasificadas', 'inicio_contable_configurado', 'guarda_importacion_cambiada', 'apertura_creada',
    'apertura_modificada', 'apertura_importada', 'apertura_enviada_revision', 'apertura_devuelta', 'apertura_confirmada',
    'apertura_ajustada', 'apertura_ajuste_reversado', 'apertura_sustituida', 'apertura_reversada', 'apertura_descartada',
    'apertura_auxiliar_agregado', 'apertura_auxiliar_anulado', 'apertura_auxiliar_vinculado', 'apertura_auxiliar_completado',
    'apertura_respaldo', 'apertura_cobro', 'apertura_cobro_anulado', 'apertura_cobro_recontabilizado', 'historico_destinado',
    'historico_vinculo_anulado', 'cobertura_declarada')


def test_acciones_de_auditoria_del_bloque(empresa):
    """Las 25 del bloque (también las del corte 2) están en AuditLog.ACTIONS con su etiqueta y caben en la columna; la
    migración tenancy 0014 deja las mismas choices (makemigrations --check lo vigila) y una fila se guarda y se muestra."""
    acciones = dict(AuditLog.ACTIONS)
    assert len(ACCIONES_DEL_BLOQUE) == 25 and set(ACCIONES_DEL_BLOQUE) <= set(acciones)
    assert all(len(c) <= 40 and acciones[c] and acciones[c] != c for c in ACCIONES_DEL_BLOQUE)
    import importlib
    migracion = importlib.import_module('core.tenancy.migrations.0014_acciones_apertura').Migration
    elegidas = dict(migracion.operations[0].field.choices)
    assert {c: elegidas[c] for c in ACCIONES_DEL_BLOQUE} == {c: acciones[c] for c in ACCIONES_DEL_BLOQUE}
    from core.tenancy.models import audit
    audit(None, 'apertura_confirmada', company=empresa, apertura=1, asiento={'id': 1, 'numero': '2025-000001'},
          debe=Decimal('10000.00'), fecha=date(2025, 12, 31))
    registro = AuditLog.objects.get(action='apertura_confirmada', company=empresa)
    assert registro.get_action_display() == 'Apertura contable confirmada' and registro.detail['debe'] == '10000.00'


def test_ids_de_la_operacion_que_no_existen_se_guardan(f):
    """Sin restricción hacia tablas operativas, una fila con ids de la operación que no existen se guarda: que el destino
    no exista es un estado que deciden los servicios (`vinculo_roto`, `origen_eliminado`), no un error de la base."""
    aux = copia(f.auxiliar, cxc_id=987_654, cliente_id=987_655, documento_importado_id=987_656, **otro_documento())
    assert AuxiliarApertura.objects.filter(pk=aux.pk, cxc_id=987_654, documento_importado_id=987_656).exists()
    with transaction.atomic():
        abierto = asiento_nuevo(f, origen_id=987_659)
        linea_nueva(f, abierto, tercero_tipo='cliente', tercero_id=987_657, documento_tipo='venta', documento_id=987_658)
        assert LineaAsiento.objects.filter(asiento=abierto, tercero_id=987_657, documento_id=987_658).exists()
        transaction.set_rollback(True)   # el asiento abierto no puede quedar (PostgreSQL)
    assert VinculoHistorico.objects.filter(pk=f.vinculo_historico.pk, documento_importado_id=900_001).exists()   # no existe
