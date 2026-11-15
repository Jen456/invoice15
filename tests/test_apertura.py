"""Apertura contable: validar, enviar a revisión, devolver y confirmar (bloque 2 del cierre contable, Parte B, segunda
mitad; aceptaciones 1, 2, 7, 8 y 10 de C6-A §8): core/contabilidad/apertura.py (`evaluar`, `validar`, `enviar`, `devolver`,
`confirmar`) y sus rutas en vistas_apertura.py.

- aceptación 1: corte 31/12 y operaciones desde 01/01, exactamente un asiento de 10 000/10 000; la misma clave → `repetido`
  (también con la versión vieja: la clave va antes que la versión); otra clave → 409 `apertura_confirmada`;
- aceptación 2: importe pendiente, diferencia de 50 y cuenta de grupo bloquean, en validar, en enviar y al confirmar (la
  revalidación con el candado), sin asiento, sin cuenta nueva y sin línea añadida;
- aceptación 7: corte a mitad de año (nominales, nominales y línea de resultado, solo patrimonio, sin declarar, «no aplica»
  con y sin nota) y corte 31/12 con nominales (`ejercicio_sin_cerrar`); el 101 del año del corte, provisional;
- aceptación 8: dos empresas (404 cruzado), pestaña vieja, matriz de los seis roles en las cuatro rutas, `version` en cada
  envío, plan vencido y complemento cerrado;
- aceptación 10: confirmar no llama al SRI, no envía correo y no crea ningún documento; con el complemento cerrado la
  factura se sigue emitiendo;
- cada bloqueo de la regla 5 que este corte puede dar, en su orden, y cada advertencia; validar no escribe; enviar y
  devolver con su historia; sin saldos (sin asiento); historial; corte futuro; solapamiento; período cerrado; el inicio
  contable sincronizado; incompletos aceptados línea por línea; ámbitos congelados; una confirmada no se edita; el diario
  posterior al corte sigue provisional (`motor_pendiente`); confirmar no toca stock, cartera ni kardex; 5 000 líneas sin
  consultas por línea;
- el detalle de cada línea es el auxiliar que su cuenta declara mientras la apertura se prepara (también si la cuenta
  cambia en revisión, en los dos sentidos, o contradice un ámbito declarado «no aplica») y confirmar lo fija; un total
  que no cabe en un asiento bloquea antes de confirmar.

La seguridad por filas y las confirmaciones simultáneas van en tests/test_zz_apertura_concurrencia_pg.py. Datos ficticios."""
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.contabilidad import apertura as servicio
from core.contabilidad import reportes
from core.contabilidad.models import (Apertura, Asiento, AuxiliarApertura, Cuenta, EventoApertura, InicioContable,
                                      LineaApertura, LineaAsiento, MovimientoManual, PeriodoContable, SaldoCuentaMes,
                                      norma_codigo)
from core.pos.models import Client, CtasCollect, DebtsPay, Product, Purchase, Sale
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog)
from tests import ayudas_contables as ayudas
from tests import helpers
from tests import test_emision_sri as emision_sri
from tests.test_apertura_preparar import (API, CAPACIDADES, acciones, balance, creada, en, entrar_como, eventos, leer, linea,
                                          mapeada, plan_grande, rechazo, vencer)
from tests.test_apertura_preparar import cuentas, web   # noqa: F401 - fixtures
from tests.test_apertura_preparar import enviar as envio
from tests.test_emision_sri import p12, sri   # noqa: F401 - fixtures de la aceptación 10
from tests.test_firma_sri import CLAVE as CLAVE_FIRMA

pytestmark = pytest.mark.django_db

CORTE = date(2025, 12, 31)
MITAD = date(2026, 6, 30)   # corte a mitad de año (ya pasado: hoy es posterior)
TV = servicio.TEXTOS_VALIDACION


# ---------------------------------------------------------------- ayudas

def accion(client, empresa, apertura, que, **datos):
    return envio(client, f'{API}{apertura["id"]}/{que}/', empresa, datos)


def validar(client, empresa, apertura):
    respuesta = accion(client, empresa, apertura, 'validar', version=apertura['version'])
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def preparada(client, empresa, filas, *, cambios=None, **creacion):
    """Creada y mapeada (y, con `cambios`, con su encabezado cambiado) por las rutas: la apertura como la devuelve
    GET apertura/<id>/."""
    apertura = creada(client, empresa, **creacion)
    if filas:
        mapeada(client, empresa, apertura, filas)
    if cambios:
        version = leer(client, f'{API}{apertura["id"]}/', empresa)['apertura']['version']
        respuesta = envio(client, f'{API}{apertura["id"]}/', empresa, {'version': version, **cambios}, 'patch')
        assert respuesta.status_code == 200, respuesta.content
    return leer(client, f'{API}{apertura["id"]}/', empresa)['apertura']


def enviada(client, empresa, filas, **kw):
    apertura = preparada(client, empresa, filas, **kw)
    respuesta = accion(client, empresa, apertura, 'enviar', version=apertura['version'])
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['apertura']


def confirmar(client, empresa, apertura, *, clave=None, aceptadas=(), **extra):
    datos = {'version': apertura['version'], 'clave': clave or ayudas.clave('confirmar'), 'revisado': True, 'nota': '',
             'incompletos_aceptados': list(aceptadas), **extra}
    return accion(client, empresa, apertura, 'confirmar', **datos)


def confirmada(client, empresa, apertura, **kw):
    respuesta = confirmar(client, empresa, apertura, **kw)
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def codigos(lista):
    return [entrada['codigo'] for entrada in lista]


def asientos(empresa):
    return en(empresa, lambda: list(Asiento.objects.order_by('id').values_list('tipo', 'fecha', 'total_debe')))


def ids_de_lineas(empresa, apertura, *cuentas_):
    with company_context(empresa):
        return [LineaApertura.objects.get(apertura_id=apertura['id'], cuenta=c).pk for c in cuentas_]


def mitad_de_anio(cuentas, *extra):
    """Corte 30/06 con 1 000 de resultado en cuentas nominales: ventas 3 000 al haber y gastos 2 000 al debe."""
    return [linea(cuentas['caja'], '6000.00'), linea(cuentas['capital'], None, '5000.00'),
            linea(cuentas['ventas'], None, '3000.00'), linea(cuentas['gastos_generales'], '2000.00'), *extra]


def cambiar_auxiliar(client, empresa, cuenta, auxiliar):
    """PATCH /contabilidad/api/cuentas/<id>/ con el auxiliar (cuentas.modificar lo permite mientras la cuenta no tenga
    auxiliares vigentes ni líneas de asiento con tercero: también con la apertura en revisión)."""
    version = en(empresa, lambda: Cuenta.objects.get(pk=cuenta.pk).version)
    respuesta = envio(client, f'/contabilidad/api/cuentas/{cuenta.pk}/', empresa, {'version': version, 'auxiliar': auxiliar},
                      'patch')
    assert respuesta.status_code == 200, respuesta.content
    assert en(empresa, lambda: Cuenta.objects.get(pk=cuenta.pk).auxiliar) == auxiliar


def conteos_de_la_operacion(empresa):
    """Lo que confirmar nunca toca: documentos, cartera, kardex y stock."""
    with company_context(empresa):
        return {'ventas': Sale.objects.count(), 'compras': Purchase.objects.count(), 'cxc': CtasCollect.objects.count(),
                'cxp': DebtsPay.objects.count(), 'kardex': MovimientoManual.objects.count(),
                'stock': sorted(Product.objects.values_list('pk', 'stock')), 'clientes': Client.objects.count(),
                'cuentas': Cuenta.objects.count()}


# ---------------------------------------------------------------- aceptación 1

