"""Respaldo del cobro (core/cobros) y separación de condición de pago (contado / crédito) y medio de cobro (efectivo,
transferencia, tarjeta, cheque…): registro con archivo, nota o ambos (al menos uno), autor/empresa/fecha del servidor,
archivo privado por empresa (PDF/JPG/PNG ≤ 5 MB con contenido validado), revisión aparte del saldo, historial, doble envío,
permisos por rol, aislamiento entre empresas, crédito sin abono, emisión al contado por medio y conservación de saldos y
documentos. Empresas ficticias y SRI simulado; sin pagos, emisiones ni correos reales."""
import io
import json
import os
import uuid
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as ClienteWeb
from PIL import Image

from core.cobros import servicios as sv
from core.cobros.models import RespaldoCobro, RespaldoCobroCambio
from core.comprobantes.fidelidad import texto_del_pdf
from core.pos import cxc
from core.pos.models import CtasCollect, PaymentsCtaCollect, Receipt, Sale
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import helpers
from tests.ayudas_ventas import cxc_de, factura_autorizada
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de, web  # noqa: F401

pytestmark = pytest.mark.django_db
PDF = b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n'


def imagen(formato='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (202, 70, 44)).save(buffer, format=formato)
    return buffer.getvalue()


def archivo(nombre='comprobante.pdf', contenido=PDF, tipo='application/pdf'):
    return SimpleUploadedFile(nombre, contenido, content_type=tipo)


def url_factura(venta):
    return f'/cobros/factura/{venta.pk}/'


def registrar(cliente, venta, **campos):
    datos = {'clave': uuid.uuid4().hex, 'medio': 'transferencia', 'importe': '10.00', 'referencia': 'TRX-1'}
    datos.update(campos)
    return cliente.post(url_factura(venta) + 'registrar/', {k: v for k, v in datos.items() if v is not None})


def entrar(usuario, empresa):  # noqa: F811
    cliente = ClienteWeb()
    helpers.iniciar_sesion(cliente, usuario, empresa=empresa)
    return cliente


@pytest.fixture
def credito(empresa, comprador, dueno, producto):  # noqa: F811
    """Factura a crédito de $23,00 con su cuenta por cobrar."""
    return factura_autorizada(empresa, comprador, dueno, producto, credito=True)


@pytest.fixture
def contado(empresa, comprador, dueno, producto):  # noqa: F811
    """Factura al contado anterior a esta mejora: medio de cobro sin dato."""
    return factura_autorizada(empresa, comprador, dueno, producto, credito=False)


@pytest.fixture
def vendedor(empresa):  # noqa: F811
    return helpers.crear_usuario('cajero.ficticio', empresa, ROLE_SELLER)


def saldo(empresa, venta):  # noqa: F811
    return leer(empresa, lambda: cxc_de(venta).saldo_actual())


def respaldos(empresa):  # noqa: F811
    return leer(empresa, lambda: list(RespaldoCobro.objects.order_by('id')))


# ---------------------------------------------------------------- factura a crédito: cobro con respaldo

class TestCobroACredito:

    def test_archivo_crea_abono_y_respaldo_con_autor_y_fecha_del_servidor(self, web, empresa, dueno, credito):  # noqa: F811
        r = registrar(web, credito, archivo=archivo(), nota='Transferencia recibida en Produbanco')
        assert r.status_code == 201, r.content
        datos = r.json()
        assert datos['repetido'] is False and datos['cuenta_por_cobrar']['saldo'] == '13.00'
        abono = leer(empresa, lambda: PaymentsCtaCollect.objects.get())
        assert (abono.tipo, abono.valor, abono.medio_pago, abono.referencia, abono.registrado_por) == ('cobro', Decimal('10.00'), 'transferencia', 'TRX-1', dueno)
        assert abono.description == 'Transferencia recibida en Produbanco'
        [resp] = respaldos(empresa)
        assert (resp.origen, resp.abono_id, resp.importe, resp.medio, resp.estado, resp.registrado_por) == ('abono', abono.pk, Decimal('10.00'), 'transferencia', 'pendiente', dueno)
        assert resp.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/cobros/') and resp.archivo.name.endswith('.pdf')
        assert (resp.archivo_nombre, resp.archivo_tipo, resp.archivo_bytes) == ('comprobante.pdf', 'pdf', len(PDF)) and len(resp.archivo_sha256) == 64
        assert resp.registrado_en is not None and resp.revisado_por is None
        assert leer(empresa, lambda: [c.accion for c in resp.cambios.all()]) == ['registro']
        assert AuditLog.objects.filter(action='cobro_respaldo_registro', company=empresa, user=dueno, detail__abono=abono.pk).exists()
        assert datos['respaldo']['archivo']['url'] == f'/cobros/respaldo/{resp.pk}/archivo/' and datos['respaldo']['estado']['id'] == 'pendiente'
        assert datos['abonos'][0]['respaldo']['id'] == resp.pk and datos['capacidades']['puede_revisar'] is True
        assert set(datos) >= {'factura', 'cuenta_por_cobrar', 'abonos', 'respaldos', 'capacidades', 'medios', 'clave_sugerida', 'respaldo', 'repetido'}

    def test_nota_sola_archivo_solo_y_ninguno(self, web, empresa, credito):  # noqa: F811
        assert registrar(web, credito, nota='Cobrado en caja, sin comprobante').status_code == 201
        assert registrar(web, credito, importe='3.00', archivo=archivo('foto.png', imagen('PNG'), 'image/png')).status_code == 201
        r = registrar(web, credito, importe='1.00')
        assert r.status_code == 400 and r.json() == {'error': sv.MENSAJES['respaldo_requerido'], 'codigo': 'respaldo_requerido'}
        assert saldo(empresa, credito) == Decimal('10.00') and leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 2

    def test_doble_envio_con_la_misma_clave_registra_un_solo_cobro(self, web, empresa, credito):  # noqa: F811
        clave = uuid.uuid4().hex
        primero = registrar(web, credito, clave=clave, nota='Doble clic')
        segundo = registrar(web, credito, clave=clave, nota='Doble clic')
        assert primero.status_code == 201 and segundo.status_code == 200 and segundo.json()['repetido'] is True
        assert segundo.json()['respaldo']['id'] == primero.json()['respaldo']['id']
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 1 and saldo(empresa, credito) == Decimal('13.00')
        assert registrar(web, credito, nota='Otro cobro real').status_code == 201 and saldo(empresa, credito) == Decimal('3.00')
        r = registrar(web, credito, clave='x', nota='clave corta')
        assert r.status_code == 400 and r.json()['codigo'] == 'clave'

    def test_autor_estado_y_empresa_no_se_aceptan_del_navegador(self, web, empresa, dueno, vendedor, credito):  # noqa: F811
        wv = entrar(vendedor, empresa)
        r = registrar(wv, credito, nota='Intento de falsificar', registrado_por=dueno.pk, registrado_en='2020-01-01T00:00:00',
                      estado='revisado', revisado_por=dueno.pk, company=999, sale=999)
        assert r.status_code == 201
        [resp] = respaldos(empresa)
        assert resp.registrado_por == vendedor and resp.estado == 'pendiente' and resp.revisado_por is None
        assert resp.registrado_en.year >= 2026 and resp.company_id == empresa.pk and resp.sale_id == credito.pk

    def test_validaciones_del_cobro(self, web, empresa, credito):  # noqa: F811
        casos = {
            ('importe', ''): 'El valor debe ser mayor que cero.',
            ('importe', '30'): 'supera el saldo de la cuenta por cobrar',
            ('medio', ''): 'Elige el medio de pago.',
            ('medio', 'bitcoin'): 'Elige el medio de pago.',
            ('referencia', '4111 1111 1111 1111'): sv.MENSAJES['referencia_tarjeta'],
            ('referencia', 'x' * 101): sv.MENSAJES['referencia_larga'],
            ('nota', 'n' * 501): sv.MENSAJES['nota_larga'],
        }
        for (campo, valor), mensaje in casos.items():
            r = registrar(web, credito, **{'nota': 'Nota', campo: valor})
            assert r.status_code == 400 and mensaje in r.json()['error'], (campo, valor, r.content)
        r = registrar(web, credito, nota='Cheque sin número', medio='cheque', referencia='')
        assert r.status_code == 400 and 'número del cheque' in r.json()['error']
        assert saldo(empresa, credito) == Decimal('23.00') and not respaldos(empresa)


# ---------------------------------------------------------------- condición y medio al emitir

class TestEmisionContado:

    def test_efectivo_exige_efectivo_suficiente_y_el_servidor_calcula_el_cambio(self, web, empresa, comprador, producto, sri):  # noqa: F811
        r = vender(web, comprador, producto, medio_cobro='efectivo', cash='10', change='0')
        assert 'El efectivo recibido' in r['error'] and leer(empresa, lambda: Sale.objects.count()) == 0
        r = vender(web, comprador, producto, medio_cobro='efectivo', cash='100', change='99')   # el cambio lo calcula el servidor
        assert 'error' not in r, r
        venta = venta_de(empresa, 271)
        assert (venta.payment_type, venta.medio_cobro, venta.cash, venta.change) == ('efectivo', 'efectivo', Decimal('100.00'), Decimal('77.00'))
        assert not respaldos(empresa)   # en efectivo la nota es opcional
        r = vender(web, comprador, producto, medio_cobro='efectivo', cash='23', nota_cobro='Recibió Ana en caja 1')
        assert 'error' not in r and respaldos(empresa)[0].origen == 'contado'

    def test_transferencia_exige_respaldo_y_deja_efectivo_y_cambio_en_cero(self, web, empresa, comprador, producto, sri):  # noqa: F811
        antes = leer(empresa, lambda: Receipt.objects.get(voucher_type='01', environment_type=2).sequence)
        r = vender(web, comprador, producto, medio_cobro='transferencia', cash='0', change='0')
        assert r['error'] == sv.MENSAJES['respaldo_requerido']
        assert leer(empresa, lambda: Sale.objects.count()) == 0   # la venta se deshizo entera
        assert leer(empresa, lambda: Receipt.objects.get(voucher_type='01', environment_type=2).sequence) == antes
        r = vender(web, comprador, producto, medio_cobro='transferencia', referencia_cobro='TRX-9', cash='23', change='5',
                   respaldo=archivo('transferencia.jpg', imagen('JPEG'), 'image/jpeg'))
        assert 'error' not in r, r
        venta = venta_de(empresa, 271)
        assert (venta.payment_type, venta.medio_cobro, venta.cash, venta.change) == ('efectivo', 'transferencia', Decimal('0.00'), Decimal('0.00'))
        [resp] = respaldos(empresa)
        assert (resp.origen, resp.abono_id, resp.importe, resp.medio, resp.referencia, resp.clave) == ('contado', None, venta.total, 'transferencia', 'TRX-9', f'venta-{venta.pk}')
        assert resp.archivo_tipo == 'jpg' and resp.registrado_por_id == venta.employee_id
        assert cxc_de(venta) is None
        json_venta = leer(empresa, lambda: venta.toJSON())
        assert json_venta['medio_cobro'] == {'id': 'transferencia', 'name': 'Transferencia'} and json_venta['condicion_pago']['name'] == 'Contado'
        assert 'TRX-9' not in json.dumps(json_venta['additional_info']) and 'TRX-9' not in (venta.xml_signed or '')

    def test_sin_medio_o_con_medio_invalido(self, web, empresa, comprador, producto, sri):  # noqa: F811
        for medio in ('', 'bitcoin'):
            r = vender(web, comprador, producto, medio_cobro=medio, cash='23', nota_cobro='x')
            assert r['error'] == 'Elige el medio de cobro.', r
        assert leer(empresa, lambda: Sale.objects.count()) == 0

    def test_credito_sin_abono_no_necesita_respaldo_y_no_lo_admite_al_emitir(self, web, empresa, comprador, producto, sri):  # noqa: F811
        r = vender(web, comprador, producto, payment_type='credito', end_credit='2026-12-31', cash='0', change='0')
        assert 'error' not in r, r
        venta = venta_de(empresa, 271)
        assert venta.medio_cobro == '' and cxc_de(venta) is not None and not respaldos(empresa)
        r = vender(web, comprador, producto, payment_type='credito', end_credit='2026-12-31', cash='0', change='0', respaldo=archivo())
        assert r['error'] == sv.MENSAJES['credito_sin_abono']

    def test_ventas_anteriores_no_se_reclasifican(self, contado, empresa):  # noqa: F811
        datos = leer(empresa, lambda: contado.toJSON())
        assert contado.medio_cobro == '' and datos['medio_cobro'] is None
        assert datos['condicion_pago'] == {'id': 'efectivo', 'name': 'Contado'} and datos['payment_type']['name'] == 'Contado'

    def test_respaldo_posterior_de_una_venta_al_contado(self, web, empresa, contado):  # noqa: F811
        r = registrar(web, contado, importe=None, medio='tarjeta_debito', referencia='VOUCHER 1234', nota='Pasó la tarjeta en caja')
        assert r.status_code == 201 and r.json()['cuenta_por_cobrar'] is None
        [resp] = respaldos(empresa)
        assert (resp.origen, resp.abono_id, resp.importe) == ('contado', None, contado.total)
        assert not leer(empresa, lambda: PaymentsCtaCollect.objects.exists())


# ---------------------------------------------------------------- archivos

class TestArchivos:

    @pytest.mark.parametrize('nombre, contenido, tipo, codigo', [
        ('grande.pdf', PDF + b'\0' * sv.MAX_BYTES, 'application/pdf', 'archivo_grande'),
        ('vacio.pdf', b'', 'application/pdf', 'archivo_vacio'),
        ('animado.gif', b'GIF89a' + b'\0' * 20, 'image/gif', 'archivo_tipo'),
        ('sin-extension', PDF, 'application/pdf', 'archivo_tipo'),
        ('pagina.pdf', b'<html><script>alert(1)</script></html>', 'application/pdf', 'archivo_contenido'),
        ('vector.png', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'image/png', 'archivo_contenido'),
        ('cambiado.jpg', b'\x89PNG\r\n\x1a\n' + b'\0' * 20, 'image/jpeg', 'archivo_contenido'),
        ('roto.png', b'\x89PNG\r\n\x1a\n' + b'basura', 'image/png', 'archivo_contenido'),
    ])
    def test_formatos_y_tamanos_invalidos(self, web, empresa, credito, nombre, contenido, tipo, codigo):  # noqa: F811
        r = registrar(web, credito, archivo=SimpleUploadedFile(nombre, contenido, content_type=tipo))
        assert r.status_code == 400 and r.json()['codigo'] == codigo, (nombre, r.content)
        assert not respaldos(empresa) and saldo(empresa, credito) == Decimal('23.00')

    def test_descarga_privada_solo_para_la_empresa_y_con_permiso(self, web, empresa, empresa_b, dueno, credito):  # noqa: F811
        r = registrar(web, credito, archivo=archivo('foto.png', imagen('PNG'), 'image/png'))
        resp = respaldos(empresa)[0]
        url = r.json()['respaldo']['archivo']['url']
        descarga = web.get(url)
        assert descarga.status_code == 200 and descarga['Content-Type'] == 'image/png'
        assert descarga['X-Content-Type-Options'] == 'nosniff' and 'sandbox' in descarga['Content-Security-Policy']
        assert b''.join(descarga.streaming_content) == imagen('PNG')
        assert 'attachment' in web.get(url + '?descargar=1')['Content-Disposition']
        assert web.get(f'/media/{resp.archivo.name}').status_code == 404   # la entrega general no sirve «privado/»
        ajeno = helpers.crear_usuario('dueno.ajeno', empresa_b, ROLE_OWNER)
        wb = entrar(ajeno, empresa_b)
        assert wb.get(url).status_code == 404 and wb.get(url_factura(credito)).status_code == 404
        assert wb.get(f'/cobros/respaldo/{resp.pk}/').status_code == 404
        consulta = entrar(helpers.crear_usuario('consulta.f', empresa, ROLE_READONLY), empresa)
        assert consulta.get(url).status_code == 200
        sin_ver = helpers.crear_grupo('SOLO VENTA FICTICIA', ['add_sale'])
        ws = entrar(helpers.crear_usuario('solo.venta', empresa, sin_ver), empresa)
        # Sin el permiso de ver: en GET el marco redirige al panel con aviso (302); en POST responde 403.
        assert ws.get(url).status_code == 302 and ws.get(url_factura(credito)).status_code == 302
        assert registrar(ws, credito, nota='sin permiso').status_code == 403
        assert ClienteWeb().get(url).status_code == 302   # sin sesión, al login


# ---------------------------------------------------------------- permisos y revisión

class TestPermisosYRevision:

    def test_vendedor_registra_pero_no_revisa_y_los_de_consulta_solo_ven(self, empresa, dueno, vendedor, credito):  # noqa: F811
        wv = entrar(vendedor, empresa)
        r = registrar(wv, credito, nota='Cobro del vendedor')
        assert r.status_code == 201 and r.json()['capacidades'] == {'puede_ver': True, 'puede_registrar': True, 'puede_revisar': False, 'puede_eliminar_cobros': False}
        resp_id = r.json()['respaldo']['id']
        assert wv.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'revisado'}).status_code == 403
        for rol in (ROLE_ACCOUNTANT, ROLE_READONLY):
            c = entrar(helpers.crear_usuario(f'u.{rol.lower()}', empresa, rol), empresa)
            assert registrar(c, credito, nota='no').status_code == 403
            assert c.get(url_factura(credito)).status_code == 200 and c.get(f'/cobros/respaldo/{resp_id}/').status_code == 200
            assert c.get(url_factura(credito)).json()['capacidades']['puede_registrar'] is False
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 1

    def test_revision_con_responsable_fecha_y_motivo_sin_tocar_el_saldo(self, web, empresa, dueno, credito):  # noqa: F811
        resp_id = registrar(web, credito, nota='Transferencia').json()['respaldo']['id']
        assert saldo(empresa, credito) == Decimal('13.00')
        r = web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'rechazado', 'motivo': ''})
        assert r.status_code == 400 and r.json()['codigo'] == 'motivo_rechazo'
        r = web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'rechazado', 'motivo': 'No aparece en el banco'})
        assert r.status_code == 200
        datos = r.json()
        assert datos['estado']['id'] == 'rechazado' and datos['revisado_por']['username'] == dueno.username and datos['motivo_revision'] == 'No aparece en el banco'
        assert datos['revisado_en'] is not None and [h['accion'] for h in datos['historial']] == ['registro', 'revision']
        assert saldo(empresa, credito) == Decimal('13.00')   # rechazar no revierte el abono: eso lo hace eliminar el cobro
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.get().anulado_en) is None
        r = web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'revisado'})
        assert r.status_code == 200 and r.json()['motivo_revision'] == ''
        r = web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'revisado'})
        assert r.status_code == 400 and r.json()['codigo'] == 'nada_que_cambiar'
        r = web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'otro'})
        assert r.status_code == 400 and r.json()['codigo'] == 'estado'
        assert web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'pendiente'}).json()['revisado_por'] is None
        assert AuditLog.objects.filter(action='cobro_respaldo_revision', company=empresa).count() == 3

    def test_eliminar_el_cobro_devuelve_el_saldo_y_el_respaldo_conserva_su_historia(self, web, empresa, credito):  # noqa: F811
        resp_id = registrar(web, credito, nota='Cobro equivocado').json()['respaldo']['id']
        abono_id = leer(empresa, lambda: PaymentsCtaCollect.objects.get().pk)
        assert web.post('/pos/ctas/collect/', {'action': 'delete_pay', 'id': abono_id}).json() == {}
        assert saldo(empresa, credito) == Decimal('23.00')
        resp = leer(empresa, lambda: RespaldoCobro.objects.get(pk=resp_id))
        assert resp.abono_id is None and resp.origen == 'abono'
        assert leer(empresa, lambda: [c.accion for c in resp.cambios.all()]) == ['registro', 'cobro_eliminado']
        datos = web.get(url_factura(credito)).json()
        assert datos['abonos'] == [] and [x['id'] for x in datos['respaldos']] == [resp_id]


