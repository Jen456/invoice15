"""Textos libres de la apertura con caracteres de control (B2-AP-3): el detalle de la fuente (crear y PATCH), la nota de un
ámbito que no aplica, el rubro de una línea, el motivo de descartar, devolver y anular un respaldo, la nota de confirmar, la
descripción de un respaldo y el motivo de omitir una fila del lote.

PostgreSQL no guarda el carácter NUL en un texto (ni `\\u0000` en un JSON): la petición acababa en 500 con
`django.db.utils.DataError`, y en SQLite se guardaba. Ahora es un 400 `validacion` con el error en su campo y un texto propio
(`caracteres_de_control`), y no se escribe nada. Lo mismo con el resto de los controles C0, DEL y una mitad suelta de un
par sustituto (no se escribe en UTF-8: también era un 500). No se rechaza lo que isprintable() rechazaría sin motivo en un
texto pegado: el guion opcional (U+00AD), el espacio de ancho cero (U+200B), la marca de orden de bytes (U+FEFF) y los
emoji compuestos con ZWJ; el tabulador y los saltos de línea se colapsan en un espacio, como siempre.

Corre en SQLite y en PostgreSQL (tests/../herramientas/pytest_pg.sh con este archivo). Datos ficticios."""
import pytest
from core.contabilidad import apertura as servicio
from core.contabilidad.models import Apertura, EventoApertura, ImportacionApertura, LineaApertura, RespaldoApertura
from tests import ayudas_contables as ayudas
from tests.test_apertura import accion, confirmar, enviada
from tests.test_apertura_importar import PDF, SALDOS, csv_de, mapear_lote, subido, subir_respaldo
from tests.test_apertura_preparar import (API, DATOS, balance, creada, en, enviar, errores, leer, linea, mapeada,
                                          mapear)
from tests.test_apertura_preparar import cuentas, web   # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db

T = servicio.TEXTOS['caracteres_de_control']
NUL = 'Balance\x00 firmado'
CONTROLES = ['Caja\x00chica', 'Caja\x07', '\x1b[31mCaja', 'Caja\x7f', 'Caja\x08', 'Caja\ud800']
ADMITIDOS = [('Caja­chica', 'Caja­chica'), ('Caja​chica', 'Caja​chica'), ('﻿Caja', '﻿Caja'),
             ('Caja 👩‍💻', 'Caja 👩‍💻'), ('Caja\tchica\r\nde la\x1coficina', 'Caja chica de la oficina')]


def version(web, empresa, apertura):
    return leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version']


def historia(empresa):
    return en(empresa, lambda: list(EventoApertura.objects.order_by('id').values_list('id', flat=True)))


class TestEncabezado:

    def test_crear(self, web, empresa):
        assert errores(enviar(web, API, empresa, {'clave': ayudas.clave('crear'), **DATOS, 'fuente_detalle': NUL})) == {
            'fuente_detalle': [T]}
        assert en(empresa, Apertura.objects.count) == 0

    def test_detalle_de_la_fuente_y_ambitos(self, web, empresa):
        apertura = creada(web, empresa)
        antes = historia(empresa)
        ruta = f'{API}{apertura["id"]}/'
        assert errores(enviar(web, ruta, empresa, {'version': 1, 'fuente_detalle': NUL}, 'patch')) == {'fuente_detalle': [T]}
        assert errores(enviar(web, ruta, empresa, {'version': 1, 'ambitos_no_aplican': [
            {'ambito': 'activos', 'nota': 'Sin activos\x00'}]}, 'patch')) == {'ambitos_no_aplican.0.nota': [T]}
        guardada = en(empresa, lambda: Apertura.objects.get(pk=apertura['id']))
        assert (guardada.version, guardada.fuente_detalle, guardada.ambitos_no_aplican) == (1, DATOS['fuente_detalle'], [])
        assert historia(empresa) == antes