class TestAceptacion1:

    def test_un_solo_asiento_de_10000(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        assert apertura['estado'] == 'en_revision'
        datos = confirmada(web, empresa, apertura, clave='confirmar-apertura-1', nota='Revisada contra el balance firmado.')
        assert list(datos) == ['apertura', 'cobertura', 'repetido'] and datos['repetido'] is False
        asiento = en(empresa, Asiento.objects.get)
        assert datos['apertura'] == {
            'id': apertura['id'], 'version': apertura['version'] + 1, 'estado': 'confirmada', 'debe': '10000.00',
            'haber': '10000.00', 'diferencia': '0.00', 'revisado_por': 'propietario.a', 'confirmado_por': 'propietario.a',
            'confirmado_en': datos['apertura']['confirmado_en'],
            'asiento': {'id': asiento.pk, 'numero': '2025-000001', 'fecha': '2025-12-31', 'debe': '10000.00', 'haber': '10000.00'}}
        # regla 7: tipo apertura, en el corte, con su origen, una línea por línea de la apertura, sin tercero ni documento
        assert (asiento.tipo, asiento.fecha, asiento.origen_tipo, asiento.origen_id, asiento.evento, asiento.sellado) == (
            'apertura', CORTE, 'apertura', apertura['id'], 'confirmacion', True)
        assert en(empresa, lambda: list(LineaAsiento.objects.filter(asiento=asiento).order_by('orden').values_list(
            'cuenta_id', 'debe', 'haber', 'concepto', 'tercero_tipo', 'documento_tipo'))) == [
            (cuentas['caja'].pk, Decimal('10000.00'), Decimal('0.00'), 'Caja', '', ''),
            (cuentas['capital'].pk, Decimal('0.00'), Decimal('10000.00'), 'Capital social', '', '')]
        # los acumulados llevan la apertura en su columna propia, en el mes del corte
        assert en(empresa, lambda: list(SaldoCuentaMes.objects.order_by('cuenta_id').values_list(
            'cuenta_id', 'anio', 'mes', 'debe', 'apertura_debe', 'haber', 'apertura_haber'))) == [
            (cuentas['caja'].pk, 2025, 12, Decimal('10000.00'), Decimal('10000.00'), Decimal('0.00'), Decimal('0.00')),
            (cuentas['capital'].pk, 2025, 12, Decimal('0.00'), Decimal('0.00'), Decimal('10000.00'), Decimal('10000.00'))]
        # operaciones desde el día siguiente al corte; la cobertura de contabilidad queda conciliada
        inicio = en(empresa, InicioContable.objects.get)
        assert (inicio.fecha_corte, inicio.contabilidad_desde, inicio.operaciones_desde) == (CORTE, date(2026, 1, 1),
                                                                                            date(2026, 1, 1))
        assert datos['cobertura']['contabilidad'] == {'estado': 'conciliada', 'causas': [], 'causas_detalle': []}
        guardada = en(empresa, lambda: Apertura.objects.get(pk=apertura['id']))
        assert (guardada.nota_revision, guardada.clave_confirmacion, guardada.revisado_en is not None) == (
            'Revisada contra el balance firmado.', 'confirmar-apertura-1', True)

        # Doble clic: la misma clave (y la versión que ya no es la vigente) → el mismo cuerpo con `repetido`.
        otra_vez = confirmar(web, empresa, apertura, clave='confirmar-apertura-1')
        assert otra_vez.status_code == 200 and otra_vez.json() == {**datos, 'repetido': True}
        # Otra clave: ya está confirmada.
        rechazo(confirmar(web, empresa, apertura, clave='confirmar-apertura-2'), 409, 'apertura_confirmada')
        rechazo(confirmar(web, empresa, {**apertura, 'version': apertura['version'] + 1}, clave='confirmar-apertura-3'), 409,
                'apertura_confirmada')
        assert asientos(empresa) == [('apertura', CORTE, Decimal('10000.00'))]
        # historia y auditoría, una sola vez
        assert eventos(empresa, apertura['id'])[-2:] == [('enviada_revision', 'borrador', 'en_revision'),
                                                         ('confirmada', 'en_revision', 'confirmada')]
        auditadas = acciones(empresa, 'apertura_confirmada')
        assert len(auditadas) == 1 and auditadas[0]['asiento'] == {'id': asiento.pk, 'numero': '2025-000001',
                                                                   'debe': '10000.00', 'haber': '10000.00'}

    def test_la_vista_de_la_empresa_despues_de_confirmar(self, web, empresa, cuentas):
        confirmada(web, empresa, enviada(web, empresa, balance(cuentas)))
        datos = leer(web, API, empresa)
        assert datos['apertura']['estado'] == 'confirmada' and datos['vigente']['asiento']['numero'] == '2025-000001'
        assert datos['apertura']['revisado_por'] == datos['apertura']['confirmado_por'] == 'propietario.a'
        etapa = web.get('/contabilidad/api/inicio/').json()['etapas']['apertura']
        assert etapa == {'estado': 'confirmada', 'fecha': '2025-12-31', 'causa': None}

    def test_con_la_ayuda_de_los_servicios(self, empresa, cuentas):
        """La ayuda 10 000/10 000 de las pruebas confirma con los servicios (crear → mapear → enviar → confirmar)."""
        inicio, apertura = ayudas.apertura_confirmada(empresa, cuentas)
        assert (apertura.estado, apertura.total_debe, inicio.fecha_corte) == ('confirmada', Decimal('10000.00'), CORTE)
        assert asientos(empresa) == [('apertura', CORTE, Decimal('10000.00'))]


# ---------------------------------------------------------------- aceptación 2

class TestAceptacion2:

    def nada_se_escribio(self, empresa, antes):
        assert asientos(empresa) == [] and conteos_de_la_operacion(empresa) == antes['operacion']
        assert en(empresa, LineaApertura.objects.count) == antes['lineas']

    def test_importe_pendiente(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['caja'], '10000.00'), linea(cuentas['capital'], None, None)])
        antes = {'operacion': conteos_de_la_operacion(empresa), 'lineas': en(empresa, LineaApertura.objects.count)}
        datos = validar(web, empresa, apertura)
        assert datos['valida'] is False and codigos(datos['bloqueos']) == ['importe_pendiente']
        assert datos['bloqueos'][0]['lineas'] == ids_de_lineas(empresa, apertura, cuentas['capital'])
        assert datos['apertura']['debe'] is None   # una suma parcial no es el total
        cuerpo = rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'importe_pendiente')
        assert cuerpo['lineas'] == datos['bloqueos'][0]['lineas'] and codigos(cuerpo['bloqueos']) == ['importe_pendiente']
        assert set(cuerpo) >= {'apertura', 'valida', 'bloqueos', 'advertencias', 'ambitos_no_aplican', 'cobertura', 'reportes'}
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).estado) == 'borrador'
        self.nada_se_escribio(empresa, antes)

    def test_diferencia_de_50(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['caja'], '10000.00'), linea(cuentas['capital'], None, '9950.00')])
        antes = {'operacion': conteos_de_la_operacion(empresa), 'lineas': en(empresa, LineaApertura.objects.count)}
        datos = validar(web, empresa, apertura)
        assert datos['bloqueos'] == [{'codigo': 'apertura_desbalanceada', 'texto': TV['apertura_desbalanceada'].format(
            debe='10000.00', haber='9950.00', diferencia='50.00'), 'debe': '10000.00', 'haber': '9950.00', 'diferencia': '50.00'}]
        cuerpo = rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'apertura_desbalanceada')
        assert cuerpo['diferencia'] == '50.00'
        self.nada_se_escribio(empresa, antes)

    def test_al_confirmar_se_revalida_con_el_candado(self, web, empresa, cuentas):
        """Lo que cambió después de enviar (aquí, escrito directamente en la base) se vuelve a comprobar al confirmar."""
        apertura = enviada(web, empresa, balance(cuentas))
        antes = {'operacion': conteos_de_la_operacion(empresa), 'lineas': en(empresa, LineaApertura.objects.count)}
        capital = ids_de_lineas(empresa, apertura, cuentas['capital'])[0]
        en(empresa, lambda: LineaApertura.objects.filter(pk=capital).update(haber=Decimal('9950.00')))
        cuerpo = rechazo(confirmar(web, empresa, apertura), 409, 'apertura_desbalanceada')
        assert cuerpo['diferencia'] == '50.00' and codigos(cuerpo['bloqueos']) == ['apertura_desbalanceada']
        assert 'advertencias' in cuerpo
        en(empresa, lambda: LineaApertura.objects.filter(pk=capital).update(haber=None, debe=None))
        rechazo(confirmar(web, empresa, apertura), 409, 'importe_pendiente')
        en(empresa, lambda: LineaApertura.objects.filter(pk=capital).update(haber=Decimal('10000.00'), debe=Decimal('0')))
        en(empresa, lambda: Cuenta.objects.filter(pk=cuentas['caja'].pk).update(tipo='grupo'))
        cuerpo = rechazo(confirmar(web, empresa, apertura), 409, 'cuenta_de_grupo')
        assert cuerpo['lineas'] == ids_de_lineas(empresa, apertura, cuentas['caja'])
        self.nada_se_escribio(empresa, antes)
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).estado) == 'en_revision'
        assert acciones(empresa, 'apertura_confirmada') == []


