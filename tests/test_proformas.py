"""Proformas (Etapa 1): numeración propia, totales por tarifa, datos del cliente, estados, duplicar, PDF, correo,
roles, plan, lista/JSON, texto seguro, menú, auditoría, bloqueos y seguridad por filas. Datos ficticios; SRI simulado y
correo en memoria. La conversión en factura se prueba en test_proformas_conversion.py."""
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
import pytest
import zxingcpp
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.files.base import ContentFile
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.pos.models import Client, CtasCollect, Product, Receipt, Sale, VoucherErrors
from core.proformas import servicios
from core.proformas.models import ContadorProforma, Proforma, ProformaDetalle
from core.security import menu
from core.security.models import GroupModule, Module, ModuleType
from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.tenancy import roles
from core.tenancy.context import company_context, platform_scope, set_db_scope
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER,
                                 AuditLog)
from tests import helpers
from tests.ayudas_proformas import (ayer, crear_proforma, datos_ejemplo, leer, lineas_ejemplo, productos_por_tarifa,
                                    web_con_rol)
from tests.test_emision_sri import p12, sri  # noqa: F401 (fixtures)
from tests.test_firma_sri import CLAVE

pytestmark = pytest.mark.django_db
LISTA = '/proformas/'
ES_PG = connection.vendor == 'postgresql'
CODIGOS_PASO_1 = ('proforma_enviada', 'proforma_marcada_enviada', 'proforma_aceptada', 'proforma_rechazada',
                  'proforma_anulada', 'proforma_eliminada')
CODIGOS = CODIGOS_PASO_1 + ('proforma_facturada', 'proforma_venta_eliminada')   # los 8 del §9


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.proformas', empresa, ROLE_OWNER)


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


@pytest.fixture
def productos(empresa):
    return productos_por_tarifa(empresa)


@pytest.fixture
def proforma(empresa, dueno, productos):
    return crear_proforma(empresa, dueno, datos_ejemplo(productos))


@pytest.fixture
def facturable(empresa, p12):  # noqa: F811
    """Empresa con la facturación configurada (secuencia 01 y firma): «Facturar» queda disponible."""
    helpers.configurar_facturacion(empresa, punto='002', ultimo_factura=270, ambiente=empresa.environment_type)
    empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
    empresa.electronic_signature_key = CLAVE
    empresa.save()
    return empresa


def accion(web, action, p, **extra):
    return web.post(LISTA, {'action': action, 'id': p.pk, **extra})


def refrescar(empresa, p):
    return leer(empresa, lambda: Proforma.objects.get(pk=p.pk))


def guardar(web, datos, url=f'{LISTA}add/', action='add'):
    return web.post(url, {**datos, 'action': action})


def fila_json(web, p):
    return accion(web, 'search_detalle', p).json()['proforma']


# ---------------------------------------------------------------- numeración

class TestNumeracion:

    def test_numeracion_propia_por_empresa_sin_receipt(self, empresa, empresa_b, dueno):
        with platform_scope():
            antes = sorted(Receipt.all_companies.values_list('id', 'sequence'))
        a1, a2 = crear_proforma(empresa, dueno), crear_proforma(empresa, dueno)
        b1 = crear_proforma(empresa_b, helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER))
        assert [a1.numero_completo, a2.numero_completo, b1.numero_completo] == ['PRO-000001', 'PRO-000002', 'PRO-000001']
        with platform_scope():
            assert sorted(Receipt.all_companies.values_list('id', 'sequence')) == antes
        assert Proforma not in Receipt.modelos_con_numero()
        assert leer(empresa, lambda: ContadorProforma.objects.get().ultimo) == 2
        assert leer(empresa_b, lambda: ContadorProforma.objects.get().ultimo) == 1

    def test_numero_no_se_reutiliza_tras_eliminar_borrador(self, empresa, dueno):
        crear_proforma(empresa, dueno)
        segunda = crear_proforma(empresa, dueno)
        with company_context(empresa):
            servicios.eliminar(segunda.pk, dueno)
        assert crear_proforma(empresa, dueno).numero_completo == 'PRO-000003'

    def test_contador_respeta_el_mayor_numero_existente(self, empresa, dueno):
        p = crear_proforma(empresa, dueno)
        with company_context(empresa):
            Proforma.objects.filter(pk=p.pk).update(numero=41, numero_completo='PRO-000041')
            ContadorProforma.objects.update(ultimo=3)
        assert crear_proforma(empresa, dueno).numero_completo == 'PRO-000042'
        assert servicios.formatear_numero(1000000) == 'PRO-1000000'


# ---------------------------------------------------------------- totales

class TestTotales:

    def test_totales_por_tarifa_ejemplo_calculado_a_mano(self, empresa, proforma):
        p = proforma
        assert (p.subtotal_gravado, p.subtotal_cero, p.total_iva, p.total_descuento, p.total) == (
            Decimal('51.70'), Decimal('18.25'), Decimal('5.29'), Decimal('3.25'), Decimal('75.24'))
        lineas = leer(empresa, lambda: list(p.detalles.values_list('codigo', 'subtotal', 'total_dscto', 'total', 'total_iva',
                                                                  'dscto', 'codigo_porcentaje')))
        assert lineas == [
            ('P15', Decimal('30.00'), Decimal('3.00'), Decimal('27.00'), Decimal('4.05'), Decimal('0.10'), '4'),
            ('P5', Decimal('24.70'), Decimal('0.00'), Decimal('24.70'), Decimal('1.24'), Decimal('0.00'), '5'),
            ('P0', Decimal('8.00'), Decimal('0.00'), Decimal('8.00'), Decimal('0.00'), Decimal('0.00'), '0'),
            ('PNO', Decimal('5.50'), Decimal('0.00'), Decimal('5.50'), Decimal('0.00'), Decimal('0.00'), '6'),
            ('PEX', Decimal('5.00'), Decimal('0.25'), Decimal('4.75'), Decimal('0.00'), Decimal('0.05'), '7')]

    def test_impuestos_por_tarifa_en_orden_del_ride(self, empresa, proforma):
        impuestos = leer(empresa, lambda: servicios.impuestos_json(list(proforma.detalles.all())))
        assert [(t['codigo'], t['base'], t['valor']) for t in impuestos] == [
            ('4', '27.00', '4.05'), ('5', '24.70', '1.24'), ('0', '8.00', '0.00'), ('6', '5.50', '0.00'), ('7', '4.75', '0.00')]
        assert impuestos[0]['tarifa'] == '15.00' and impuestos[0]['nombre'] == '15 %'

    @pytest.mark.parametrize('cambio, campo, texto', [
        ({'cant': 0}, 'cant', servicios.LINEAS['cant']),
        ({'cant': 1.5}, 'cant', servicios.LINEAS['cant']),
        ({'price': '-1.00'}, 'price', servicios.LINEAS['price']),
        ({'price': '10.005'}, 'price', servicios.LINEAS['price']),
        ({'dscto': '12.5'}, 'dscto', servicios.LINEAS['dscto']),
        ({'dscto': 101}, 'dscto', servicios.LINEAS['dscto']),
        ({'descripcion': 'x' * 301}, 'descripcion', servicios.LINEAS['descripcion']),
        ('repetido', 'product', 'El producto PRODUCTO P15 está repetido: suma las cantidades en una sola línea.'),
        ('201', 'lineas', servicios.CAMPOS['lineas_max']),
        ('vacia', 'lineas', servicios.CAMPOS['lineas']),
        ('maximo', None, servicios.MENSAJES['total_maximo']),
    ])
    def test_descuento_entero_y_limites_de_linea(self, web, empresa, productos, cambio, campo, texto):
        lineas = lineas_ejemplo(productos)
        if cambio == 'repetido':
            lineas.append(dict(lineas[0]))
        elif cambio == '201':
            lineas = [dict(lineas[0]) for _ in range(201)]
        elif cambio == 'vacia':
            lineas = []
        elif cambio == 'maximo':
            lineas = [dict(lineas[0], price='999999.99', cant=11, dscto=0)]
        else:
            lineas[0].update(cambio)
        r = guardar(web, datos_ejemplo(productos, lineas=lineas))
        assert r.status_code == 400
        datos = r.json()
        if campo is None:
            assert datos['error'] == texto and 'campos' not in datos
        elif campo == 'lineas' and isinstance(datos['campos']['lineas'], str):
            assert datos['campos']['lineas'] == texto
        else:
            indice = 5 if cambio == 'repetido' else 0
            assert {'indice': indice, 'campo': campo, 'texto': texto} in datos['campos']['lineas']
        assert datos.get('campos') is None or datos['error'] == servicios.MENSAJES['revisa']
        assert leer(empresa, lambda: Proforma.objects.count()) == 0

    def test_descuento_entero_se_guarda_como_fraccion(self, empresa, dueno, productos):
        lineas = lineas_ejemplo(productos)[:1]
        lineas[0].update(dscto='25', price='10', cant='2')
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, lineas=lineas))
        linea = leer(empresa, lambda: p.detalles.get())
        assert (linea.dscto, linea.price, linea.cant, linea.total_dscto, linea.total) == (
            Decimal('0.25'), Decimal('10.00'), 2, Decimal('5.00'), Decimal('15.00'))