class TestLineas:

    @pytest.mark.parametrize('rubro', CONTROLES, ids=['nul', 'bel', 'esc', 'del', 'bs', 'sustituto'])
    def test_rubro_con_control(self, web, empresa, cuentas, rubro):
        apertura = creada(web, empresa)
        assert errores(mapear(web, empresa, apertura, [linea(cuentas['caja'], '10.00', rubro=rubro),
                                                       linea(cuentas['capital'], None, '10.00')])) == {'lineas.0.rubro': [T]}
        assert en(empresa, LineaApertura.objects.count) == 0 and version(web, empresa, apertura) == 1

    def test_lo_que_si_se_admite(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        filas = [linea(cuentas[c], '1.00', rubro=rubro) for c, (rubro, _) in zip(('caja', 'bancos', 'clientes', 'inventario',
                                                                                    'credito_iva'), ADMITIDOS)]
        datos = mapeada(web, empresa, apertura, [*filas, linea(cuentas['capital'], None, '5.00')])
        assert [l['rubro'] for l in datos['lineas'][:5]] == [guardado for _, guardado in ADMITIDOS]


class TestMotivosYNotas:

    def test_descartar(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(accion(web, empresa, apertura, 'descartar', version=1, motivo='Error\x00')) == {'motivo': [T]}
        # el largo va antes: un texto demasiado largo da ese error, lleve o no un control
        assert errores(accion(web, empresa, apertura, 'descartar', version=1, motivo='x\x00' * 200)) == {
            'motivo': [servicio.TEXTOS['motivo_largo']]}
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura['id']).estado) == 'borrador'

    def test_devolver_y_confirmar(self, web, empresa, cuentas):
        apertura = enviada(web, empresa, balance(cuentas))
        antes = historia(empresa)
        assert errores(accion(web, empresa, apertura, 'devolver', version=apertura['version'], motivo='Falta\x00')) == {
            'motivo': [T]}
        assert errores(confirmar(web, empresa, apertura, nota='Revisada\x00')) == {'nota': [T]}
        guardada = en(empresa, lambda: Apertura.objects.get(pk=apertura['id']))
        assert (guardada.estado, guardada.version, guardada.nota_revision) == ('en_revision', apertura['version'], '')
        assert historia(empresa) == antes


class TestArchivos:

    def test_descripcion_del_respaldo(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf', descripcion=NUL)) == {
            'descripcion': [T]}
        assert en(empresa, RespaldoApertura.objects.count) == 0

    def test_la_misma_clave_con_la_descripcion_con_control(self, web, empresa):
        """La descripción con el control no es la del respaldo ya guardado con esa clave: otro envío, 409 `clave_usada`."""
        apertura = creada(web, empresa)
        subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf', clave='respaldo-textos-1', descripcion='Balance firmado')
        respuesta = subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf', clave='respaldo-textos-1',
                                   descripcion='Balance\x00firmado')
        assert respuesta.status_code == 409 and respuesta.json()['codigo'] == 'clave_usada'

    def test_motivo_de_anular_un_respaldo(self, web, empresa):
        apertura = creada(web, empresa)
        respaldo = subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf').json()['respaldo']
        assert errores(enviar(web, f'{API}respaldos/{respaldo["id"]}/anular/', empresa, {'motivo': 'Otro\x00'})) == {
            'motivo': [T]}
        assert en(empresa, lambda: RespaldoApertura.objects.get(pk=respaldo['id']).anulado_en) is None

    def test_motivo_de_omitir_una_fila_del_lote(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        lote = subido(web, empresa, apertura['id'], csv_de(*SALDOS, ('1', 'ACTIVO', '10000.00', '')))
        assert errores(mapear_lote(web, empresa, apertura, lote, decisiones=[
            {'fila': 4, 'omitir': True, 'motivo': 'Subtotal\x00'}])) == {'decisiones.0.motivo': [T]}
        guardado = en(empresa, lambda: ImportacionApertura.objects.get(pk=lote['id']))
        assert (guardado.estado, guardado.mapeo['decisiones']) == ('vista_previa', [])
        assert en(empresa, LineaApertura.objects.count) == 0