# ---------------------------------------------------------------- bloqueos de la regla 5 y advertencias

class TestBloqueos:

    def test_todos_a_la_vez_en_su_orden(self, web, empresa, cuentas):
        sin_clase = en(empresa, lambda: Cuenta.objects.create(codigo='1.1.90', nombre='Sin clase', tipo='movimiento'))
        inactiva = en(empresa, lambda: Cuenta.objects.create(codigo='1.1.91', nombre='Inactiva', tipo='movimiento',
                                                             clase='activo'))
        apertura = preparada(web, empresa, [linea(None, '5.00'), linea(sin_clase, '7.00'), linea(inactiva, None, None),
                                            linea(cuentas['capital'], None, '12.00')])
        en(empresa, lambda: Cuenta.objects.filter(pk=inactiva.pk).update(activa=False))
        datos = validar(web, empresa, apertura)
        assert codigos(datos['bloqueos']) == ['cuenta_sin_mapear', 'cuenta_inactiva', 'importe_pendiente', 'cuenta_sin_clase']
        assert [len(b['lineas']) for b in datos['bloqueos']] == [1, 1, 1, 1]
        assert datos['bloqueos'][0]['texto'] == TV['cuenta_sin_mapear'].format(n=1)

    def test_sin_lineas(self, web, empresa):
        apertura = preparada(web, empresa, [])
        assert codigos(validar(web, empresa, apertura)['bloqueos']) == ['sin_lineas']

    def test_detalle_que_no_concilia_y_vinculo_roto(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['clientes'], '300.00'), linea(cuentas['capital'], None, '300.00')])
        clientes = ids_de_lineas(empresa, apertura, cuentas['clientes'])[0]
        with company_context(empresa):
            AuxiliarApertura.objects.create(
                apertura_id=apertura['id'], linea_id=clientes, cuenta=cuentas['clientes'], naturaleza='cliente',
                saldo_inicial=Decimal('400.00'), tercero_identificacion='0912345678', tercero_nombre='CLIENTE FICTICIO',
                documento_tipo='01', documento_numero='001-001-000000001', cxc_id=987_654_321, creado_por_nombre='x')
        datos = validar(web, empresa, apertura)
        assert codigos(datos['bloqueos']) == ['auxiliar_no_concilia', 'vinculo_roto']
        assert datos['bloqueos'][0]['lineas'] == [clientes] and len(datos['bloqueos'][1]['auxiliares']) == 1

    def test_detalle_de_otra_naturaleza_no_concilia(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['clientes'], '300.00'), linea(cuentas['capital'], None, '300.00')])
        clientes = ids_de_lineas(empresa, apertura, cuentas['clientes'])[0]
        with company_context(empresa):
            AuxiliarApertura.objects.create(apertura_id=apertura['id'], linea_id=clientes, cuenta=cuentas['clientes'],
                                            naturaleza='banco', saldo_inicial=Decimal('100.00'), banco_nombre='BANCO',
                                            creado_por_nombre='x')
        assert codigos(validar(web, empresa, apertura)['bloqueos']) == ['auxiliar_no_concilia']

    def test_sin_saldos_con_lineas_se_contradice(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas), fuente='inicio_actividades', sin_saldos=True,
                             fuente_detalle='Empieza sus actividades el 01/01/2026.')
        assert codigos(validar(web, empresa, apertura)['bloqueos']) == ['sin_saldos_con_lineas']

    def test_corte_de_hoy_no_se_confirma(self, web, empresa, cuentas):
        """El corte de hoy se prepara, pero no se envía ni se confirma hasta que el día termine."""
        hoy = servicio.inicio_contable.hoy()
        apertura = preparada(web, empresa, balance(cuentas), fecha_corte=hoy.isoformat(),
                             cambios={'resultado_ejercicio': 'no_aplica'})
        assert validar(web, empresa, apertura)['bloqueos'] == [{
            'codigo': 'fecha_corte_futura', 'texto': TV['fecha_corte_futura'].format(fecha=hoy), 'fecha_corte': hoy.isoformat()}]
        rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'fecha_corte_futura')

    def test_solapamiento_y_periodo_cerrado_al_confirmar(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        # Después de enviar aparece un asiento ordinario anterior al corte (escrito sin el servicio) y un mes cerrado.
        ayudas.asiento_directo(empresa, [(cuentas['caja'], '5.00', '0'), (cuentas['ventas'], '0', '5.00')],
                               fecha=date(2025, 12, 20))
        en(empresa, lambda: PeriodoContable.objects.create(anio=2026, mes=2, estado='cerrado', cerrado_en=timezone.now(),
                                                           cerrado_por_nombre='x'))
        cuerpo = rechazo(confirmar(web, empresa, apertura), 409, 'rango_solapado')
        assert (cuerpo['asientos'], cuerpo['aplicaciones'], cuerpo['primera_fecha']) == (1, 0, '2025-12-20')
        assert codigos(cuerpo['bloqueos']) == ['rango_solapado', 'periodo_cerrado']
        assert cuerpo['bloqueos'][1]['periodos'] == ['2026-02']
        assert en(empresa, lambda: Asiento.objects.filter(tipo='apertura').count()) == 0

    def test_validar_no_escribe(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['clientes'], '300.00'), linea(cuentas['capital'], None, '300.00')])
        historia, auditoria = en(empresa, EventoApertura.objects.count), AuditLog.objects.filter(company=empresa).count()
        validar(web, empresa, apertura)
        validar(web, empresa, apertura)
        assert en(empresa, EventoApertura.objects.count) == historia
        assert AuditLog.objects.filter(company=empresa).count() == auditoria
        assert leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version'] == apertura['version']

    def test_total_que_no_cabe_en_un_asiento(self, web, empresa, cuentas):
        """B2-AP-4: cada línea admite hasta 999 999 999 999,99, pero el asiento (16, 2) no pasa de 99 999 999 999 999,99 por
        lado (diario.TOTAL_MAX): validar y enviar lo dicen con `importe_total_excedido`, y confirmar lo revalida, en vez de
        fallar en diario.contabilizar con un 400 que no es un bloqueo."""
        from core.contabilidad import diario
        with company_context(empresa):
            Cuenta.objects.bulk_create(
                [Cuenta(company=empresa, codigo=f'{lado}.9.{i:03d}', codigo_norm=norma_codigo(f'{lado}.9.{i:03d}'),
                        nombre=f'Cuenta {lado}.{i}', tipo='movimiento', clase=clase, padre=cuentas[grupo])
                 for lado, clase, grupo in (('1', 'activo', 'activo'), ('2', 'pasivo', 'pasivo')) for i in range(101)])
            activos = list(Cuenta.objects.filter(codigo__startswith='1.9.').order_by('codigo'))
            pasivos = list(Cuenta.objects.filter(codigo__startswith='2.9.').order_by('codigo'))
        mayor = str(servicio.IMPORTE_MAX - servicio.CENTAVO)   # el mayor importe de una línea

        def filas(ultimo):
            return ([linea(c, mayor) for c in activos[:100]] + [linea(activos[100], ultimo)]
                    + [linea(c, None, mayor) for c in pasivos[:100]] + [linea(pasivos[100], None, ultimo)])
        # 100 × 999 999 999 999,99 + 0,99 = 99 999 999 999 999,99 por lado: cabe
        apertura = preparada(web, empresa, filas('0.99'))
        assert validar(web, empresa, apertura)['valida'] is True
        # un centavo más por lado ya no
        mapeada(web, empresa, apertura, filas('1.00'))
        apertura = leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']
        maximo = '99999999999999.99'
        assert str(diario.TOTAL_MAX - servicio.CENTAVO) == maximo
        textos = {'debe': '100000000000000.00', 'haber': '100000000000000.00', 'maximo': maximo}
        assert validar(web, empresa, apertura)['bloqueos'] == [{
            'codigo': 'importe_total_excedido', 'texto': TV['importe_total_excedido'].format(**textos), **textos}]
        cuerpo = rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'importe_total_excedido')
        assert (cuerpo['debe'], cuerpo['maximo']) == ('100000000000000.00', maximo)
        # Enviada con el total que cabe y crecida después (escrito en la base): confirmar lo revalida con el candado.
        mapeada(web, empresa, apertura, filas('0.99'))
        apertura = leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']
        enviada_ = accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura']
        with company_context(empresa):
            LineaApertura.objects.filter(apertura_id=apertura['id'], cuenta=activos[100]).update(debe=Decimal('1.00'))
            LineaApertura.objects.filter(apertura_id=apertura['id'], cuenta=pasivos[100]).update(haber=Decimal('1.00'))
        cuerpo = rechazo(confirmar(web, empresa, enviada_), 409, 'importe_total_excedido')
        assert codigos(cuerpo['bloqueos']) == ['importe_total_excedido']
        assert asientos(empresa) == []
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).estado) == 'en_revision'

    def test_la_forma_de_validar(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas))
        datos = validar(web, empresa, apertura)
        assert list(datos) == ['apertura', 'valida', 'bloqueos', 'advertencias', 'ambitos_no_aplican', 'cobertura', 'reportes']
        assert datos['valida'] is True and datos['bloqueos'] == [] and datos['apertura']['id'] == apertura['id']
        assert datos['cobertura']['contabilidad']['causas_detalle'][0]['codigo'] == 'apertura_sin_confirmar'
        assert [r['reporte'] for r in datos['reportes']] == ['estado_situacion', 'f104_f103_ats', 'resultado_anual_101']
        for reporte in datos['reportes']:
            assert list(reporte) == ['reporte', 'necesita', 'desde', 'hasta', 'provisional', 'causas', 'causas_detalle']
            assert reporte['provisional'] is True and 'apertura_sin_confirmar' in codigos(reporte['causas_detalle'])
        f104 = datos['reportes'][1]
        assert (f104['desde'], f104['hasta']) == ('2026-01-01', '2026-01-31')
        assert codigos(f104['causas_detalle']) == ['apertura_sin_confirmar', 'motor_pendiente']
        # el 101 del año del corte 31/12 no pasa del corte: solo le falta la apertura
        assert codigos(datos['reportes'][2]['causas_detalle']) == ['apertura_sin_confirmar']