# ---------------------------------------------------------------- datos del cliente y productos

class TestDatos:

    def test_cliente_registrado_toma_copia_de_sus_datos(self, web, empresa, productos):
        cliente = helpers.crear_cliente('cliente.proforma', empresa, '0990000002001', '0990000003')
        with company_context(empresa):
            Client.objects.filter(pk=cliente.pk).update(extra_emails='pagos@example.test', address='Calle Ficticia 2')
        cliente.user.names, cliente.user.email = 'CLIENTE FICTICIO S.A.', 'compras@example.test'
        cliente.user.save()
        r = guardar(web, datos_ejemplo(productos, cliente=cliente, cliente_nombre='OTRO NOMBRE', cliente_correo='x@example.test'))
        assert r.status_code == 200, r.content
        c = r.json()['proforma']['cliente']
        assert c == {'id': cliente.pk, 'nombre': 'CLIENTE FICTICIO S.A.', 'identificacion': '0990000002001',
                     'correo': 'compras@example.test, pagos@example.test', 'telefono': '0990000003',
                     'direccion': 'Calle Ficticia 2', 'es_prospecto': False}

    def test_prospecto_exige_nombre_y_correos_validos(self, web, empresa, productos):
        r = guardar(web, datos_ejemplo(productos, cliente_nombre=' ', cliente_correo='bien@example.test, mal@',
                                       cliente_telefono='abc'))
        campos = r.json()['campos']
        assert r.status_code == 400
        assert campos['cliente_nombre'] == servicios.CAMPOS['cliente_nombre']
        assert campos['cliente_correo'] == 'Este correo no es válido: mal@.'
        assert campos['cliente_telefono'] == servicios.CAMPOS['cliente_telefono']
        seis = ', '.join(f'c{i}@example.test' for i in range(6))
        assert guardar(web, datos_ejemplo(productos, cliente_correo=seis)).json()['campos']['cliente_correo'] == \
            servicios.CAMPOS['cliente_correos']
        r = guardar(web, datos_ejemplo(productos, cliente_nombre='  Prospecto   con  espacios ', cliente_identificacion=' abc-1 '))
        c = r.json()['proforma']['cliente']
        assert c['nombre'] == 'Prospecto con espacios' and c['identificacion'] == 'ABC-1' and c['es_prospecto'] is True

    def test_cliente_o_producto_de_otra_empresa_rechazado(self, web, empresa, empresa_b, productos):
        ajeno = helpers.crear_cliente('cliente.ajeno', empresa_b, '0990000004001', '0990000005')
        producto_ajeno = helpers.crear_producto(empresa_b, 'AJENO')
        r = guardar(web, datos_ejemplo(productos, cliente=ajeno))
        assert r.status_code == 400 and r.json()['campos']['cliente'] == 'El cliente no existe.'
        lineas = lineas_ejemplo(productos)
        lineas[1]['product'] = producto_ajeno.pk
        r = guardar(web, datos_ejemplo(productos, lineas=lineas))
        assert {'indice': 1, 'campo': 'product', 'texto': 'El producto no existe.'} in r.json()['campos']['lineas']
        assert leer(empresa, lambda: Proforma.objects.count()) == 0

    def test_cliente_eliminado_conserva_la_copia(self, empresa, dueno, productos):
        cliente = helpers.crear_cliente('cliente.borrado', empresa, '0990000006001', '0990000007')
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=cliente))
        with company_context(empresa):
            Client.objects.get(pk=cliente.pk).delete()
            p.refresh_from_db()
        assert p.cliente_id is None and p.es_prospecto and p.cliente_nombre == 'cliente.borrado'
        assert p.cliente_identificacion == '0990000006001'

    def test_producto_eliminado_conserva_codigo_y_descripcion_y_el_pdf_sale(self, web, empresa, proforma, productos):
        with company_context(empresa):
            Product.objects.get(pk=productos['5'].pk).delete()
            linea = proforma.detalles.get(codigo='P5')
        assert linea.product_id is None and linea.descripcion == 'PRODUCTO P5'
        r = web.get(f'{LISTA}pdf/{proforma.pk}/')
        assert r.status_code == 200 and r['Content-Type'] == 'application/pdf'
        assert 'P5' in texto_pdf(r.content)
        datos = fila_json(web, proforma)
        assert [l['producto_eliminado'] for l in datos['lineas']] == [False, True, False, False, False]


# ---------------------------------------------------------------- estados

