"""Ayudas de las pruebas del libro diario y de la apertura contable (bloque 2 del cierre contable). Datos ficticios.

Secciones separadas para que cada parte amplíe la suya sin pisar a las demás:

- comunes: claves, petición simulada, autor, plan mínimo de cuentas con clases y auxiliares, `en_paralelo` (PostgreSQL)
  y `sin_disparadores` (PostgreSQL);
- «libro» (Parte A: candado, diario, acumulados, lectura);
- «apertura» (Parte B: inicio, apertura, líneas, confirmación; y el corte 2);
- «esquema»: una fila válida de cada una de las 19 tablas, para las pruebas del esquema (RLS, restricciones, convivencia).

`asiento_directo` y las filas del esquema escriben sin pasar por los servicios: sirven para probar lo que la base y las
guardas de modelo garantizan por sí solas. No son `diario.contabilizar` (no toman el candado, no validan fechas ni
mantienen `SaldoCuentaMes`); las pruebas de los servicios usan los servicios."""
import hashlib
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.db import connection, connections, transaction
from django.test import RequestFactory
from django.utils import timezone

from core.contabilidad.models import (AjusteApertura, AplicacionAuxiliar, Apertura, Asiento, AuxiliarApertura, CoberturaPeriodo,
                                      Contabilizacion, Cuenta, EjercicioContable, EventoApertura, ImportacionApertura,
                                      InicioContable, LineaApertura, LineaAsiento, PartidaBancoApertura, PeriodoContable,
                                      RegistroClave, RespaldoApertura, SaldoCuentaMes, VinculoHistorico)
from core.tenancy.context import company_context
from core.tenancy.models import Membership

_claves = count(1)

# ---------------------------------------------------------------- comunes

# Quien escribe en las pruebas que no necesitan un usuario real: (id, nombre), la forma de los autores (decisión común 16).
AUTOR = (None, 'prueba.esquema')


def clave(prefijo='prueba'):
    """Clave de envío única con el formato del kardex (8 a 40 letras, cifras, guion o guion bajo)."""
    return f'{prefijo}-{next(_claves):08d}'


def autor(usuario):
    """`(id, nombre)` de un usuario, como lo guardan los autores del libro y de la apertura."""
    return usuario.pk, usuario.username


def peticion(usuario, empresa, metodo='post'):
    """Petición con el usuario, la empresa activa y su membresía (lo que deja el middleware), para los servicios que reciben
    `request` (permiso del rol, auditoría con IP)."""
    request = getattr(RequestFactory(), metodo)('/', REMOTE_ADDR='127.0.0.1')
    request.user = usuario
    request.company = empresa
    request.membership = Membership.objects.select_related('group').filter(user=usuario, company=empresa).first()
    return request


# (clave, código, nombre, tipo, clase, auxiliar, clave del padre): un plan mínimo con las siete clases y los seis auxiliares.
PLAN_MINIMO = (
    ('activo', '1', 'ACTIVO', 'grupo', 'activo', '', None),
    ('caja', '1.1.01', 'Caja', 'movimiento', 'activo', '', 'activo'),
    ('bancos', '1.1.02', 'Bancos', 'movimiento', 'activo', 'banco', 'activo'),
    ('clientes', '1.1.03', 'Clientes', 'movimiento', 'activo', 'cliente', 'activo'),
    ('inventario', '1.1.04', 'Inventario de mercaderías', 'movimiento', 'activo', 'inventario', 'activo'),
    ('credito_iva', '1.1.05', 'Crédito tributario de IVA', 'movimiento', 'activo', 'tributario', 'activo'),
    ('equipos', '1.2.01', 'Equipos de computación', 'movimiento', 'activo', 'activo', 'activo'),
    ('pasivo', '2', 'PASIVO', 'grupo', 'pasivo', '', None),
    ('proveedores', '2.1.01', 'Proveedores', 'movimiento', 'pasivo', 'proveedor', 'pasivo'),
    ('patrimonio', '3', 'PATRIMONIO', 'grupo', 'patrimonio', '', None),
    ('capital', '3.1.01', 'Capital social', 'movimiento', 'patrimonio', '', 'patrimonio'),
    ('resultados', '3.1.02', 'Resultados acumulados', 'movimiento', 'patrimonio', '', 'patrimonio'),
    ('ingresos', '4', 'INGRESOS', 'grupo', 'ingreso', '', None),
    ('ventas', '4.1.01', 'Ventas', 'movimiento', 'ingreso', '', 'ingresos'),
    ('costos', '5', 'COSTOS', 'grupo', 'costo', '', None),
    ('costo_ventas', '5.1.01', 'Costo de ventas', 'movimiento', 'costo', '', 'costos'),
    ('gastos', '6', 'GASTOS', 'grupo', 'gasto', '', None),
    ('gastos_generales', '6.1.01', 'Gastos generales', 'movimiento', 'gasto', '', 'gastos'),
)