class TestAdvertencias:

    def test_detalle_tributario_y_ambitos_sin_cuenta(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, [linea(cuentas['clientes'], '300.00'), linea(cuentas['capital'], None, '300.00')],
                             cambios={'ambitos_no_aplican': [{'ambito': 'activos', 'nota': 'No tiene activos fijos.'}]})
        datos = validar(web, empresa, apertura)
        assert datos['valida'] is True   # el detalle incompleto no impide enviar: se acepta al confirmar
        clientes = ids_de_lineas(empresa, apertura, cuentas['clientes'])[0]
        assert datos['advertencias'][0] == {'codigo': 'auxiliar_incompleto', 'texto': TV['detalle_incompleto'].format(
            codigo='1.1.03', detallado='0.00', importe='300.00'), 'linea_id': clientes}
        sin_cuenta = [a['ambito'] for a in datos['advertencias'] if a['codigo'] == 'sin_cuenta_declarada']
        assert sin_cuenta == ['proveedores', 'inventario', 'bancos', 'tributario']   # activos: declarado que no aplica
        assert 'tributario_sin_saldos' in codigos(datos['advertencias'])
        assert datos['ambitos_no_aplican'] == [{'ambito': 'activos', 'nota': 'No tiene activos fijos.'}]

    def test_cartera_operativa_anterior_al_corte(self, web, empresa, cuentas, admin):
        cliente = helpers.crear_cliente('cliente.apertura', empresa, '0912345678', '0990000003')
        producto = helpers.crear_producto(empresa, 'AP01')
        venta = helpers.crear_venta(empresa, cliente, admin, producto)
        with company_context(empresa):
            Sale.objects.filter(pk=venta.pk).update(emission_date=date(2025, 11, 30))
            CtasCollect.objects.create(sale=venta, debt=Decimal('23.00'), saldo=Decimal('23.00'), date_joined=date(2025, 11, 30))
        apertura = preparada(web, empresa, balance(cuentas))
        aviso = next(a for a in validar(web, empresa, apertura)['advertencias']
                     if a['codigo'] == 'cartera_operativa_anterior_al_corte')
        assert aviso['documentos'] == {'cuentas_por_cobrar': 1, 'cuentas_por_pagar': 0}
        # una cuenta de un documento posterior al corte no cuenta
        en(empresa, lambda: Sale.objects.filter(pk=venta.pk).update(emission_date=date(2026, 1, 2)))
        assert 'cartera_operativa_anterior_al_corte' not in codigos(validar(web, empresa, apertura)['advertencias'])


# ---------------------------------------------------------------- el detalle de cada línea es el de su cuenta