class TestEstados:

    @pytest.mark.parametrize('inicial, action, final', [
        ('borrador', 'marcar_enviada', 'enviada'), ('borrador', 'aceptar', 'aceptada'), ('enviada', 'aceptar', 'aceptada'),
        ('enviada', 'rechazar', 'rechazada'), ('aceptada', 'rechazar', 'rechazada'), ('borrador', 'anular', 'anulada'),
        ('enviada', 'anular', 'anulada'), ('aceptada', 'anular', 'anulada'), ('rechazada', 'anular', 'anulada'),
    ])
    def test_transiciones_permitidas(self, web, empresa, dueno, inicial, action, final):
        p = crear_proforma(empresa, dueno, estado=inicial)
        r = accion(web, action, p, motivo='  Cliente   eligió otra opción  ')
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos['proforma']['estado']['guardado'] == final
        assert datos['mensaje'] == f'La proforma {p.numero_completo} quedó {final}.'
        p = refrescar(empresa, p)
        campo = servicios.TRANSICIONES[action][3]
        assert getattr(p, campo) is not None
        assert p.motivo == ('Cliente eligió otra opción' if action in ('rechazar', 'anular') else '')

    @pytest.mark.parametrize('inicial, action', [
        ('enviada', 'marcar_enviada'), ('aceptada', 'marcar_enviada'), ('aceptada', 'aceptar'), ('rechazada', 'aceptar'),
        ('borrador', 'rechazar'), ('rechazada', 'rechazar'), ('anulada', 'anular'), ('anulada', 'aceptar'),
        ('rechazada', 'marcar_enviada'),
    ])
    def test_transiciones_prohibidas(self, web, empresa, dueno, inicial, action):
        p = crear_proforma(empresa, dueno, estado=inicial)
        r = accion(web, action, p)
        assert r.status_code == 409
        assert r.json()['error'] == f'La proforma {p.numero_completo} está {inicial}: no se puede {servicios.VERBOS[action]}.'
        assert refrescar(empresa, p).estado == inicial

    def test_vencida_es_calculada_y_bloquea_enviar_aceptar_facturar(self, web, empresa, dueno, facturable):
        vigente = crear_proforma(empresa, dueno, estado='enviada')
        assert 'facturar' in fila_json(web, vigente)['acciones']
        p = crear_proforma(empresa, dueno, estado='enviada', valida_hasta=ayer())
        assert p.estado == 'enviada' and p.esta_vencida() and p.estado_visible() == 'vencida'
        datos = fila_json(web, p)
        assert datos['estado'] == {'id': 'vencida', 'nombre': 'Vencida', 'guardado': 'enviada'}
        assert datos['dias_para_vencer'] == -1
        assert datos['acciones'] == ['ver', 'pdf', 'editar', 'duplicar', 'rechazar', 'anular']
        texto = f'La proforma {p.numero_completo} venció el {ayer():%d/%m/%Y}. Cambia la fecha de validez antes de '
        assert accion(web, 'aceptar', p).json()['error'] == texto + 'aceptar.'
        assert accion(web, 'enviar_correo', p, destinatarios='a@example.test').json()['error'] == texto + 'enviar por correo.'
        borrador = crear_proforma(empresa, dueno, valida_hasta=ayer(3))
        r = accion(web, 'marcar_enviada', borrador)
        assert r.status_code == 409 and 'venció el' in r.json()['error']
        assert accion(web, 'rechazar', p).status_code == 200   # rechazar no exige vigencia

    def test_editar_enviada_vuelve_a_borrador(self, web, empresa, dueno, productos):
        p = crear_proforma(empresa, dueno, estado='enviada')
        lineas = list(reversed(lineas_ejemplo(productos)))[:3]
        lineas[0]['descripcion'] = 'Descripción negociada'
        r = guardar(web, datos_ejemplo(productos, lineas=lineas, valida_hasta=(timezone.localdate() + timedelta(days=30)).isoformat()),
                    url=f'{LISTA}update/{p.pk}/', action='edit')
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos['mensaje'] == f'Proforma {p.numero_completo} guardada. Volvió a borrador: envíala de nuevo a tu cliente.'
        assert datos['proforma']['estado']['guardado'] == 'borrador'
        assert [l['codigo'] for l in datos['proforma']['lineas']] == ['PEX', 'PNO', 'P0']   # orden recibido
        assert datos['proforma']['lineas'][0]['descripcion'] == 'Descripción negociada'
        assert datos['proforma']['numero'] == p.numero_completo and datos['proforma']['vendedor']['id'] == dueno.pk
        r = guardar(web, datos_ejemplo(productos), url=f'{LISTA}update/{p.pk}/', action='edit')
        assert r.json()['mensaje'] == f'Proforma {p.numero_completo} guardada.'
        assert leer(empresa, lambda: ProformaDetalle.objects.filter(proforma=p).count()) == 5
        html = web.get(f'{LISTA}update/{crear_proforma(empresa, dueno, estado="enviada").pk}/').content.decode()
        assert servicios.AVISO_EDITAR_ENVIADA in html

    def test_editar_estado_final_no_permitido(self, web, empresa, dueno, productos):
        p = crear_proforma(empresa, dueno, estado='aceptada')
        r = web.get(f'{LISTA}update/{p.pk}/')
        assert r.status_code == 302 and r.url == f'{LISTA}ver/{p.pk}/'
        r = guardar(web, datos_ejemplo(productos), url=f'{LISTA}update/{p.pk}/', action='edit')
        assert r.status_code == 409
        assert r.json()['error'] == (f'La proforma {p.numero_completo} está aceptada y ya no se puede editar. '
                                     'Puedes duplicarla.')

    def test_eliminar_solo_borrador_nunca_enviado(self, web, empresa, dueno, productos):
        p = crear_proforma(empresa, dueno)
        assert web.get(f'{LISTA}delete/{p.pk}/').status_code == 200
        r = web.post(f'{LISTA}delete/{p.pk}/')
        assert r.status_code == 200 and r.json() == {}
        assert not leer(empresa, lambda: Proforma.objects.filter(pk=p.pk).exists())
        assert not leer(empresa, lambda: ProformaDetalle.objects.filter(proforma_id=p.pk).exists())
        registro = AuditLog.objects.get(action='proforma_eliminada')
        assert registro.detail == {'proforma': p.numero_completo, 'proforma_id': p.pk} and registro.company_id == empresa.pk
        enviada = crear_proforma(empresa, dueno, estado='enviada')
        r = web.post(f'{LISTA}delete/{enviada.pk}/')
        assert r.status_code == 409 and r.json()['error'] == servicios.MENSAJES['eliminar_no']
        assert web.get(f'{LISTA}delete/{enviada.pk}/').status_code == 302
        devuelta = crear_proforma(empresa, dueno)
        accion(web, 'marcar_enviada', devuelta)
        guardar(web, datos_ejemplo(productos), url=f'{LISTA}update/{devuelta.pk}/', action='edit')   # vuelve a borrador
        assert refrescar(empresa, devuelta).estado == 'borrador'
        assert 'eliminar' not in fila_json(web, devuelta)['acciones']
        assert web.post(f'{LISTA}delete/{devuelta.pk}/').status_code == 409

    def test_check_facturada_exige_venta(self, empresa, proforma):
        with company_context(empresa):
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    Proforma.objects.filter(pk=proforma.pk).update(estado='facturada')
            assert Proforma.objects.get(pk=proforma.pk).estado == 'borrador'


# ---------------------------------------------------------------- duplicar

class TestDuplicar:

    def test_duplicar_crea_borrador_con_numero_nuevo_fecha_de_hoy_y_origen(self, client, empresa, dueno, productos):
        original = crear_proforma(empresa, dueno, estado='anulada', valida_hasta=ayer(20))
        vendedor = web_con_rol(client, empresa, ROLE_SELLER)
        r = accion(client, 'duplicar', original)
        assert r.status_code == 200, r.content
        datos = r.json()
        copia = datos['proforma']
        assert datos['mensaje'] == f'Se creó la proforma PRO-000002, copia de {original.numero_completo}.'
        assert datos['url_editar'] == f'{LISTA}update/{copia["id"]}/' and datos['avisos'] == []
        hoy = timezone.localdate()
        assert copia['numero'] == 'PRO-000002' and copia['estado']['guardado'] == 'borrador'
        assert copia['fecha'] == hoy.isoformat() and copia['valida_hasta'] == (hoy + timedelta(days=15)).isoformat()
        assert copia['origen'] == {'id': original.pk, 'numero': original.numero_completo}
        assert copia['vendedor']['id'] == vendedor.pk and copia['creada_por'] == vendedor.names
        assert copia['total'] == '75.24' and len(copia['lineas']) == 5 and copia['cliente']['nombre'] == original.cliente_nombre
        original_despues = refrescar(empresa, original)
        assert original_despues.estado == 'anulada' and original_despues.anulada_en == original.anulada_en

    def test_duplicar_omite_productos_eliminados_con_aviso(self, web, empresa, proforma, productos):
        with company_context(empresa):
            Product.objects.get(pk=productos['0'].pk).delete()
            Product.objects.filter(pk=productos['4'].pk).update(tarifa_iva='5')   # la copia usa la tarifa actual
        datos = accion(web, 'duplicar', proforma).json()
        assert datos['avisos'] == ['La línea «PRODUCTO P0» no se cargó: el producto ya no existe.']
        lineas = datos['proforma']['lineas']
        assert [l['codigo'] for l in lineas] == ['P15', 'P5', 'PNO', 'PEX'] and lineas[0]['codigo_porcentaje'] == '5'
        with company_context(empresa):
            Product.objects.all().delete()
        r = accion(web, 'duplicar', proforma)
        assert r.status_code == 409
        assert r.json()['error'] == servicios.MENSAJES['sin_lineas_facturables'].format(numero=proforma.numero_completo)