def plan_minimo(empresa):
    """Crea el plan mínimo ficticio en la empresa y devuelve `{clave: Cuenta}`."""
    cuentas = {}
    with company_context(empresa):
        for nombre, codigo, titulo, tipo, clase, auxiliar, padre in PLAN_MINIMO:
            cuentas[nombre] = Cuenta.objects.create(codigo=codigo, nombre=titulo, tipo=tipo, clase=clase, auxiliar=auxiliar,
                                                    padre=cuentas.get(padre))
    return cuentas


def en_paralelo(tareas):
    """Solo PostgreSQL y pruebas `transaction=True`: ejecuta cada tarea en su hilo y su conexión, a la vez (barrera), como
    tests/test_zz_kardex_concurrencia_pg.py. Cada tarea abre su propio `company_context`. Devuelve (resultados, errores)."""
    barrera, resultados, errores, cerrojo = threading.Barrier(len(tareas)), [], [], threading.Lock()

    def correr(tarea):
        try:
            barrera.wait()
            resultado = tarea()
            with cerrojo:
                resultados.append(resultado)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            with cerrojo:
                errores.append(e)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(t,)) for t in tareas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados, errores


@contextmanager
def sin_disparadores(*tablas):
    """Solo PostgreSQL: desactiva los disparadores de usuario de esas tablas dentro de un punto de guardado que siempre se
    deshace, para comprobar una restricción que el disparador taparía (rechaza antes el mismo cambio). En SQLite no hay
    disparadores: no hace nada más que el punto de guardado."""
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            # PostgreSQL no altera una tabla con eventos de disparador pendientes en la transacción (los diferidos de lo
            # que la prueba ya insertó): se comprueban ahora, como al confirmar, y la tabla queda libre.
            connection.check_constraints()
            with connection.cursor() as cursor:
                for tabla in tablas:
                    cursor.execute(f'ALTER TABLE {connection.ops.quote_name(tabla)} DISABLE TRIGGER USER')
        try:
            yield
        finally:
            transaction.set_rollback(True)


# ---------------------------------------------------------------- libro (Parte A)

def huella_de_prueba(*partes):
    """SHA-256 de un texto cualquiera: la huella real (contenido canónico `v1`) es de diario.py."""
    return hashlib.sha256('|'.join(str(p) for p in partes).encode()).hexdigest()


def ejercicio(empresa, anio):
    with company_context(empresa):
        return EjercicioContable.objects.get_or_create(anio=anio)[0]


def asiento_directo(empresa, lineas, *, fecha=date(2026, 1, 15), tipo='manual', concepto='Asiento de prueba',
                    motivo='Prueba del esquema', origen=None, reversa_de=None, autor=AUTOR, clave=None, sellar=True):
    """Asiento insertado sin el servicio, con el orden que exigen las guardas y los disparadores: el asiento sin sellar,
    sus líneas y el sello. `lineas` = `[(cuenta, debe, haber)]` o `[(cuenta, debe, haber, {campos de la línea})]` (tercero,
    documento…); `origen` = `(tipo, id, evento)`. Toma el número siguiente de su ejercicio. Con `sellar=False` queda
    abierto: en PostgreSQL, solo dentro de una transacción de la prueba que se deshaga (al confirmar, un asiento sin
    sellar se rechaza)."""
    origen_tipo, origen_id, evento = origen or ('', None, '')
    # En una transacción propia, como diario.py: en PostgreSQL un asiento que se confirma sin sellar se rechaza (en una prueba
    # transaccional, cada sentencia suelta se confirmaría al momento).
    with company_context(empresa), transaction.atomic():
        ej = EjercicioContable.objects.get_or_create(anio=fecha.year)[0]
        ej.ultimo_numero += 1
        ej.save(update_fields=['ultimo_numero'])
        lineas = [(*linea, {})[:4] for linea in lineas]
        debe = sum((Decimal(str(d)) for _, d, _, _ in lineas), Decimal('0'))
        haber = sum((Decimal(str(h)) for _, _, h, _ in lineas), Decimal('0'))
        asiento = Asiento.objects.create(
            ejercicio=ej, anio=fecha.year, mes=fecha.month, numero=ej.ultimo_numero, fecha=fecha, tipo=tipo, concepto=concepto,
            origen_tipo=origen_tipo, origen_id=origen_id, evento=evento, reversa_de=reversa_de, total_debe=debe,
            total_haber=haber, lineas_n=len(lineas), huella=huella_de_prueba(empresa.pk, fecha, ej.ultimo_numero),
            motivo=motivo, clave=clave, creado_por_id=autor[0], creado_por_nombre=autor[1])
        for orden, (cuenta, d, h, extra) in enumerate(lineas, 1):
            LineaAsiento.objects.create(asiento=asiento, orden=orden, cuenta=cuenta, debe=Decimal(str(d)), haber=Decimal(str(h)),
                                        fecha=fecha, anio=fecha.year, mes=fecha.month, **extra)
        if sellar:
            asiento.sellado = True
            asiento.save(update_fields=['sellado'])
        return asiento