class TestDetalleDeLaCuenta:
    """B2-AP-1: `detalle` es la copia de `cuenta.auxiliar` tomada al mapear, y el auxiliar de la cuenta puede cambiar después
    (cuentas.modificar lo permite sin auxiliares vigentes ni líneas con tercero), también con la apertura en revisión.
    Mientras se prepara, validar, enviar, confirmar, la cobertura, la lista de líneas, el PATCH de los ámbitos y el aviso
    del registro miran la cuenta; confirmar fija la copia con el candado tomado. Antes se confirmaba con la copia vieja:
    sin aceptar una línea cuya cuenta declara detalle, o pidiendo aceptar una que ya no lo declara."""

    def test_la_cuenta_declara_auxiliar_en_revision(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        caja = ids_de_lineas(empresa, apertura, cuentas['caja'])[0]
        cambiar_auxiliar(web, empresa, cuentas['caja'], 'cliente')
        datos = validar(web, empresa, apertura)
        assert {'codigo': 'auxiliar_incompleto', 'texto': TV['detalle_incompleto'].format(
            codigo='1.1.01', detallado='0.00', importe='10000.00'), 'linea_id': caja} in datos['advertencias']
        sin_cuenta = [a['ambito'] for a in datos['advertencias'] if a['codigo'] == 'sin_cuenta_declarada']
        assert 'clientes' not in sin_cuenta
        clientes = {'estado': 'pendiente', 'cuenta': '10000.00', 'detallado': '0.00', 'documentos': 0}
        assert datos['cobertura']['cartera']['clientes'] == clientes
        # para confirmar hay que aceptarla (contrato §6.5, regla 8)
        assert rechazo(confirmar(web, empresa, apertura), 409, 'auxiliar_incompleto')['lineas'] == [caja]
        datos = confirmada(web, empresa, apertura, aceptadas=[caja])
        guardada = en(empresa, lambda: LineaApertura.objects.get(pk=caja))
        assert (guardada.detalle, guardada.incompleto_aceptado) == ('cliente', True)
        assert datos['cobertura']['contabilidad']['estado'] == 'parcial'
        assert datos['cobertura']['cartera']['clientes'] == clientes
        confirmacion = en(empresa, lambda: EventoApertura.objects.get(apertura_id=apertura['id'], accion='confirmada').detalle)
        assert confirmacion['detalle_fijado'] == [{'linea_id': caja, 'anterior': '', 'nuevo': 'cliente'}]
        assert confirmacion['incompletos_aceptados'] == [caja]

    def test_la_cuenta_deja_de_declarar_auxiliar_en_revision(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, [linea(cuentas['clientes'], '10000.00'), linea(cuentas['capital'], None, '10000.00')])
        clientes = ids_de_lineas(empresa, apertura, cuentas['clientes'])[0]
        cambiar_auxiliar(web, empresa, cuentas['clientes'], '')
        assert 'auxiliar_incompleto' not in codigos(validar(web, empresa, apertura)['advertencias'])
        cuerpo = rechazo(confirmar(web, empresa, apertura, aceptadas=[clientes]), 409, 'auxiliar_incompleto')
        assert (cuerpo['lineas'], cuerpo['sobran']) == ([], [clientes])
        datos = confirmada(web, empresa, apertura)
        guardada = en(empresa, lambda: LineaApertura.objects.get(pk=clientes))
        assert (guardada.detalle, guardada.incompleto_aceptado) == ('', False)
        assert datos['cobertura']['contabilidad']['estado'] == 'conciliada'
        assert datos['cobertura']['cartera']['clientes'] == {'estado': 'pendiente', 'cuenta': None, 'detallado': None,
                                                              'documentos': 0}
        assert en(empresa, lambda: EventoApertura.objects.get(apertura_id=apertura['id'], accion='confirmada').detalle)[
            'detalle_fijado'] == [{'linea_id': clientes, 'anterior': 'cliente', 'nuevo': ''}]

    def test_el_ambito_que_no_aplica_y_la_cuenta_que_lo_contradice(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas), cambios={'ambitos_no_aplican': [
            {'ambito': 'clientes', 'nota': 'No vende a crédito.'}]})
        caja = ids_de_lineas(empresa, apertura, cuentas['caja'])[0]
        cambiar_auxiliar(web, empresa, cuentas['caja'], 'cliente')
        bloqueo = {'codigo': 'cuenta_no_aplica', 'texto': TV['cuenta_no_aplica'].format(n=1, ambitos='clientes'),
                   'lineas': [caja], 'ambitos': ['clientes']}
        assert validar(web, empresa, apertura)['bloqueos'] == [bloqueo]
        cuerpo = rechazo(confirmar(web, empresa, apertura, aceptadas=[caja]), 409, 'cuenta_no_aplica')
        assert (cuerpo['lineas'], cuerpo['ambitos'], codigos(cuerpo['bloqueos'])) == ([caja], ['clientes'], ['cuenta_no_aplica'])
        assert asientos(empresa) == []
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).ambitos_no_aplican) == [
            {'ambito': 'clientes', 'nota': 'No vende a crédito.'}]   # nada congelado
        # sin el auxiliar, la declaración vale y se confirma
        cambiar_auxiliar(web, empresa, cuentas['caja'], '')
        datos = confirmada(web, empresa, apertura)
        assert datos['cobertura']['cartera']['clientes']['estado'] == 'no_aplica'

    def test_en_borrador_sin_volver_a_mapear(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas))
        caja = ids_de_lineas(empresa, apertura, cuentas['caja'])[0]
        cambiar_auxiliar(web, empresa, cuentas['caja'], 'cliente')
        # el PATCH de los ámbitos mira la cuenta, como mapear
        no_aplica = {'version': apertura['version'], 'ambitos_no_aplican': [{'ambito': 'clientes', 'nota': 'No aplica.'}]}
        assert rechazo(envio(web, f'{API}{apertura["id"]}/', empresa, no_aplica, 'patch'), 400, 'validacion')['errores'] == {
            'ambitos_no_aplican.0.ambito': [servicio.TEXTOS['ambito_con_cuentas']]}
        # la lista de líneas, la cobertura de la empresa y el aviso del registro, también
        lista = {l['id']: l for l in leer(web, f'{API}{apertura["id"]}/lineas/', empresa)['lineas']}
        assert (lista[caja]['detalle'], lista[caja]['auxiliares']['estado']) == ('cliente', 'sin_detalle')
        assert leer(web, API, empresa)['cobertura']['cartera']['clientes'] == {
            'estado': 'pendiente', 'cuenta': '10000.00', 'detallado': '0.00', 'documentos': 0}
        avisos = {a['codigo']: a for a in web.get(CAPACIDADES).json()['funciones']['apertura']['avisos']}
        assert avisos['auxiliares_incompletos']['cantidad'] == 1
        # declarado antes de que la cuenta cambie: enviar lo bloquea
        cambiar_auxiliar(web, empresa, cuentas['caja'], '')
        assert envio(web, f'{API}{apertura["id"]}/', empresa, no_aplica, 'patch').status_code == 200
        cambiar_auxiliar(web, empresa, cuentas['caja'], 'cliente')
        cuerpo = rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version'] + 1), 409, 'cuenta_no_aplica')
        assert cuerpo['lineas'] == [caja]
        assert en(empresa, lambda: LineaApertura.objects.get(pk=caja).detalle) == ''   # validar y enviar no escriben

    def test_confirmada_vale_lo_que_se_fijo(self, web, empresa, cuentas):
        """Después de confirmar, la Parte A deja cambiar el auxiliar (sin auxiliares vigentes): la apertura confirmada no
        cambia, y su lista de líneas y su cobertura siguen con el detalle fijado al confirmar."""
        apertura = enviada(web, empresa, balance(cuentas))
        confirmada(web, empresa, apertura)
        caja = ids_de_lineas(empresa, apertura, cuentas['caja'])[0]
        cambiar_auxiliar(web, empresa, cuentas['caja'], 'cliente')
        lista = {l['id']: l for l in leer(web, f'{API}{apertura["id"]}/lineas/', empresa)['lineas']}
        assert (lista[caja]['detalle'], lista[caja]['auxiliares']['estado']) == ('', 'sin_declarar')
        assert leer(web, API, empresa)['cobertura']['cartera']['clientes']['cuenta'] is None
        assert 'auxiliares_incompletos' not in {a['codigo'] for a in web.get(CAPACIDADES).json()['funciones']['apertura']['avisos']}


# ---------------------------------------------------------------- aceptación 7: el resultado del ejercicio