# ---------------------------------------------------------------- edición con historial

class TestEdicion:

    def test_quien_registro_corrige_mientras_esta_pendiente_y_queda_lo_anterior(self, web, empresa, dueno, vendedor, credito):  # noqa: F811
        wv = entrar(vendedor, empresa)
        resp_id = registrar(wv, credito, nota='Nota inicial', archivo=archivo()).json()['respaldo']['id']
        anterior = leer(empresa, lambda: RespaldoCobro.objects.get(pk=resp_id).archivo.name)
        r = wv.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': 'Nota corregida', 'referencia': 'TRX-2',
                                                            'archivo': archivo('nuevo.png', imagen('PNG'), 'image/png')})
        assert r.status_code == 200
        datos = r.json()
        assert datos['nota'] == 'Nota corregida' and datos['referencia'] == 'TRX-2' and datos['archivo']['nombre'] == 'nuevo.png'
        acciones = {h['accion']: h['detalle'] for h in datos['historial']}
        assert acciones['nota'] == {'antes': 'Nota inicial', 'despues': 'Nota corregida', 'vuelve_a_pendiente': False}
        assert acciones['archivo']['antes'] == anterior and acciones['archivo']['antes_nombre'] == 'comprobante.pdf'
        resp = leer(empresa, lambda: RespaldoCobro.objects.get(pk=resp_id))
        assert resp.archivo.name != anterior and resp.archivo.storage.exists(anterior)   # el original no se borra
        assert wv.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': 'Nota corregida'}).json()['codigo'] == 'nada_que_cambiar'
        assert wv.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': ''}).status_code == 200   # queda el archivo
        otro = entrar(helpers.crear_usuario('otro.cajero', empresa, ROLE_SELLER), empresa)
        assert otro.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': 'ajena'}).status_code == 403
        assert web.post(f'/cobros/respaldo/{resp_id}/revisar/', {'estado': 'revisado'}).status_code == 200
        assert wv.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': 'tarde'}).status_code == 403
        r = web.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': 'El revisor corrige'})   # y vuelve a pendiente
        assert r.status_code == 200 and r.json()['estado']['id'] == 'pendiente' and r.json()['revisado_por'] is None
        assert AuditLog.objects.filter(action='cobro_respaldo_cambio', company=empresa).count() == 3

    def test_no_se_deja_sin_nota_ni_archivo(self, web, empresa, credito):  # noqa: F811
        resp_id = registrar(web, credito, nota='Solo nota').json()['respaldo']['id']
        r = web.post(f'/cobros/respaldo/{resp_id}/editar/', {'nota': ''})
        assert r.status_code == 400 and r.json()['codigo'] == 'respaldo_requerido'