def reverso_directo(empresa, original, *, fecha=None, motivo='Reverso de prueba', autor=AUTOR):
    """Reverso sin el servicio: el asiento espejo y, después, el par `reversado_por`/`reversado_en` del original."""
    with company_context(empresa), transaction.atomic():
        lineas = [(linea.cuenta, linea.haber, linea.debe) for linea in original.lineas.select_related('cuenta')]
        reverso = asiento_directo(empresa, lineas, fecha=fecha or original.fecha, tipo='reverso', concepto=f'Reverso de {original}',
                                  motivo=motivo, origen=(original.origen_tipo, original.origen_id, original.evento)
                                  if original.origen_id is not None else None, reversa_de=original, autor=autor)
        original.reversado_por, original.reversado_en = reverso, timezone.now()
        original.save(update_fields=['reversado_por', 'reversado_en'])
    return reverso


def filas_del_libro(empresa, cuentas):
    """Una fila válida de cada tabla del libro (8). El asiento es `origen` con su origen, cuadrado y sellado."""
    with company_context(empresa):
        inicio = InicioContable.objects.create(modalidad='saldos', fecha_corte=date(2025, 12, 31),
                                               contabilidad_desde=date(2026, 1, 1), operaciones_desde=date(2026, 1, 1),
                                               creado_por_nombre=AUTOR[1], actualizado_por_nombre=AUTOR[1])
        periodo = PeriodoContable.objects.create(anio=2026, mes=1)
    asiento = asiento_directo(empresa, [(cuentas['caja'], '100.00', '0'), (cuentas['ventas'], '0', '100.00')],
                              tipo='origen', origen=('venta', 123, 'emision'), clave=clave('asiento'))
    with company_context(empresa):
        return {
            'inicio': inicio,
            'ejercicio': EjercicioContable.objects.get(anio=2026),
            'periodo': periodo,
            'asiento': asiento,
            'linea_asiento': asiento.lineas.order_by('orden').first(),
            'saldo': SaldoCuentaMes.objects.create(cuenta=cuentas['caja'], anio=2026, mes=1, debe=Decimal('100.00')),
            'expediente': Contabilizacion.objects.create(origen_tipo='aplicacion_auxiliar', origen_id=1, evento='registro',
                                                         fecha_contable=date(2026, 1, 15), creado_por_nombre=AUTOR[1]),
            'registro_clave': RegistroClave.objects.create(clave=clave('registro'), accion='apertura_auxiliares',
                                                           recurso_tipo='apertura', huella='0' * 64,
                                                           creado_por_nombre=AUTOR[1]),
        }


def inicio_directo(empresa, corte=date(2025, 12, 31), modalidad='saldos', **campos):
    """La fila del candado sin el servicio de la Parte B (`inicio_contable.configurar`): por saldos, contabilidad y
    operaciones desde el día siguiente al corte; por historial, `historial_desde` = corte + 1 y `historial_hasta` el que se
    pase (por defecto el 30/06 siguiente)."""
    from datetime import timedelta
    desde = corte + timedelta(days=1)
    datos = dict(modalidad=modalidad, fecha_corte=corte, contabilidad_desde=desde, operaciones_desde=desde,
                 creado_por_nombre=AUTOR[1], actualizado_por_nombre=AUTOR[1])
    if modalidad == 'historial':
        hasta = campos.pop('historial_hasta', date(desde.year, 6, 30))
        datos.update(historial_desde=desde, historial_hasta=hasta, operaciones_desde=hasta + timedelta(days=1))
    datos.update(campos)
    with company_context(empresa):
        return InicioContable.objects.create(**datos)


def lineas_de(*filas):
    """`[(cuenta, debe, haber[, {tercero, documento, concepto…}])]` → las líneas que recibe diario.contabilizar."""
    return [{'cuenta_id': cuenta.pk, 'debe': Decimal(str(debe)), 'haber': Decimal(str(haber)), **(extra[0] if extra else {})}
            for cuenta, debe, haber, *extra in filas]