class TestAceptacion7:

    def test_mitad_de_anio_con_nominales(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, mitad_de_anio(cuentas), fecha_corte=MITAD.isoformat())
        datos = confirmada(web, empresa, apertura)
        assert datos['apertura']['asiento']['fecha'] == '2026-06-30' and datos['apertura']['debe'] == '8000.00'
        guardada = en(empresa, lambda: Apertura.objects.get(pk=apertura['id']))
        assert guardada.resultado_ejercicio == 'en_cuentas_nominales'   # lo que dicen las líneas
        with company_context(empresa):
            assert 'resultados_acumulados_sin_detalle' not in codigos(
                reportes.provisionalidad('estado_resultados', date(2026, 1, 1), MITAD)[2])

    def test_nominales_y_linea_de_resultado_es_duplicado(self, web, empresa, cuentas):
        filas = mitad_de_anio(cuentas, linea(cuentas['resultados'], None, '1000.00', es_resultado_ejercicio=True))
        filas[0] = linea(cuentas['caja'], '7000.00')
        apertura = preparada(web, empresa, filas, fecha_corte=MITAD.isoformat())
        datos = validar(web, empresa, apertura)
        assert codigos(datos['bloqueos']) == ['resultado_duplicado']
        assert {k: datos['bloqueos'][0][k] for k in ('en_cuentas_nominales', 'en_patrimonio')} == {
            'en_cuentas_nominales': '1000.00', 'en_patrimonio': '1000.00'}
        cuerpo = rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'resultado_duplicado')
        assert (cuerpo['en_cuentas_nominales'], cuerpo['en_patrimonio']) == ('1000.00', '1000.00')

    def test_resultado_acumulado_declarado_distinto(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, mitad_de_anio(cuentas), fecha_corte=MITAD.isoformat(),
                             cambios={'resultado_acumulado': '900.00'})
        assert codigos(validar(web, empresa, apertura)['bloqueos']) == ['resultado_duplicado']
        envio(web, f'{API}{apertura["id"]}/', empresa, {'version': apertura['version'], 'resultado_acumulado': '1000.00'},
              'patch')
        assert validar(web, empresa, {**apertura, 'version': apertura['version'] + 1})['valida'] is True

    def test_solo_en_patrimonio(self, web, empresa, cuentas):
        filas = [linea(cuentas['caja'], '6000.00'), linea(cuentas['capital'], None, '5000.00'),
                 linea(cuentas['resultados'], None, '1000.00', es_resultado_ejercicio=True)]
        apertura = enviada(web, empresa, filas, fecha_corte=MITAD.isoformat())
        confirmada(web, empresa, apertura)
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).resultado_ejercicio) == 'en_patrimonio'
        with company_context(empresa):
            assert 'resultados_acumulados_sin_detalle' in codigos(
                reportes.provisionalidad('estado_resultados', date(2026, 1, 1), MITAD)[2])
            assert 'resultados_acumulados_sin_detalle' in codigos(
                reportes.provisionalidad('resultado_anual_101', date(2026, 1, 1), date(2026, 12, 31))[2])

    def test_sin_declarar_y_no_aplica_con_su_nota(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas), fecha_corte=MITAD.isoformat())
        datos = validar(web, empresa, apertura)
        assert codigos(datos['bloqueos']) == ['resultado_sin_declarar']
        assert 'sin_resultados_acumulados' in codigos(datos['advertencias'])
        # el 101 del año del corte a mitad de año queda provisional (pasa del corte)
        assert codigos(datos['reportes'][2]['causas_detalle']) == ['apertura_sin_confirmar', 'motor_pendiente']
        rechazo(accion(web, empresa, apertura, 'enviar', version=apertura['version']), 409, 'resultado_sin_declarar')
        envio(web, f'{API}{apertura["id"]}/', empresa, {'version': apertura['version'], 'resultado_ejercicio': 'no_aplica'},
              'patch')
        respuesta = accion(web, empresa, apertura, 'enviar', version=apertura['version'] + 1)
        assert respuesta.status_code == 200, respuesta.content
        enviada_ = respuesta.json()['apertura']
        # «no aplica» exige la nota de la revisión al confirmar
        rechazo(confirmar(web, empresa, enviada_), 409, 'resultado_sin_declarar')
        datos = confirmada(web, empresa, enviada_, nota='La empresa no tuvo actividad antes del corte.')
        assert datos['apertura']['estado'] == 'confirmada'

    def test_31_de_diciembre_con_nominales(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, mitad_de_anio(cuentas))
        datos = validar(web, empresa, apertura)
        assert datos['valida'] is True
        assert {'codigo': 'ejercicio_sin_cerrar', 'texto': TV['ejercicio_sin_cerrar'].format(anio=2025)} in datos['advertencias']
        confirmada(web, empresa, accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura'])
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).resultado_ejercicio) == 'en_cuentas_nominales'


# ---------------------------------------------------------------- enviar, devolver y estados

class TestEstados:

    def test_enviar_y_devolver(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas))
        en_revision = accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura']
        assert (en_revision['estado'], en_revision['version'], en_revision['enviado_por']) == (
            'en_revision', apertura['version'] + 1, 'propietario.a')
        # en revisión ya no se edita, pero se valida y se descarta
        rechazo(envio(web, f'{API}{apertura["id"]}/', empresa, {'version': en_revision['version'], 'fuente': 'otra'}, 'patch'),
                409, 'estado')
        assert validar(web, empresa, en_revision)['valida'] is True
        rechazo(accion(web, empresa, en_revision, 'enviar', version=en_revision['version']), 409, 'estado')
        rechazo(accion(web, empresa, en_revision, 'devolver', version=en_revision['version']), 400, 'validacion')
        devuelta = accion(web, empresa, en_revision, 'devolver', version=en_revision['version'],
                          motivo='Falta el balance firmado.').json()['apertura']
        assert (devuelta['estado'], devuelta['version'], devuelta['enviado_por']) == ('borrador', en_revision['version'] + 1,
                                                                                     None)
        rechazo(accion(web, empresa, devuelta, 'devolver', version=devuelta['version'], motivo='x'), 409, 'estado')
        rechazo(confirmar(web, empresa, devuelta), 409, 'estado')
        assert eventos(empresa, apertura['id'])[-2:] == [('enviada_revision', 'borrador', 'en_revision'),
                                                         ('devuelta', 'en_revision', 'borrador')]
        assert acciones(empresa, 'apertura_devuelta')[0]['motivo'] == 'Falta el balance firmado.'
        assert len(acciones(empresa, 'apertura_enviada_revision')) == 1

    def test_version_en_cada_envio(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas))
        vieja = {**apertura, 'version': apertura['version'] - 1}
        for que, extra in (('validar', {}), ('enviar', {})):
            rechazo(accion(web, empresa, vieja, que, version=vieja['version'], **extra), 409, 'version')
        en_revision = accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura']
        rechazo(accion(web, empresa, apertura, 'devolver', version=apertura['version'], motivo='x'), 409, 'version')
        rechazo(confirmar(web, empresa, apertura), 409, 'version')
        # sin versión: error de campo
        assert rechazo(accion(web, empresa, en_revision, 'devolver', motivo='x'), 400, 'validacion')['errores'] == {
            'version': [servicio.TEXTOS['version_falta']]}

    def test_confirmar_pide_revisado_y_la_clave(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        respuesta = confirmar(web, empresa, apertura, revisado=False)
        assert rechazo(respuesta, 400, 'validacion')['errores'] == {'revisado': [TV['revisado']]}
        assert rechazo(confirmar(web, empresa, apertura, nota='x' * 501, incompletos_aceptados='1'), 400, 'validacion')[
            'errores'] == {'nota': [TV['nota_larga']], 'incompletos_aceptados': [TV['incompletos']]}
        assert rechazo(accion(web, empresa, apertura, 'confirmar', version=apertura['version'], revisado=True), 400, 'clave')
        assert asientos(empresa) == []

    def test_una_confirmada_no_se_edita(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        datos = confirmada(web, empresa, apertura)
        version = datos['apertura']['version']
        actual = {**apertura, 'version': version}
        rechazo(envio(web, f'{API}{apertura["id"]}/', empresa, {'version': version, 'fuente': 'estado_situacion'}, 'patch'),
                409, 'estado')
        rechazo(envio(web, f'{API}{apertura["id"]}/mapear/', empresa, {'version': version, 'lineas': balance(cuentas)}), 409,
                'estado')
        rechazo(accion(web, empresa, actual, 'descartar', version=version, motivo='x'), 409, 'estado')
        for que in ('validar', 'enviar'):
            rechazo(accion(web, empresa, actual, que, version=version), 409, 'estado')
        rechazo(accion(web, empresa, actual, 'devolver', version=version, motivo='x'), 409, 'estado')
        rechazo(confirmar(web, empresa, actual), 409, 'apertura_confirmada')
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).version) == version
        assert asientos(empresa) == [('apertura', CORTE, Decimal('10000.00'))]

    def test_capacidades_por_estado(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas))
        en_revision = accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura']
        capacidades_ = leer(web, f'{API}{apertura["id"]}/', empresa)['capacidades']
        assert {a for a, v in capacidades_.items() if v} == {'validar', 'devolver', 'confirmar', 'descartar'}
        confirmada(web, empresa, en_revision)
        assert not any(leer(web, f'{API}{apertura["id"]}/', empresa)['capacidades'].values())

    def test_etapa_en_revision(self, web, empresa, cuentas):
        enviada(web, empresa, balance(cuentas))
        assert web.get('/contabilidad/api/inicio/').json()['etapas']['apertura'] == {
            'estado': 'en_revision', 'fecha': '2025-12-31', 'causa': None}