# ---------------------------------------------------------------- privacidad y pantalla de cuentas por cobrar

class TestPrivacidadYPantallaCxC:

    def test_nota_y_archivo_fuera_del_json_xml_ride_y_correo(self, web, empresa, comprador, producto, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = vender(web, comprador, producto, medio_cobro='transferencia', nota_cobro='NOTA-SECRETA-123', referencia_cobro='REF-SECRETA',
                   cash='0', change='0')
        assert 'error' not in r, r
        venta = venta_de(empresa, 271)
        privados = ('NOTA-SECRETA-123', 'REF-SECRETA', 'respaldo', 'privado/')
        textos = leer(empresa, lambda: (json.dumps(venta.toJSON(), ensure_ascii=False), venta.xml_signed or '',
                                        venta.xml_authorized.read().decode(), texto_del_pdf(venta.ride_pdf()),
                                        json.dumps(venta.additional_info)))
        for texto in textos:
            assert not any(p in texto for p in privados), texto[:200]
        from django.core import mail
        assert all('NOTA-SECRETA-123' not in (m.body or '') for m in mail.outbox)

    def test_pantalla_de_cuentas_por_cobrar_exige_nota_o_archivo_y_acepta_archivo(self, web, empresa, credito):  # noqa: F811
        datos = {'action': 'add', 'ctas_collect': cxc_de(credito).pk, 'date_joined': credito.date_joined.isoformat(), 'valor': '5.00',
                 'medio_pago': 'deposito', 'referencia': 'DEP-1', 'description': '', 'clave': uuid.uuid4().hex}
        r = web.post('/pos/ctas/collect/add/', datos).json()
        assert r == {'error': sv.MENSAJES['respaldo_requerido']}
        r = web.post('/pos/ctas/collect/add/', {**datos, 'archivo': archivo()}).json()
        assert r == {}, r
        [resp] = respaldos(empresa)
        assert resp.origen == 'abono' and resp.archivo_tipo == 'pdf' and resp.importe == Decimal('5.00') and saldo(empresa, credito) == Decimal('18.00')
        r = web.post('/pos/ctas/collect/add/', {**datos, 'archivo': archivo()}).json()   # misma clave: no duplica
        assert r == {} and leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 1
        r = web.post('/pos/ctas/collect/add/', {**datos, 'clave': uuid.uuid4().hex, 'description': 'Depósito en ventanilla'}).json()
        assert r == {} and leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 2
        assert respaldos(empresa)[1].nota == 'Depósito en ventanilla' and respaldos(empresa)[1].archivo.name in ('', None)

    def test_factura_anulada_en_el_sri_no_recibe_cobros(self, web, empresa, credito):  # noqa: F811
        with company_context(empresa):   # en PostgreSQL la seguridad por filas exige el contexto de la empresa
            Sale.objects.filter(pk=credito.pk).update(anulado_sri_fecha=credito.date_joined)
        r = registrar(web, credito, nota='x')
        assert r.status_code == 400 and r.json()['codigo'] == 'factura_anulada'