def contabilizar(empresa, filas, *, tipo='manual', fecha=date(2026, 1, 15), concepto='Asiento de prueba',
                 motivo='Prueba del diario', autor=AUTOR, **otros):
    """diario.contabilizar con el candado, en la empresa (las pruebas del diario usan el servicio, no `asiento_directo`)."""
    from core.contabilidad import candado, diario
    with company_context(empresa), candado.libro():
        return diario.contabilizar(tipo=tipo, fecha=fecha, concepto=concepto, lineas=lineas_de(*filas), autor=autor,
                                   motivo=motivo, **otros)


def reversar(empresa, asiento, *, motivo='Reverso de prueba', autor=AUTOR, **otros):
    """diario.reversar con el candado, en la empresa. Devuelve `(reverso, repetido)`."""
    from core.contabilidad import candado, diario
    with company_context(empresa), candado.libro():
        return diario.reversar(asiento.pk, motivo=motivo, autor=autor, **otros)


# ---------------------------------------------------------------- apertura (Parte B y corte 2)

def apertura_directa(empresa, **campos):
    """Apertura en borrador sin el servicio (corte 31/12/2025, balance de comprobación)."""
    datos = dict(fecha_corte=date(2025, 12, 31), fuente='balance_comprobacion', clave=clave('apertura'),
                 creado_por_nombre=AUTOR[1])
    datos.update(campos)
    with company_context(empresa):
        return Apertura.objects.create(**datos)


def filas_de_apertura(empresa, cuentas, asiento):
    """Una fila válida de cada tabla de la apertura (11), sobre una apertura en borrador con tres líneas (clientes,
    bancos y proveedores) y un auxiliar en cada una. `asiento` hace de asiento del ajuste."""
    apertura = apertura_directa(empresa)
    with company_context(empresa):
        linea = LineaApertura.objects.create(apertura=apertura, orden=1, cuenta=cuentas['clientes'], debe=Decimal('100.00'),
                                             detalle='cliente', rubro_origen='Clientes')
        linea_banco = LineaApertura.objects.create(apertura=apertura, orden=2, cuenta=cuentas['bancos'], debe=Decimal('50.00'),
                                                   detalle='banco', rubro_origen='Bancos')
        linea_proveedor = LineaApertura.objects.create(apertura=apertura, orden=3, cuenta=cuentas['proveedores'],
                                                       haber=Decimal('30.00'), detalle='proveedor', rubro_origen='Proveedores')
        cliente = AuxiliarApertura.objects.create(
            apertura=apertura, linea=linea, cuenta=cuentas['clientes'], naturaleza='cliente', saldo_inicial=Decimal('100.00'),
            tercero_tipo_identificacion='05', tercero_identificacion='0912345678', tercero_nombre='CLIENTE FICTICIO',
            documento_tipo='01', documento_numero='001-001-000000001', creado_por_nombre=AUTOR[1])
        banco = AuxiliarApertura.objects.create(
            apertura=apertura, linea=linea_banco, cuenta=cuentas['bancos'], naturaleza='banco', saldo_inicial=Decimal('50.00'),
            banco_nombre='BANCO FICTICIO', banco_numero='0001', creado_por_nombre=AUTOR[1])
        proveedor = AuxiliarApertura.objects.create(
            apertura=apertura, linea=linea_proveedor, cuenta=cuentas['proveedores'], naturaleza='proveedor',
            saldo_inicial=Decimal('30.00'), tercero_tipo_identificacion='04', tercero_identificacion='0990000001001',
            tercero_nombre='PROVEEDOR FICTICIO', documento_tipo='01', documento_numero='001-001-000000077',
            creado_por_nombre=AUTOR[1])
        return {
            'apertura': apertura,
            'linea_apertura': linea,
            'importacion_apertura': ImportacionApertura.objects.create(
                apertura=apertura, tipo='saldos', archivo='privado/empresas/prueba/apertura/saldos.csv', nombre='saldos.csv',
                tamano=10, sha256='0' * 64, clave=clave('importacion'), creado_por_nombre=AUTOR[1]),
            'respaldo_apertura': RespaldoApertura.objects.create(
                apertura=apertura, archivo='privado/empresas/prueba/apertura/respaldo.pdf', nombre='respaldo.pdf',
                tipo_mime='application/pdf', tamano=10, sha256='1' * 64, clave=clave('respaldo'), subido_por_nombre=AUTOR[1]),
            'ajuste_apertura': AjusteApertura.objects.create(apertura=apertura, numero=1, fecha=date(2026, 1, 20),
                                                             motivo='Ajuste de prueba', asiento=asiento, clave=clave('ajuste'),
                                                             creado_por_nombre=AUTOR[1]),
            'auxiliar': cliente,
            'auxiliar_banco': banco,
            'auxiliar_proveedor': proveedor,
            'partida_banco': PartidaBancoApertura.objects.create(auxiliar=banco, tipo='deposito_transito', sentido='ingreso',
                                                                 importe=Decimal('10.00'), creado_por_nombre=AUTOR[1]),
            'aplicacion': AplicacionAuxiliar.objects.create(auxiliar=cliente, raiz=cliente, tipo='cobro', fecha=date(2026, 1, 10),
                                                            importe=Decimal('10.00'), medio='transferencia',
                                                            clave=clave('aplicacion'), registrado_por_nombre=AUTOR[1]),
            'vinculo_historico': VinculoHistorico.objects.create(documento_importado_id=900_001, destino='consulta',
                                                                 clave=clave('historico'), decidido_por_nombre=AUTOR[1]),
            'cobertura': CoberturaPeriodo.objects.create(ambito='contabilidad', anio=2026, mes=1, estado='pendiente',
                                                         fuente_tipo='aplicacion', declarado_por_nombre=AUTOR[1]),
            'evento': EventoApertura.objects.create(apertura=apertura, accion='creada', a_estado='borrador',
                                                    usuario_nombre=AUTOR[1]),
        }