# ---------------------------------------------------------------- sin efectos fuera de la proforma

def huella(empresa):
    with company_context(empresa):
        return {'stock': sorted(Product.objects.values_list('code', 'stock')),
                'receipts': sorted(Receipt.objects.values_list('id', 'sequence')),
                'ventas': Sale.objects.count(), 'cxc': CtasCollect.objects.count(), 'errores': VoucherErrors.objects.count(),
                'reservas': QuotaReservation.objects.filter(company=empresa).count(),
                'cupo': list(SubscriptionPeriod.objects.filter(company=empresa).values_list('documents_used', 'documents_reserved'))}


def test_ninguna_accion_toca_stock_cupo_receipt_ctascollect_ni_sri(web, empresa, dueno, productos, facturable, sri):  # noqa: F811
    antes = huella(empresa)
    p = guardar(web, datos_ejemplo(productos)).json()['proforma']
    obj = Proforma(pk=p['id'])
    assert guardar(web, datos_ejemplo(productos), url=f'{LISTA}update/{p["id"]}/', action='edit').status_code == 200
    copia = accion(web, 'duplicar', obj).json()['proforma']
    assert web.get(f'{LISTA}pdf/{p["id"]}/').status_code == 200
    assert accion(web, 'enviar_correo', obj, destinatarios='compras@example.test').status_code == 200
    assert accion(web, 'aceptar', obj).status_code == 200
    assert accion(web, 'rechazar', obj).status_code == 200
    assert accion(web, 'anular', obj).status_code == 200
    otra = Proforma(pk=copia['id'])
    assert accion(web, 'marcar_enviada', otra).status_code == 200
    tercera = guardar(web, datos_ejemplo(productos)).json()['proforma']
    assert web.post(f'{LISTA}delete/{tercera["id"]}/').status_code == 200
    assert huella(empresa) == antes
    assert sri.urls == [] and sri.recepciones == [] and sri.consultas == []
    assert len(mail.outbox) == 1


# ---------------------------------------------------------------- PDF

def texto_pdf(contenido):
    with pdfium.PdfDocument(contenido) as documento:
        return ' '.join(' '.join(p.get_textpage().get_text_range().split()) for p in documento)


class TestPdf:

    def test_pdf_a4_sin_validez_tributaria(self, web, empresa, proforma):
        r = web.get(f'{LISTA}pdf/{proforma.pk}/')
        assert r.status_code == 200 and r['Content-Type'] == 'application/pdf'
        assert r['Content-Disposition'] == f'inline; filename="{proforma.numero_completo}.pdf"'
        assert r['Cache-Control'] == 'private, no-store'
        with pdfium.PdfDocument(r.content) as documento:
            assert len(documento) == 1
            assert documento[0].get_size() == pytest.approx((595.276, 841.89), abs=.02)
        texto = texto_pdf(r.content)
        for dato in ('PROFORMA', proforma.numero_completo, 'sin validez tributaria', '75,24', 'PROSPECTO FICTICIO S.A.',
                     'Subtotal 15 %', 'Subtotal 5 %', 'Subtotal 0 %', 'Subtotal no objeto de IVA', 'Subtotal exento de IVA',
                     'IVA 15 %', 'IVA 5 %', 'Válida hasta', 'Entrega inmediata.', 'OTROS CON UTILIZACION DEL SISTEMA FINANCIERO'):
            assert dato in texto, dato
        for prohibido in ('Clave de acceso', 'autorización', 'Autorización', 'Ambiente', 'FACTURA', 'Obligado a llevar',
                          'RIMPE', 'Contribuyente'):
            assert prohibido not in texto, prohibido

    def test_pdf_anulada_lleva_la_banda(self, web, empresa, dueno):
        p = crear_proforma(empresa, dueno, estado='anulada')
        texto = texto_pdf(web.get(f'{LISTA}pdf/{p.pk}/').content)
        assert 'ANULADA' in texto and 'Estado: Anulada' in texto

    def test_pdf_sin_codigo_de_barras(self, web, proforma):
        with pdfium.PdfDocument(web.get(f'{LISTA}pdf/{proforma.pk}/').content) as documento:
            for opciones in ({'scale': 300 / 72, 'no_smoothimage': True}, {'scale': 600 / 72}):
                assert zxingcpp.read_barcodes(documento[0].render(**opciones).to_pil()) == []

    def test_pdf_largo_varias_paginas_cabecera_una_vez(self, web, empresa, dueno):
        with company_context(empresa):
            from core.pos.models import Category
            categoria = Category.objects.create(name='LARGA')
            productos = [Product.objects.create(name=f'ARTÍCULO LARGO {i:03d}', code=f'L{i:03d}', category=categoria,
                                                price=Decimal('1'), pvp=Decimal('2.00'), stock=5, tarifa_iva='4')
                         for i in range(60)]
        lineas = [{'product': prod.pk, 'cant': 1, 'price': '2.00', 'dscto': 0} for prod in productos]
        p = crear_proforma(empresa, dueno, datos_ejemplo(None, lineas=lineas))
        with pdfium.PdfDocument(web.get(f'{LISTA}pdf/{p.pk}/').content) as documento:
            textos = [' '.join(pagina.get_textpage().get_text_range().split()) for pagina in documento]
        assert len(textos) >= 2
        assert textos[0].count('PROFORMA') == 1 and all('PROFORMA' not in t for t in textos[1:])
        assert sum(t.count('Descripción') for t in textos) == 1
        assert 'ARTÍCULO LARGO 059' in ' '.join(textos) and 'TOTAL USD' in textos[-1]

    def test_pdf_de_otra_empresa_404(self, web, empresa_b):
        ajena = crear_proforma(empresa_b, helpers.crear_usuario('dueno.b.pdf', empresa_b, ROLE_OWNER))
        assert web.get(f'{LISTA}pdf/{ajena.pk}/').status_code == 404
        assert web.get(f'{LISTA}ver/{ajena.pk}/').status_code == 404
        assert accion(web, 'search_detalle', ajena).json() == {'error': 'La proforma no existe.'}


# ---------------------------------------------------------------- correo