# ---------------------------------------------------------------- confirmar: incompletos, sin saldos, historial, inicio

class TestConfirmar:

    def test_incompletos_aceptados_linea_por_linea(self, web, empresa, cuentas):
        filas = [linea(cuentas['clientes'], '3000.00'), linea(cuentas['bancos'], '5000.00'),
                 linea(cuentas['capital'], None, '8000.00')]
        apertura = enviada(web, empresa, filas)
        clientes, bancos = ids_de_lineas(empresa, apertura, cuentas['clientes'], cuentas['bancos'])
        cuerpo = rechazo(confirmar(web, empresa, apertura), 409, 'auxiliar_incompleto')
        assert cuerpo['lineas'] == sorted([clientes, bancos]) and 'sobran' not in cuerpo
        assert rechazo(confirmar(web, empresa, apertura, aceptadas=[clientes]), 409, 'auxiliar_incompleto')['lineas'] == [bancos]
        capital = ids_de_lineas(empresa, apertura, cuentas['capital'])[0]
        cuerpo = rechazo(confirmar(web, empresa, apertura, aceptadas=[clientes, bancos, capital]), 409, 'auxiliar_incompleto')
        assert (cuerpo['lineas'], cuerpo['sobran']) == ([], [capital])
        datos = confirmada(web, empresa, apertura, aceptadas=[bancos, clientes])
        assert en(empresa, lambda: sorted(LineaApertura.objects.filter(incompleto_aceptado=True).values_list('id', flat=True))) == \
            sorted([clientes, bancos])
        assert datos['cobertura']['contabilidad']['estado'] == 'parcial'
        assert datos['cobertura']['contabilidad']['causas_detalle'][0]['codigo'] == 'detalle_incompleto_aceptado'
        assert en(empresa, Asiento.objects.count) == 1

    def test_sin_saldos_se_confirma_sin_asiento(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, [], fuente='inicio_actividades', sin_saldos=True,
                           fuente_detalle='Empieza sus actividades el 01/01/2026.')
        datos = confirmada(web, empresa, apertura)
        assert datos['apertura'] == {**datos['apertura'], 'estado': 'confirmada', 'asiento': None, 'debe': '0.00',
                                     'haber': '0.00', 'diferencia': '0.00'}
        assert asientos(empresa) == [] and datos['cobertura']['contabilidad']['estado'] == 'conciliada'
        assert acciones(empresa, 'apertura_confirmada')[0]['asiento'] is None
        # el diario posterior al corte sigue provisional: la operación todavía no se contabiliza
        diario = leer(web, '/contabilidad/api/diario/?desde=2026-01-01&hasta=2026-01-31', empresa)
        assert diario['provisional'] is True and codigos(diario['causas_detalle']) == ['motor_pendiente']

    def test_historial(self, web, empresa, cuentas):
        apertura = preparada(web, empresa, balance(cuentas), modalidad='historial', fecha_corte=None,
                             historial_desde='2025-07-01', historial_hasta='2025-09-30',
                             cambios={'resultado_ejercicio': 'en_patrimonio'})
        datos = leer(web, API, empresa)
        assert datos['configuracion']['fecha_corte'] == '2025-06-30'
        assert codigos(datos['cobertura']['contabilidad']['causas_detalle']) == ['saldo_anterior_sin_confirmar']
        diario = leer(web, '/contabilidad/api/diario/?desde=2025-07-01&hasta=2025-07-31', empresa)
        assert diario['provisional'] is True and codigos(diario['causas_detalle']) == ['saldo_anterior_sin_confirmar',
                                                                                        'motor_pendiente']
        enviada_ = accion(web, empresa, apertura, 'enviar', version=apertura['version']).json()['apertura']
        datos = confirmada(web, empresa, enviada_)
        assert datos['apertura']['asiento']['fecha'] == '2025-06-30'
        assert datos['cobertura']['contabilidad']['estado'] == 'conciliada'
        inicio = en(empresa, InicioContable.objects.get)
        assert (inicio.contabilidad_desde, inicio.operaciones_desde) == (date(2025, 7, 1), date(2025, 10, 1))
        diario = leer(web, '/contabilidad/api/diario/?desde=2025-07-01&hasta=2025-07-31', empresa)
        assert codigos(diario['causas_detalle']) == ['motor_pendiente']

    def test_el_inicio_contable_sigue_al_corte_de_la_apertura(self, web, empresa, cuentas):
        """Paso 8: la configuración dice el corte de la apertura confirmada (aquí distinto a propósito, escrito en la base)."""
        apertura = enviada(web, empresa, balance(cuentas))
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(fecha_corte=date(2024, 12, 31)))
        datos = confirmada(web, empresa, apertura)
        inicio = en(empresa, InicioContable.objects.get)
        assert (inicio.fecha_corte, inicio.contabilidad_desde, inicio.version) == (date(2024, 12, 31), date(2025, 1, 1), 2)
        assert datos['apertura']['asiento']['fecha'] == '2024-12-31'
        assert ('inicio_configurado', '', '') in eventos(empresa, None)

    def test_ambitos_que_no_aplican_quedan_congelados(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas), cambios={'ambitos_no_aplican': [
            {'ambito': 'inventario', 'nota': 'Presta servicios: no tiene inventario.'}]})
        confirmada(web, empresa, apertura)
        declarado = en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).ambitos_no_aplican)
        assert declarado == [{'ambito': 'inventario', 'nota': 'Presta servicios: no tiene inventario.',
                              'declarado_por': 'propietario.a', 'declarado_en': declarado[0]['declarado_en']}]
        assert leer(web, API, empresa)['cobertura']['inventario']['estado'] == 'no_aplica'

    def test_no_toca_la_operacion(self, web, empresa, cuentas, admin):
        cliente = helpers.crear_cliente('cliente.operacion', empresa, '0912345679', '0990000004')
        producto = helpers.crear_producto(empresa, 'OP01')
        venta = helpers.crear_venta(empresa, cliente, admin, producto)
        en(empresa, lambda: CtasCollect.objects.create(sale=venta, debt=Decimal('23.00'), saldo=Decimal('23.00')))
        antes = conteos_de_la_operacion(empresa)
        apertura = enviada(web, empresa, [linea(cuentas['inventario'], '2000.00'), linea(cuentas['clientes'], '3000.00'),
                                          linea(cuentas['capital'], None, '5000.00')])
        confirmada(web, empresa, apertura, aceptadas=ids_de_lineas(empresa, apertura, cuentas['inventario'], cuentas['clientes']))
        assert conteos_de_la_operacion(empresa) == antes
        assert en(empresa, lambda: CtasCollect.objects.get().saldo) == Decimal('23.00')

    def test_el_diario_posterior_al_corte_sigue_provisional(self, web, empresa, cuentas):
        confirmada(web, empresa, enviada(web, empresa, balance(cuentas)))
        despues = leer(web, '/contabilidad/api/diario/?desde=2026-01-01&hasta=2026-01-31', empresa)
        assert despues['provisional'] is True and codigos(despues['causas_detalle']) == ['motor_pendiente']
        hasta_el_corte = leer(web, '/contabilidad/api/diario/?desde=2025-12-01&hasta=2025-12-31', empresa)
        assert hasta_el_corte['provisional'] is False and hasta_el_corte['causas_detalle'] == []
        assert [a['tipo'] for a in hasta_el_corte['asientos']] == ['apertura']
        integridad = leer(web, '/contabilidad/api/integridad/?anio=2025', empresa)
        assert all(c['ok'] for c in integridad['comprobaciones']), integridad