def apertura_confirmada_directa(empresa, cuentas, *, fecha_corte=date(2025, 12, 31), importe='10000.00'):
    """Apertura confirmada de 10 000/10 000 (caja al debe, capital social al haber) con su inicio y su asiento de
    apertura, escrita SIN el servicio: la confirmación (apertura.confirmar) es de la parte siguiente del corte 1. Sirve a
    las pruebas que solo necesitan que exista una confirmada (crear o mover el corte → `apertura_confirmada`, la etapa del
    inicio, la cobertura). Cuando exista apertura.confirmar, la parte siguiente la cambia por el servicio."""
    with company_context(empresa):
        inicio = InicioContable.objects.first() or inicio_directo(empresa, fecha_corte)
    apertura = apertura_directa(empresa, fecha_corte=fecha_corte)
    monto = Decimal(importe)
    with company_context(empresa):
        LineaApertura.objects.create(apertura=apertura, orden=1, cuenta=cuentas['caja'], debe=monto, haber=Decimal('0'),
                                     rubro_origen='Caja')
        LineaApertura.objects.create(apertura=apertura, orden=2, cuenta=cuentas['capital'], debe=Decimal('0'), haber=monto,
                                     rubro_origen='Capital social')
    asiento = asiento_directo(empresa, [(cuentas['caja'], importe, '0'), (cuentas['capital'], '0', importe)],
                              fecha=fecha_corte, tipo='apertura', concepto='Apertura contable', motivo='',
                              origen=('apertura', apertura.pk, 'confirmacion'))
    with company_context(empresa):
        apertura.estado, apertura.asiento, apertura.total_debe, apertura.total_haber = 'confirmada', asiento, monto, monto
        apertura.confirmado_en, apertura.confirmado_por_nombre = timezone.now(), AUTOR[1]
        apertura.version += 1
        apertura.save(update_fields=['estado', 'asiento', 'total_debe', 'total_haber', 'confirmado_en',
                                     'confirmado_por_nombre', 'version'])
    return inicio, apertura


# ---------------------------------------------------------------- esquema (las 19 tablas)

def filas_de_cada_tabla(empresa, cuentas=None):
    """Plan mínimo (si no se pasa) y una fila válida de cada una de las 19 tablas del bloque, más las que necesitan
    (líneas y auxiliares de más). Devuelve `{nombre: instancia}` con `cuentas` incluidas."""
    cuentas = cuentas or plan_minimo(empresa)
    filas = filas_del_libro(empresa, cuentas)
    filas.update(filas_de_apertura(empresa, cuentas, filas['asiento']))
    filas['cuentas'] = cuentas
    return filas


# Las 19 tablas nuevas del bloque, por modelo (las que recorre la seguridad por filas de contabilidad 0012).
MODELOS_DEL_BLOQUE = (InicioContable, EjercicioContable, PeriodoContable, Asiento, LineaAsiento, SaldoCuentaMes,
                      Contabilizacion, RegistroClave, Apertura, LineaApertura, ImportacionApertura, RespaldoApertura,
                      AjusteApertura, AuxiliarApertura, PartidaBancoApertura, AplicacionAuxiliar, VinculoHistorico,
                      CoberturaPeriodo, EventoApertura)