class TestCorreo:

    def test_correo_adjunta_pdf_y_pasa_a_enviada(self, web, empresa, dueno, productos):
        texto = 'Entrega "inmediata" & sin costo, d\'Ávila'
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, condiciones=texto))
        r = accion(web, 'enviar_correo', p, destinatarios='compras@example.test; pagos@example.test', mensaje=texto)
        assert r.status_code == 200, r.content
        assert r.json()['mensaje'] == f'Proforma {p.numero_completo} enviada a compras@example.test, pagos@example.test.'
        correo = mail.outbox[0]
        assert correo.subject == f'Proforma {p.numero_completo} - EMPRESA A'
        assert correo.to == ['compras@example.test', 'pagos@example.test'] and correo.reply_to == ['empresa@example.com']
        assert 'vía FacturaPorAquí' in correo.from_email
        nombre, contenido, tipo = correo.attachments[0]
        assert nombre == 'PRO-000001.pdf' and tipo == 'application/pdf' and contenido.startswith(b'%PDF')
        assert correo.body.count(texto) == 2 and 'sin validez tributaria: no es una factura' in correo.body
        assert not any(e in correo.body for e in ('&amp;', '&quot;', '&#x27;', '&#39;'))
        assert 'USD 75.24' in correo.body
        p = refrescar(empresa, p)
        assert (p.estado, p.envios, p.enviada_a) == ('enviada', 1, 'compras@example.test, pagos@example.test')
        assert p.enviada_en is not None

    def test_reenvio_no_cambia_estado_y_suma_envios(self, web, empresa, dueno):
        p = crear_proforma(empresa, dueno, estado='aceptada')
        assert accion(web, 'enviar_correo', p).status_code == 200   # sin destinatarios: los de la proforma
        assert accion(web, 'enviar_correo', p).status_code == 200
        p = refrescar(empresa, p)
        assert (p.estado, p.envios, p.enviada_a) == ('aceptada', 2, 'compras@example.test')
        assert [c.to for c in mail.outbox] == [['compras@example.test']] * 2
        assert [r.detail['envio'] for r in AuditLog.objects.filter(action='proforma_enviada').order_by('created_at')] == [1, 2]

    def test_correo_sin_destinatario_valido_o_mas_de_cinco(self, web, empresa, dueno, productos):
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente_correo=''))
        assert accion(web, 'enviar_correo', p).json()['error'] == servicios.MENSAJES['sin_correo']
        assert accion(web, 'enviar_correo', p, destinatarios='no-es-correo').json()['error'] == \
            'Este correo no es válido: no-es-correo.'
        seis = ','.join(f'c{i}@example.test' for i in range(6))
        r = accion(web, 'enviar_correo', p, destinatarios=seis)
        assert r.status_code == 400 and r.json()['error'] == servicios.MENSAJES['demasiados_correos']
        r = accion(web, 'enviar_correo', p, destinatarios='a@example.test', mensaje='x' * 1001)
        assert r.status_code == 400 and r.json()['error'] == servicios.MENSAJES['mensaje_largo']
        assert mail.outbox == [] and refrescar(empresa, p).estado == 'borrador'

    def test_correo_de_vencida_rechazado(self, web, empresa, dueno):
        p = crear_proforma(empresa, dueno, valida_hasta=ayer())
        r = accion(web, 'enviar_correo', p)
        assert r.status_code == 409 and 'venció el' in r.json()['error'] and mail.outbox == []
        anulada = crear_proforma(empresa, dueno, estado='anulada')
        r = accion(web, 'enviar_correo', anulada)
        assert r.status_code == 409 and r.json()['error'].endswith('está anulada: no se puede enviar por correo.')

    def test_fallo_smtp_no_cambia_estado(self, web, empresa, dueno, monkeypatch):
        from django.core.mail import EmailMessage

        def fallar(self, *args, **kwargs):
            raise ConnectionRefusedError('servidor de correo ficticio caído')
        monkeypatch.setattr(EmailMessage, 'send', fallar)
        p = crear_proforma(empresa, dueno)
        r = accion(web, 'enviar_correo', p)
        assert r.status_code == 502
        assert r.json()['error'] == (f'No se pudo enviar la proforma {p.numero_completo} (ConnectionRefusedError: servidor de '
                                     'correo ficticio caído). Revisa el correo de la empresa e inténtalo de nuevo.')
        p2 = refrescar(empresa, p)
        assert (p2.estado, p2.envios, p2.enviada_en) == ('borrador', 0, None)
        assert not AuditLog.objects.filter(action='proforma_enviada').exists()

    def test_limite_de_envios_por_hora(self, web, empresa, empresa_b, dueno):
        p = crear_proforma(empresa, dueno)
        for _ in range(59):
            AuditLog.objects.create(company=empresa, action='proforma_enviada', detail={})
        AuditLog.objects.create(company=empresa, action='proforma_enviada', detail={},
                                created_at=timezone.now() - timedelta(hours=2))   # fuera de la ventana
        AuditLog.objects.create(company=empresa_b, action='proforma_enviada', detail={})   # otra empresa
        assert accion(web, 'enviar_correo', p).status_code == 200   # el envío 60
        r = accion(web, 'enviar_correo', p)
        assert r.status_code == 409 and r.json()['error'] == servicios.MENSAJES['limite_envios']
        assert len(mail.outbox) == 1


# ---------------------------------------------------------------- roles y plan

ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_SELLER, ROLE_ACCOUNTANT, ROLE_READONLY, ROLE_CLIENT)


@pytest.mark.parametrize('rol, esperado', [
    # lista, crear (GET), editar (GET), ver, pdf, eliminar (GET), duplicar (POST), aceptar (POST), eliminar (POST)
    (ROLE_OWNER, (200, 200, 200, 200, 200, 200, 200, 200, 200)),
    (ROLE_ADMIN, (200, 200, 200, 200, 200, 200, 200, 200, 200)),
    (ROLE_SELLER, (200, 200, 200, 200, 200, 302, 200, 200, 403)),
    (ROLE_ACCOUNTANT, (200, 302, 302, 200, 200, 302, 403, 403, 403)),
    (ROLE_READONLY, (200, 302, 302, 200, 200, 302, 403, 403, 403)),
    (ROLE_CLIENT, (302, 302, 302, 302, 302, 302, 403, 403, 403)),
])
def test_permisos_por_rol(client, empresa, dueno, rol, esperado):
    p = crear_proforma(empresa, dueno)
    otra = crear_proforma(empresa, dueno)
    web_con_rol(client, empresa, rol)
    obtenido = (client.get(LISTA).status_code, client.get(f'{LISTA}add/').status_code,
                client.get(f'{LISTA}update/{p.pk}/').status_code, client.get(f'{LISTA}ver/{p.pk}/').status_code,
                client.get(f'{LISTA}pdf/{p.pk}/').status_code, client.get(f'{LISTA}delete/{otra.pk}/').status_code,
                accion(client, 'duplicar', p).status_code, accion(client, 'aceptar', p).status_code,
                client.post(f'{LISTA}delete/{otra.pk}/').status_code)
    assert obtenido == esperado
    if rol in (ROLE_ACCOUNTANT, ROLE_READONLY):
        assert accion(client, 'aceptar', p).json()['error'] == servicios.MENSAJES['sin_permiso']
        assert client.post(f'{LISTA}add/', datos_ejemplo(productos_por_tarifa(empresa), action='add')).status_code == 403