# ---------------------------------------------------------------- aceptación 8: empresas, pestaña, roles y licencia

RUTAS_NUEVAS = (('validar', servicio.PREPARAR), ('enviar', servicio.PREPARAR), ('devolver', servicio.CONFIRMAR),
                ('confirmar', servicio.CONFIRMAR))


class TestAceptacion8:

    @pytest.mark.parametrize('rol, preparar, confirmar_', [
        (ROLE_OWNER, True, True), (ROLE_ADMIN, True, True), (ROLE_ACCOUNTANT, True, True), (ROLE_READONLY, False, False),
        (ROLE_SELLER, False, False), (ROLE_CLIENT, False, False)])
    def test_matriz_de_los_seis_roles(self, client, empresa, cuentas, rol, preparar, confirmar_):
        apertura = ayudas.apertura_directa(empresa)
        entrar_como(client, empresa, rol)
        for que, permiso in RUTAS_NUEVAS:
            respuesta = envio(client, f'{API}{apertura.pk}/{que}/', empresa, {'version': 99})
            permitido = preparar if permiso == servicio.PREPARAR else confirmar_
            sin_permiso = respuesta.status_code == 403 and respuesta.json().get('codigo') == 'sin_permiso'
            assert sin_permiso is not permitido, (rol, que, respuesta.status_code, respuesta.content[:200])

    def test_dos_empresas(self, client, empresa, empresa_b, admin, cuentas):
        from django.contrib.auth.models import Group

        from core.tenancy.models import Membership
        ayudas.plan_minimo(empresa_b)
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        de_a = enviada(client, empresa, balance(cuentas))
        client.post('/empresas/cambiar/', {'company': empresa_b.pk})
        for que, _ in RUTAS_NUEVAS:
            # la pestaña de A sigue abierta: 409, no escribe en B
            rechazo(accion(client, empresa, de_a, que, version=de_a['version'], motivo='x'), 409, 'empresa_cambiada')
            # desde B, la apertura de A no existe
            rechazo(accion(client, empresa_b, de_a, que, version=de_a['version'], motivo='x', clave=ayudas.clave('b'),
                           revisado=True), 404, 'no_existe')
        assert en(empresa, lambda: Apertura.objects.get(pk=de_a['id']).estado) == 'en_revision'
        assert asientos(empresa) == [] and asientos(empresa_b) == []

    def test_plan_vencido(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        vencer(empresa)
        for que, _ in RUTAS_NUEVAS:
            respuesta = confirmar(web, empresa, apertura) if que == 'confirmar' else \
                accion(web, empresa, apertura, que, version=apertura['version'], motivo='x')
            assert respuesta.status_code == 403 and respuesta.json()['codigo'] == 'plan', que
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).estado) == 'en_revision'

    def test_complemento_cerrado(self, web, empresa, cuentas, settings):
        apertura = enviada(web, empresa, balance(cuentas))
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        for que, _ in RUTAS_NUEVAS:
            cuerpo = accion(web, empresa, apertura, que, version=apertura['version']).json()
            assert (cuerpo['codigo'], cuerpo['causa']) == ('complemento_pendiente', 'licencia'), que
        # pestaña vieja: 409 antes que la licencia (también con la empresa solo en el cuerpo JSON: manda el código real del
        # bloque 1, core/tenancy/pestanas.py)
        rechazo(web.post(f'{API}{apertura["id"]}/confirmar/?empresa={empresa.pk + 999}', json.dumps({'version': 1}),
                         content_type='application/json'), 409, 'empresa_cambiada')
        rechazo(web.post(f'{API}{apertura["id"]}/confirmar/', json.dumps({'empresa': empresa.pk + 999}),
                         content_type='application/json'), 409, 'empresa_cambiada')
        assert asientos(empresa) == []


# ---------------------------------------------------------------- aceptación 10: sin SRI, sin correo, sin documentos

class TestAceptacion10:

    @pytest.fixture
    def empresa(self, settings, p12):
        """La empresa emisora de tests/test_emision_sri.py (firma de prueba, ambiente de producción simulado)."""
        settings.FPA_RUC_PROVEEDOR = emision_sri.RUC_PROVEEDOR
        empresa = helpers.crear_empresa('EMISORA', environment_type=2)
        helpers.configurar_facturacion(empresa, estab='001', punto='002', ultimo_factura=270, ultimo_nota=4, ambiente=2)
        empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
        empresa.electronic_signature_key = CLAVE_FIRMA
        empresa.save()
        return empresa

    def test_confirmar_no_emite_y_la_factura_sigue(self, web, empresa, cuentas, sri, settings):
        comprador = helpers.crear_cliente('comprador.apertura', empresa, '0991234567001', '0990000002')
        en(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(identification_type='04'))
        producto = helpers.crear_producto(empresa, 'P100', pvp='10.00')
        antes = conteos_de_la_operacion(empresa)
        mail.outbox = []
        confirmada(web, empresa, enviada(web, empresa, balance(cuentas)))
        assert (sri.recepciones, sri.consultas, sri.urls, mail.outbox) == ([], [], [], [])
        assert conteos_de_la_operacion(empresa) == antes
        # La emisión básica sigue funcionando aunque el complemento no esté contratado.
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = emision_sri.vender(web, comprador, producto)
        assert respuesta['resp'] is True and respuesta['estado'] == 'authorized'
        assert len(sri.recepciones) == 1 and asientos(empresa) == [('apertura', CORTE, Decimal('10000.00'))]


# ---------------------------------------------------------------- rendimiento

def consultas(funcion):
    with CaptureQueriesContext(connection) as capturadas:
        resultado = funcion()
    return len(capturadas), resultado


class TestRendimiento:

    def test_5000_lineas_validan_y_confirman_sin_consultas_por_linea(self, web, empresa, cuentas):
        ids = plan_grande(empresa, 5000)

        def lineas(n):
            filas = [{'cuenta_id': pk, 'rubro': f'R{i}', 'debe': '2.00', 'haber': None} for i, pk in enumerate(ids[:n - 1])]
            return filas + [{'cuenta_id': ids[n - 1], 'rubro': 'Contrapartida', 'debe': None, 'haber': f'{2 * (n - 1)}.00'}]

        def preparar(n):
            apertura = creada(web, empresa)
            mapeada(web, empresa, apertura, lineas(n))
            return leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']

        pocas = preparar(10)
        n_validar_pocas, _ = consultas(lambda: validar(web, empresa, pocas))
        n_enviar_pocas, r = consultas(lambda: accion(web, empresa, pocas, 'enviar', version=pocas['version']))
        assert r.status_code == 200, r.content
        accion(web, empresa, r.json()['apertura'], 'descartar', version=r.json()['apertura']['version'], motivo='Solo medía.')

        todas = preparar(5000)
        n_validar, datos = consultas(lambda: validar(web, empresa, todas))
        assert datos['valida'] is True, datos['bloqueos']
        n_enviar, r = consultas(lambda: accion(web, empresa, todas, 'enviar', version=todas['version']))
        assert r.status_code == 200, r.content
        n_confirmar, r = consultas(lambda: confirmar(web, empresa, r.json()['apertura']))
        assert r.status_code == 200, r.content
        assert r.json()['apertura']['debe'] == '9998.00' and en(empresa, LineaAsiento.objects.count) == 5000
        # Validar y enviar no crecen con las líneas: las consultas son agregadas.
        assert n_validar <= n_validar_pocas + 2 and n_enviar <= n_enviar_pocas + 2, (n_validar_pocas, n_validar, n_enviar)
        # Confirmar inserta las 5 000 líneas del asiento y sus acumulados por lotes: en PostgreSQL, uno cada 1 000 filas;
        # SQLite los parte además por su límite de variables por sentencia. Nunca una consulta por línea.
        lotes = 12 if connection.vendor == 'postgresql' else 5000 * 40 // 999 + 12
        assert n_confirmar <= 70 + lotes, n_confirmar
