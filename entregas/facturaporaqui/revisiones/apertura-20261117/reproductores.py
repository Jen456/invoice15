"""Reproductores aislados de revisión. Datos ficticios; sin llamadas al SRI ni cambios productivos."""
import pytest

from tests.test_apertura_preparar import (
    API, balance, creada, cuentas, enviar, linea, mapear, web,
)
from tests.test_apertura import confirmada, enviada, preparada
from tests.test_apertura_importar import csv_de, subir

pytestmark = pytest.mark.django_db


def test_importe_excesivo_capturado_responde_validacion(web, empresa, cuentas):
    apertura = creada(web, empresa)
    web.raise_request_exception = False
    filas = [linea(cuentas['caja'], '999999999999999999999999999999.99'),
             linea(cuentas['capital'], None, '10000.00')]
    respuesta = mapear(web, empresa, apertura, filas)
    assert respuesta.status_code == 400, f'Esperado 400 de campo; recibido {respuesta.status_code}'
    assert 'lineas.0.debe' in respuesta.json()['errores']


def test_importe_excesivo_csv_se_identifica_en_fila(web, empresa, cuentas):
    apertura = creada(web, empresa)
    web.raise_request_exception = False
    contenido = csv_de(('Código', 'Nombre', 'Debe', 'Haber'),
                       ('1.1.01', 'Caja ficticia', '999999999999999999999999999999.99', ''),
                       ('3.1.01', 'Capital ficticio', '', '10000.00'))
    respuesta = subir(web, empresa, apertura['id'], contenido)
    assert respuesta.status_code == 200, f'Esperada vista previa con fila inválida; recibido {respuesta.status_code}'


def test_apertura_no_convierte_anio_anterior_en_diario_completo(web, empresa, cuentas):
    apertura = enviada(web, empresa, balance(cuentas))
    confirmada(web, empresa, apertura, nota='Saldo de muestra al 31/12/2025; no incluye diario histórico.')
    respuesta = web.get('/contabilidad/api/diario/',
                        {'empresa': empresa.pk, 'desde': '2024-01-01', 'hasta': '2024-12-31'})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos['asientos'] == []
    assert datos['provisional'] is True and datos['causas_detalle'], datos


def test_resultado_neto_cero_con_ingresos_y_gastos_es_valido(web, empresa, cuentas):
    filas = [linea(cuentas['caja'], '6000.00'), linea(cuentas['capital'], None, '6000.00'),
             linea(cuentas['ventas'], None, '1000.00'), linea(cuentas['gastos_generales'], '1000.00')]
    apertura = preparada(web, empresa, filas, fecha_corte='2026-06-30',
                         cambios={'resultado_ejercicio': 'en_cuentas_nominales', 'resultado_acumulado': '0.00'})
    respuesta = enviar(web, f'{API}{apertura["id"]}/enviar/', empresa, {'version': apertura['version']})
    assert respuesta.status_code == 200, respuesta.json()