def test_menu_proformas_por_rol():
    modulo = Module.objects.get(url='/proformas/')
    assert (modulo.name, modulo.icon, modulo.module_type.name, modulo.module_type.icon, modulo.module_type.orden) == (
        'Proformas', 'fas fa-file-contract', 'Cotizaciones', 'fas fa-file-alt', 15)
    assert set(modulo.permissions.values_list('codename', flat=True)) == {
        'view_proforma', 'add_proforma', 'change_proforma', 'delete_proforma'}

    def de(rol):
        grupo = Group.objects.get(name=rol)
        return (grupo.groupmodule_set.filter(module=modulo).exists(),
                set(grupo.permissions.filter(content_type__app_label='proformas').values_list('codename', flat=True)))
    todos = {'view_proforma', 'add_proforma', 'change_proforma', 'delete_proforma'}
    assert de(ROLE_OWNER) == de(ROLE_ADMIN) == (True, todos)
    assert de(ROLE_SELLER) == (True, {'view_proforma', 'add_proforma', 'change_proforma'})
    assert de(ROLE_ACCOUNTANT) == de(ROLE_READONLY) == (True, {'view_proforma'})
    assert de(ROLE_CLIENT) == (False, set())


class TestPlan:

    def test_plan_gratuito_bloquea_y_muestra_candado(self, client):
        gratuita = helpers.crear_empresa('GRATUITA', plan=None)
        web_con_rol(client, gratuita, ROLE_OWNER)
        r = client.get(LISTA)
        assert r.status_code == 302 and r.url == '/suscripcion/'
        r = client.post(LISTA, {'action': 'search'})
        assert r.status_code == 403 and r.json()['plan'] == 'requerido'
        html = client.get('/pos/product/').content.decode()
        assert re.search(r'Proformas<i class="fas fa-lock fpa-candado"', html)

    def test_plan_vencido_solo_consulta(self, client):
        vencida = helpers.crear_empresa('VENCIDA', plan=None)
        helpers.dar_plan(vencida, 'plan-1000', inicio=timezone.now() - timedelta(days=400))
        usuario = helpers.crear_usuario('dueno.vencida', vencida, ROLE_OWNER)
        p = crear_proforma(vencida, usuario, estado='enviada')
        helpers.iniciar_sesion(client, usuario, empresa=vencida)
        assert client.get(LISTA).status_code == 200
        filas = client.post(LISTA, {'action': 'search'}).json()
        assert filas[0]['acciones'] == ['ver', 'pdf'] and 'venció' in filas[0]['facturar_bloqueado']
        assert accion(client, 'search_detalle', p).status_code == 200
        assert client.get(f'{LISTA}ver/{p.pk}/').status_code == 200 and client.get(f'{LISTA}pdf/{p.pk}/').status_code == 200
        for url in ('add/', f'update/{p.pk}/', f'delete/{p.pk}/'):
            assert client.get(LISTA + url).status_code == 302
        for action in ('duplicar', 'enviar_correo', 'aceptar', 'anular'):
            assert accion(client, action, p).status_code == 403
        assert client.get(LISTA).context['create_url'] is None

    def test_cupo_agotado_permite_proformas_y_oculta_facturar(self, client, p12):  # noqa: F811
        agotada = helpers.crear_empresa('AGOTADA', plan=None, environment_type=2)
        helpers.dar_plan(agotada, 'plan-1000', documents_used=1000)
        helpers.configurar_facturacion(agotada, punto='002', ambiente=2)
        agotada.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
        agotada.electronic_signature_key = CLAVE
        agotada.save()
        web_con_rol(client, agotada, ROLE_OWNER)
        productos = productos_por_tarifa(agotada)
        assert client.get(f'{LISTA}add/').status_code == 200
        r = guardar(client, datos_ejemplo(productos))
        assert r.status_code == 200
        p = r.json()['proforma']
        assert accion(client, 'marcar_enviada', Proforma(pk=p['id'])).status_code == 200
        fila = client.post(LISTA, {'action': 'search'}).json()[0]
        assert 'facturar' not in fila['acciones'] and fila['urls']['facturar'] is None
        assert fila['facturar_bloqueado'].startswith('Usaste los 1000 documentos')


# ---------------------------------------------------------------- lista y JSON

class TestListaYJson:

    def test_busqueda_por_estado_visible_fecha_y_texto(self, web, empresa, dueno, productos):
        vigente = crear_proforma(empresa, dueno)
        vencida = crear_proforma(empresa, dueno, estado='enviada', valida_hasta=ayer(10))
        aceptada = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente_nombre='COMERCIAL ÚNICA',
                                                                 cliente_identificacion='1790000000001'), estado='aceptada')
        anulada = crear_proforma(empresa, dueno, estado='anulada')

        def ids(**filtros):
            return [f['id'] for f in web.post(LISTA, {'action': 'search', **filtros}).json()]
        assert ids() == [anulada.pk, aceptada.pk, vencida.pk, vigente.pk]
        assert ids(estado='vencida') == [vencida.pk]
        assert ids(estado='borrador') == [vigente.pk] and ids(estado='enviada') == []
        assert ids(estado='aceptada') == [aceptada.pk] and ids(estado='anulada') == [anulada.pk]
        assert ids(q='comercial') == [aceptada.pk] and ids(q='17900000') == [aceptada.pk]   # sin distinguir mayúsculas
        assert ids(q=vigente.numero_completo) == [vigente.pk]
        hace_10 = ayer(10)
        assert ids(hasta=(hace_10 - timedelta(days=1)).isoformat()) == []
        assert ids(desde=hace_10.isoformat(), hasta=hace_10.isoformat()) == [vencida.pk]
        assert ids(desde=timezone.localdate().isoformat()) == [anulada.pk, aceptada.pk, vigente.pk]

    def test_json_montos_como_texto_y_acciones_por_estado_y_rol(self, client, web, empresa, dueno):
        p = crear_proforma(empresa, dueno)
        f = web.post(LISTA, {'action': 'search'}).json()[0]
        assert set(f) == {'id', 'numero', 'fecha', 'valida_hasta', 'dias_para_vencer', 'estado', 'cliente', 'vendedor',
                          'subtotal_gravado', 'subtotal_cero', 'total_descuento', 'total_iva', 'total', 'venta', 'envios',
                          'enviada_en', 'acciones', 'facturar_bloqueado', 'urls'}
        assert (f['subtotal_gravado'], f['subtotal_cero'], f['total_descuento'], f['total_iva'], f['total']) == (
            '51.70', '18.25', '3.25', '5.29', '75.24')
        assert f['dias_para_vencer'] == 15 and f['venta'] is None and f['envios'] == 0 and f['enviada_en'] is None
        assert f['vendedor'] == {'id': dueno.pk, 'nombre': dueno.names}
        assert f['acciones'] == ['ver', 'pdf', 'editar', 'duplicar', 'enviar_correo', 'marcar_enviada', 'aceptar', 'anular',
                                 'eliminar']
        assert f['urls'] == {'ver': f'/proformas/ver/{p.pk}/', 'pdf': f'/proformas/pdf/{p.pk}/',
                             'editar': f'/proformas/update/{p.pk}/', 'facturar': None, 'eliminar': f'/proformas/delete/{p.pk}/'}
        d = fila_json(web, p)
        assert d['lineas'][0] == {
            'id': d['lineas'][0]['id'], 'product_id': d['lineas'][0]['product_id'], 'codigo': 'P15', 'descripcion': 'PRODUCTO P15',
            'cant': 3, 'price': '10.00', 'dscto': '10', 'codigo_porcentaje': '4', 'tarifa': '15.00', 'nombre_tarifa': '15 %',
            'subtotal': '30.00', 'total_dscto': '3.00', 'total': '27.00', 'total_iva': '4.05', 'producto_eliminado': False,
            'producto': {'nombre': 'PRODUCTO P15', 'stock': 100, 'inventariado': True, 'pvp': '10.00'}}
        assert d['forma_pago_sugerida'] == {'id': '20', 'nombre': 'OTROS CON UTILIZACION DEL SISTEMA FINANCIERO'}
        assert d['empresa'] == {'razon_social': 'EMPRESA A S.A.', 'nombre_comercial': 'EMPRESA A', 'ruc': empresa.ruc}
        assert set(d['fechas']) == {'creada', 'actualizada', 'enviada', 'aceptada', 'rechazada', 'anulada', 'facturada'}
        for estado, acciones in (('aceptada', ['ver', 'pdf', 'duplicar', 'enviar_correo', 'rechazar', 'anular']),
                                 ('rechazada', ['ver', 'pdf', 'duplicar', 'anular']), ('anulada', ['ver', 'pdf', 'duplicar'])):
            assert fila_json(web, crear_proforma(empresa, dueno, estado=estado))['acciones'] == acciones
        web_con_rol(client, empresa, ROLE_SELLER)
        assert 'eliminar' not in fila_json(client, p)['acciones'] and 'editar' in fila_json(client, p)['acciones']
        web_con_rol(client, empresa, ROLE_ACCOUNTANT)
        assert fila_json(client, p)['acciones'] == ['ver', 'pdf']

    def test_busqueda_sin_consultas_por_fila(self, web, empresa, dueno, productos):
        cliente = helpers.crear_cliente('cliente.lista', empresa, '0990000008001', '0990000009')

        def crear(n):
            for _ in range(n):
                p = crear_proforma(empresa, dueno, datos_ejemplo(productos, lineas=lineas_ejemplo(productos)[:1]))
                if p.numero % 3 == 0:   # algunas facturadas, con su venta
                    venta = helpers.crear_venta(empresa, cliente, dueno, productos['4'])
                    with company_context(empresa):
                        Proforma.objects.filter(pk=p.pk).update(estado='facturada', venta=venta)

        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                filas = web.post(LISTA, {'action': 'search'}).json()
            return len(capturadas), filas
        crear(3)
        con_3, filas = consultas()
        assert len(filas) == 3 and sum(1 for f in filas if f['venta']) == 1
        crear(27)
        con_30, filas = consultas()
        assert len(filas) == 30 and sum(1 for f in filas if f['venta']) == 10
        assert con_30 == con_3

    def test_facturar_en_pruebas_en_el_json(self, client, web, empresa, dueno, facturable, productos):
        """Decisión de la propietaria (28/10/2026): en PRUEBAS se factura igual que en PRODUCCIÓN y la pantalla avisa."""
        assert empresa.environment_type == 1
        p = crear_proforma(empresa, dueno, estado='enviada')
        f = fila_json(web, p)
        assert 'facturar' in f['acciones'] and f['facturar_bloqueado'] is None
        assert f['urls']['facturar'] == f'/pos/sale/admin/add/?proforma={p.pk}'
        cliente = helpers.crear_cliente('cliente.pruebas', empresa, '0990000010001', '0990000011')
        venta = helpers.crear_venta(empresa, cliente, dueno, productos['4'])
        facturada = crear_proforma(empresa, dueno)
        with company_context(empresa):
            Proforma.objects.filter(pk=facturada.pk).update(estado='facturada', venta=venta)
        v = fila_json(web, facturada)['venta']
        assert v['ambiente'] == {'id': 1, 'nombre': 'PRUEBAS'} and v['sin_validez_tributaria'] is True
        assert v['aviso_ambiente'] == servicios.AVISO_FACTURA_PRUEBAS and v['numero'] == venta.voucher_number_full
        assert v['aviso'].startswith(f'La factura {venta.voucher_number_full} está «Sin Autorizar»')
        html = web.get(f'{LISTA}ver/{facturada.pk}/').content.decode()
        assert 'PRUEBAS · sin validez tributaria' in html and servicios.AVISO_FACTURA_PRUEBAS in html
        assert '(PRUEBAS, sin validez tributaria)' in texto_pdf(web.get(f'{LISTA}pdf/{facturada.pk}/').content)
        web_con_rol(client, empresa, ROLE_ACCOUNTANT)   # sin add_sale: ni botón ni motivo
        f = fila_json(client, p)
        assert 'facturar' not in f['acciones'] and f['facturar_bloqueado'] is None

    def test_facturar_bloqueado_por_configuracion(self, web, empresa, dueno):
        p = crear_proforma(empresa, dueno, estado='aceptada')
        f = fila_json(web, p)
        assert 'facturar' not in f['acciones'] and f['facturar_bloqueado'].startswith('Para emitir facturas completa la configuración')

    def test_texto_hostil_se_escapa(self, web, empresa, dueno, productos):
        hostil = '<img src=x onerror=alert(1)>'
        lineas = lineas_ejemplo(productos)
        lineas[0]['descripcion'] = hostil
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente_nombre=hostil, condiciones=hostil, lineas=lineas))
        fila = web.post(LISTA, {'action': 'search'}).json()[0]
        assert fila['cliente']['nombre'] == hostil
        for url in (f'{LISTA}ver/{p.pk}/', f'{LISTA}update/{p.pk}/'):
            html = web.get(url).content.decode()
            assert '<img src=x' not in html and '\\u003Cimg src=x onerror=alert(1)\\u003E' in html   # json_script
        assert '&lt;img src=x onerror=alert(1)&gt;' in web.get(f'{LISTA}ver/{p.pk}/').content.decode()
        assert 'onerror=alert(1)' in texto_pdf(web.get(f'{LISTA}pdf/{p.pk}/').content)

    def test_list_js_usa_render_text(self):
        js = (Path(settings.BASE_DIR) / 'core/proformas/static/proformas/js/list.js').read_text()
        for campo in ('numero', 'cliente.nombre', 'cliente.identificacion', 'vendedor.nombre', 'estado.nombre', 'venta.numero'):
            assert re.search(r"data: '" + re.escape(campo) + r"'[^}\n]*render: \$\.fn\.dataTable\.render\.text\(\)", js), campo
        for nombre in ('list.html', 'detalle.html', 'form.html'):
            plantilla = (Path(settings.BASE_DIR) / 'templates/proformas' / nombre).read_text()
            assert '|safe' not in plantilla


# ---------------------------------------------------------------- menú

def test_organizar_menu_idempotente_y_omite_apps_sin_permisos():
    def estado():
        return (sorted(Module.objects.values_list('url', 'name', 'orden', 'module_type__name')),
                sorted(ModuleType.objects.values_list('name', 'orden')),
                sorted(GroupModule.objects.values_list('group__name', 'module__url')))
    menu.organizar_menu(ModuleType, Module, Permission)
    roles.sync_roles(Group, Module, GroupModule)
    antes = estado()
    menu.organizar_menu(ModuleType, Module, Permission)
    roles.sync_roles(Group, Module, GroupModule)
    assert estado() == antes and Module.objects.filter(url='/proformas/').count() == 1
    Module.objects.filter(url='/proformas/').delete()
    Permission.objects.filter(content_type__app_label='proformas').delete()   # como una base sin la app migrada
    menu.organizar_menu(ModuleType, Module, Permission)
    assert not Module.objects.filter(url='/proformas/').exists()


# ---------------------------------------------------------------- auditoría

class TestAuditoria:

    def test_auditoria_de_cada_transicion(self, web, empresa, dueno):
        p = crear_proforma(empresa, dueno)
        accion(web, 'marcar_enviada', p)
        accion(web, 'enviar_correo', p, destinatarios='a@example.test, b@example.test')
        accion(web, 'aceptar', p)
        accion(web, 'rechazar', p, motivo='Precio')
        accion(web, 'anular', p, motivo='Duplicada por error')
        borrador = crear_proforma(empresa, dueno)
        web.post(f'{LISTA}delete/{borrador.pk}/')
        registros = {r.action: r for r in AuditLog.objects.filter(action__startswith='proforma_')}
        assert set(registros) == set(CODIGOS_PASO_1)
        base = {'proforma': p.numero_completo, 'proforma_id': p.pk}
        assert registros['proforma_marcada_enviada'].detail == base
        assert registros['proforma_enviada'].detail == {**base, 'destinatarios': 2, 'envio': 1}
        assert registros['proforma_aceptada'].detail == base
        assert registros['proforma_rechazada'].detail == {**base, 'motivo': 'Precio'}
        assert registros['proforma_anulada'].detail == {**base, 'motivo': 'Duplicada por error'}
        assert registros['proforma_eliminada'].detail == {'proforma': borrador.numero_completo, 'proforma_id': borrador.pk}
        assert all(r.company_id == empresa.pk and r.user_id == dueno.pk for r in registros.values())

    def test_detalle_de_auditoria_serializable_sin_encoder(self, empresa, dueno):
        p = crear_proforma(empresa, dueno)
        with company_context(empresa):
            servicios.enviar_por_correo(p.pk, dueno, 'a@example.test')
            for accion_ in ('aceptar', 'rechazar', 'anular'):
                servicios.cambiar_estado(p.pk, accion_, dueno, motivo='x')
            otra = crear_proforma(empresa, dueno)
            servicios.cambiar_estado(otra.pk, 'marcar_enviada', dueno)
            servicios.eliminar(crear_proforma(empresa, dueno).pk, dueno)
            facturada = crear_proforma(empresa, dueno, estado='aceptada')
            cliente = helpers.crear_cliente('cliente.auditoria', empresa, '0990000012001', '0990000012')
            venta = helpers.crear_venta(empresa, cliente, dueno, Product.objects.get(code='P15'))
            servicios.marcar_facturada(facturada, venta, dueno)
            Sale.objects.get(pk=venta.pk).delete()   # la señal libera la proforma
        registros = list(AuditLog.objects.filter(action__startswith='proforma_'))
        assert {r.action for r in registros} == set(CODIGOS)
        for registro in registros:
            json.dumps(registro.detail)   # sin DjangoJSONEncoder
            assert all(isinstance(v, (str, int, bool, list)) for v in registro.detail.values())
            # Sin petición, el servicio registra al usuario; la señal de la venta eliminada no tiene usuario.
            assert registro.user_id == (None if registro.action == 'proforma_venta_eliminada' else dueno.pk)
        detalle = next(r.detail for r in registros if r.action == 'proforma_facturada')
        assert re.fullmatch(r'\d+\.\d{2}', detalle['total_proforma']) and re.fullmatch(r'\d+\.\d{2}', detalle['total_factura'])
        assert isinstance(detalle['coincide'], bool) and isinstance(detalle['ambiente'], int)
        assert next(r.detail for r in registros if r.action == 'proforma_venta_eliminada')['estado'] == 'aceptada'


# ---------------------------------------------------------------- bloqueos y seguridad por filas (PostgreSQL)

@pytest.mark.skipif(not ES_PG, reason='FOR UPDATE OF es de PostgreSQL')
def test_bloqueo_usa_for_update_of_sin_join(empresa, dueno):
    p = crear_proforma(empresa, dueno, estado='aceptada')
    with company_context(empresa), transaction.atomic():
        with CaptureQueriesContext(connection) as capturadas:
            servicios.bloquear(p.pk)
            servicios.bloquear_para_facturar(p.pk, '01')
            servicios.siguiente_numero()
    bloqueos = [q['sql'] for q in capturadas if 'FOR UPDATE' in q['sql']]
    assert len(bloqueos) == 3
    for sql in bloqueos[:2]:
        assert 'FOR UPDATE OF "proformas_proforma"' in sql and 'JOIN' not in sql
    assert 'FOR UPDATE OF "proformas_contadorproforma"' in bloqueos[2] and 'JOIN' not in bloqueos[2]


rls = pytest.mark.skipif(not ES_PG, reason='La seguridad por filas es de PostgreSQL')
TABLAS = ('proformas_contadorproforma', 'proformas_proforma', 'proformas_proformadetalle')


def contar(tabla):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM {tabla}')   # sin filtro de empresa a propósito
        return cursor.fetchone()[0]


@rls
def test_rls_tablas_de_proformas_activas_y_forzadas():
    with connection.cursor() as cursor:
        cursor.execute("SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relname = ANY(%s)",
                       [list(TABLAS)])
        assert {f[0] for f in cursor.fetchall()} == set(TABLAS)
        cursor.execute("SELECT tablename FROM pg_policies WHERE policyname = 'fpa_empresa' AND tablename = ANY(%s)",
                       [list(TABLAS)])
        assert {f[0] for f in cursor.fetchall()} == set(TABLAS)


@rls
def test_rls_sql_directo_aisla_las_tres_tablas(empresa, empresa_b, dueno):
    crear_proforma(empresa, dueno)
    usuario_b = helpers.crear_usuario('dueno.b.rls', empresa_b, ROLE_OWNER)
    crear_proforma(empresa_b, usuario_b)
    crear_proforma(empresa_b, usuario_b)
    with company_context(empresa):
        assert [contar(t) for t in TABLAS] == [1, 1, 5]
    with company_context(empresa_b):
        assert [contar(t) for t in TABLAS] == [1, 2, 10]
    with platform_scope():
        assert [contar(t) for t in TABLAS] == [2, 3, 15]
    set_db_scope(None)
    assert [contar(t) for t in TABLAS] == [0, 0, 0]


def insertar_proforma(company_id, numero):
    hoy = timezone.localdate()
    with connection.cursor() as cursor:
        cursor.execute(
            'INSERT INTO proformas_proforma (company_id, numero, numero_completo, cliente_nombre, cliente_identificacion, '
            'cliente_correo, cliente_telefono, cliente_direccion, fecha, valida_hasta, condiciones, forma_pago_sugerida, '
            'subtotal_gravado, subtotal_cero, total_descuento, total_iva, total, estado, motivo, enviada_a, envios, '
            "creada_en, actualizada_en) VALUES (%s, %s, 'PRO-X', 'SQL', '', '', '', '', %s, %s, '', '', "
            "0, 0, 0, 0, 0, 'borrador', '', '', 0, now(), now()) RETURNING id", [company_id, numero, hoy, hoy])
        return cursor.fetchone()[0]


def insertar_linea(company_id, proforma_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO proformas_proformadetalle (company_id, proforma_id, codigo, descripcion, cant, price, dscto, "
            "codigo_porcentaje, iva, price_with_vat, subtotal, total_dscto, total, total_iva) "
            "VALUES (%s, %s, '', 'SQL', 1, 0, 0, '0', 0, 0, 0, 0, 0, 0)", [company_id, proforma_id])


@rls
def test_rls_no_inserta_proforma_ni_linea_de_otra_empresa(empresa, empresa_b, dueno):
    with company_context(empresa):
        propia = insertar_proforma(empresa.pk, 98)          # control: la misma orden con la empresa activa funciona
        insertar_linea(empresa.pk, propia)
        with pytest.raises(DatabaseError), transaction.atomic():
            insertar_proforma(empresa_b.pk, 99)
        with pytest.raises(DatabaseError), transaction.atomic():
            insertar_linea(empresa_b.pk, propia)
        assert [contar(t) for t in TABLAS[1:]] == [1, 1]
