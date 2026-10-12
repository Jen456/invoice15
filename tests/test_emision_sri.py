"""Emisión electrónica en dos fases (auditoría SRI, oct-2026), con un SRI simulado (sin red):
el comprobante se guarda firmado antes de enviarlo, nunca se deshace ni se renumera después de enviarlo,
los reintentos conservan la clave, el cupo se consume solo al autorizar, y reglas de servidor para
consumidor final, ticket, borrado, notas de crédito, identificación y RUC del proveedor."""
import base64
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from core.pos import emision
from core.pos.clientes import consumidor_final
from core.pos.forms import ClientForm
from core.pos.models import Client, CreditNote, Receipt, Sale, SaleDetail, VoucherErrors
from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, ROLE_READONLY
from core.user.models import User
from tests import helpers
from tests.test_firma_sri import CLAVE, generar_p12

pytestmark = pytest.mark.django_db
RUC_PROVEEDOR = '0991234567001'
VENTAS = '/pos/sale/admin/'


class SRIFalso:
    """Servicios web del SRI simulados. `recepciones` guarda cada XML recibido."""

    def __init__(self):
        self.recepciones, self.consultas, self.urls = [], [], []
        self.respuestas_recepcion = []      # cada una: 'RECIBIDA', ('DEVUELTA', [(código, mensaje)]) o una excepción
        self.respuestas_autorizacion = []   # cada una: 'AUTORIZADO', 'NO AUTORIZADO' o None (aún sin respuesta)

    def __call__(self, url, timeout):
        self.urls.append(url)
        return SimpleNamespace(service=self)

    def validarComprobante(self, xml_b64):
        self.recepciones.append(base64.b64decode(xml_b64).decode())
        respuesta = self.respuestas_recepcion.pop(0) if self.respuestas_recepcion else 'RECIBIDA'
        if isinstance(respuesta, Exception):
            raise respuesta
        if respuesta == 'RECIBIDA':
            return SimpleNamespace(estado='RECIBIDA', comprobantes=None)
        mensajes = [SimpleNamespace(identificador=c, mensaje=m, informacionAdicional='', tipo='ERROR') for c, m in respuesta[1]]
        return SimpleNamespace(estado='DEVUELTA', comprobantes=SimpleNamespace(comprobante=[
            SimpleNamespace(claveAcceso='', mensajes=SimpleNamespace(mensaje=mensajes))]))

    def autorizacionComprobante(self, clave):
        self.consultas.append(clave)
        estado = self.respuestas_autorizacion.pop(0) if self.respuestas_autorizacion else None
        if estado is None:
            return SimpleNamespace(claveAccesoConsultada=clave, numeroComprobantes='0', autorizaciones=None)
        mensajes = None if estado == 'AUTORIZADO' else SimpleNamespace(mensaje=[SimpleNamespace(
            identificador='56', mensaje='ERROR ESTABLECIMIENTO CERRADO', informacionAdicional='', tipo='ERROR')])
        return SimpleNamespace(autorizaciones=SimpleNamespace(autorizacion=[SimpleNamespace(
            estado=estado, numeroAutorizacion=clave, fechaAutorizacion=timezone.now(), ambiente='PRODUCCIÓN',
            comprobante=self.recepciones[-1] if self.recepciones else '<factura/>', mensajes=mensajes)]))


@pytest.fixture
def sri(monkeypatch):
    falso = SRIFalso()
    monkeypatch.setattr(emision, '_cliente', falso)
    monkeypatch.setattr(emision, 'ESPERAS_AL_EMITIR', (0, 0, 0))
    monkeypatch.setattr(emision, 'ESPERAS_AL_CONSULTAR', (0,))
    return falso


@pytest.fixture(scope='module')
def p12():
    return generar_p12()[0]


@pytest.fixture
def empresa(settings, p12):
    settings.FPA_RUC_PROVEEDOR = RUC_PROVEEDOR
    empresa = helpers.crear_empresa('EMISORA', environment_type=2)
    helpers.configurar_facturacion(empresa, estab='001', punto='002', ultimo_factura=270, ultimo_nota=4, ambiente=2)
    empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
    empresa.electronic_signature_key = CLAVE
    empresa.save()
    return empresa


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.emisora', empresa, ROLE_OWNER)


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


@pytest.fixture
def comprador(empresa):
    cliente = helpers.crear_cliente('comprador.ruc', empresa, '0991234567001', '0990000002')
    leer(empresa, lambda: Client.objects.filter(pk=cliente.pk).update(identification_type='04'))
    cliente.identification_type = '04'
    return cliente


@pytest.fixture
def producto(empresa):
    return helpers.crear_producto(empresa, 'P100', pvp='10.00')


def vender(web, cliente, producto, cantidad=2, receipt='01', fecha='2026-10-11', **extra):
    datos = {'action': 'add', 'receipt': receipt, 'client': cliente.pk, 'payment_type': 'efectivo', 'date_joined': fecha,
             'cash': '100', 'change': '0', 'time_limit': '0', 'payment_method': '01', 'additional_info': '[]',
             'products': json.dumps([{'id': producto.pk, 'cant': cantidad, 'price_current': str(producto.pvp), 'dscto': 0}])}
    datos.update(extra)
    return web.post(f'{VENTAS}add/', datos).json()


def accion(web, action, venta):
    return web.post(VENTAS, {'action': action, 'id': venta.pk}).json()


def leer(empresa, consulta):
    """Las lecturas de datos de empresa, dentro de su contexto (en PostgreSQL rige la seguridad por filas)."""
    with company_context(empresa):
        return consulta()


def venta_de(empresa, numero):
    return leer(empresa, lambda: Sale.objects.get(voucher_number=f'{numero:09d}'))


def refrescar(*objetos):
    for objeto in objetos:
        with company_context(objeto.company):
            objeto.refresh_from_db()


def periodo(empresa):
    return SubscriptionPeriod.objects.get(company=empresa, status='activa')


# ---------------------------------------------------------------- flujo principal

class TestFlujo:

    def test_autoriza_al_primer_intento(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert r['resp'] is True and r['estado'] == 'authorized' and r['print_url']
        assert venta.status == 'authorized' and len(venta.access_code) == 49 and venta.xml_authorized and venta.pdf_authorized
        assert sri.recepciones == [venta.xml_signed]                      # se envía exactamente lo que se guardó
        assert all('celcer' not in u for u in sri.urls)                   # producción
        assert f'<ds:Signature' in venta.xml_signed and f'<campoAdicional nombre="RUC Proveedor">{RUC_PROVEEDOR}</campoAdicional>' in venta.xml_signed
        assert '<ambiente>2</ambiente>' in venta.xml_signed and '<estab>001</estab><ptoEmi>002</ptoEmi><secuencial>000000271</secuencial>' in venta.xml_signed
        assert (periodo(empresa).documents_used, periodo(empresa).documents_reserved) == (1, 0)

    def test_si_el_sri_tarda_queda_en_proceso_y_el_numero_no_se_reutiliza(self, web, empresa, comprador, producto, sri):
        r = vender(web, comprador, producto)                               # RECIBIDA, sin autorización aún
        primera = venta_de(empresa, 271)
        assert r['resp'] is True and r['en_proceso'] and 'En proceso en el SRI' in r['mensaje']
        assert primera.status == 'in_process' and primera.sri_sent_at is not None
        assert QuotaReservation.objects.get(voucher_id=primera.pk).status == 'reservada'
        clave = primera.access_code
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        assert venta_de(empresa, 272).voucher_number == '000000272'        # la siguiente venta no repite el 271
        # Consultar desde el listado: no reenvía, consulta con la misma clave
        recepciones = len(sri.recepciones)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = accion(web, 'generate_invoice', primera)
        refrescar(primera)
        assert r['resp'] is True and primera.status == 'authorized' and primera.access_code == clave
        assert len(sri.recepciones) == recepciones and sri.consultas[-1] == clave
        assert periodo(empresa).documents_used == 2 and periodo(empresa).documents_reserved == 0

    def test_sin_respuesta_se_reenvia_el_mismo_xml(self, web, empresa, comprador, producto, sri):
        sri.respuestas_recepcion = [TimeoutError('sin red')]
        r = vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert r['en_proceso'] and venta.status == 'in_process'
        sri.respuestas_recepcion = [('DEVUELTA', [('43', 'CLAVE ACCESO REGISTRADA')])]   # ya lo tenía
        sri.respuestas_autorizacion = [None, 'AUTORIZADO']
        r = accion(web, 'generate_invoice', venta)
        refrescar(venta)
        assert r['resp'] is True and venta.status == 'authorized'
        assert len(sri.recepciones) == 2 and sri.recepciones[0] == sri.recepciones[1] == venta.xml_signed

    def test_devuelta_queda_guardada_y_se_reenvia_con_la_misma_clave(self, web, empresa, comprador, producto, sri):
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        r = vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert r['resp'] is False and '[35] ARCHIVO NO CUMPLE ESTRUCTURA XML' in r['error'] and 'se conservan el número y la clave' in r['error']
        assert venta.status == 'returned' and leer(empresa, lambda: VoucherErrors.objects.filter(reference=venta.voucher_number_full).exists())
        assert QuotaReservation.objects.get(voucher_id=venta.pk).status == 'liberada'
        clave, firmado_antes = venta.access_code, venta.signed_at
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = accion(web, 'generate_invoice', venta)
        refrescar(venta)
        assert r['resp'] is True and venta.status == 'authorized' and venta.access_code == clave and venta.signed_at > firmado_antes
        assert periodo(empresa).documents_used == 1

    def test_secuencial_registrado_no_se_reintenta_solo(self, web, empresa, comprador, producto, sri):
        sri.respuestas_recepcion = [('DEVUELTA', [('45', 'ERROR SECUENCIAL REGISTRADO')])]
        r = vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert venta.status == 'sequential_registered_error' and 'ya tiene registrado el número 001-002-000000271' in r['error']
        envios = len(sri.recepciones)
        assert 'soporte' in accion(web, 'generate_invoice', venta)['error'] and len(sri.recepciones) == envios

    def test_no_autorizado(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['NO AUTORIZADO']
        r = vender(web, comprador, producto)
        assert r['resp'] is False and '[56] ERROR ESTABLECIMIENTO CERRADO' in r['error']
        assert venta_de(empresa, 271).status == 'not_authorized'

    def test_listados_en_json(self, web, empresa, comprador, producto, sri):
        vender(web, comprador, producto)                                   # en proceso, con XML firmado guardado
        filas = web.post(VENTAS, {'action': 'search', 'start_date': '', 'end_date': ''}).json()
        assert [f['status']['id'] for f in filas] == ['in_process'] and 'xml_signed' not in filas[0]
        assert filas[0]['emission_date'] == f'{timezone.localdate():%Y-%m-%d}'
        assert web.post('/pos/credit/note/admin/', {'action': 'search', 'start_date': '', 'end_date': ''}).json() == []

    def test_tarea_periodica_consulta_los_pendientes(self, web, empresa, comprador, producto, sri, capsys):
        vender(web, comprador, producto)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert venta_de(empresa, 271).status == 'authorized'
        assert 'autorizados 1' in capsys.readouterr().out

    def test_firma_fallida_deshace_la_venta(self, web, empresa, comprador, producto, sri):
        empresa.electronic_signature_key = 'equivocada'
        empresa.save()
        r = vender(web, comprador, producto)
        assert r['error'].startswith('La clave no abre la firma electrónica') and sri.recepciones == []
        assert not leer(empresa, lambda: Sale.objects.exists())
        with company_context(empresa):
            assert Receipt.objects.get(voucher_type='01', environment_type=2, issuing_point_code='002').sequence == 270   # el número sigue libre

    def test_sin_ruc_del_proveedor_no_se_emite_en_produccion(self, web, empresa, comprador, producto, sri, settings):
        settings.FPA_RUC_PROVEEDOR = ''
        r = vender(web, comprador, producto)
        assert r['error'] == emision.MENSAJE_SIN_RUC_PROVEEDOR and not leer(empresa, lambda: Sale.objects.exists())

    def test_fecha_de_emision_es_la_de_hoy(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto, fecha='2020-01-01')
        venta = venta_de(empresa, 271)
        hoy = timezone.localdate()
        assert venta.date_joined == hoy == venta.emission_date
        assert f'<fechaEmision>{hoy:%d/%m/%Y}</fechaEmision>' in venta.xml_signed and venta.access_code.startswith(f'{hoy:%d%m%Y}')

    def test_apostrofos_intactos(self, web, empresa, comprador, producto, sri):
        User.objects.filter(pk=comprador.user_id).update(names="PANADERÍA D'ONOFRIO")
        r = vender(web, comprador, producto, additional_info=json.dumps([{'name': "Atención d'Mesa", 'value': "Mesa 'A'"}]))
        assert 'error' not in r, r
        xml = venta_de(empresa, 271).xml_signed
        assert "<razonSocialComprador>PANADERÍA D'ONOFRIO</razonSocialComprador>" in xml
        assert '<campoAdicional nombre="Atención d\'Mesa">Mesa \'A\'</campoAdicional>' in xml

    def test_informacion_adicional_sin_campos_vacios(self, web, empresa, comprador, producto, sri):
        User.objects.filter(pk=comprador.user_id).update(email=None)
        vender(web, comprador, producto)
        xml = venta_de(empresa, 271).xml_signed
        assert 'nombre="Email"' not in xml and xml.index('nombre="RUC Proveedor"') > xml.index('nombre="Dirección"')


# ---------------------------------------------------------------- reglas del servidor

class TestReglas:

    def test_no_se_borra_lo_que_llego_al_sri(self, web, empresa, comprador, producto, sri):
        vender(web, comprador, producto)                                   # queda en proceso
        venta = venta_de(empresa, 271)
        r = web.post(f'{VENTAS}delete/{venta.pk}/').json()
        assert 'no se puede eliminar' in r['error'] and leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).exists())

    def test_se_puede_borrar_una_devuelta(self, web, empresa, comprador, producto, sri):
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert web.post(f'{VENTAS}delete/{venta.pk}/').json() == {} and not leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).exists())

    def test_sin_cupo_la_venta_no_se_guarda(self, web, empresa, comprador, producto, sri):
        SubscriptionPeriod.objects.filter(company=empresa).update(document_limit=5, documents_used=5)
        r = vender(web, comprador, producto)
        assert 'Usaste los 5 documentos' in r['error'] and sri.recepciones == []
        assert not leer(empresa, lambda: Sale.objects.exists())

    def test_ticket_no_disponible_en_produccion(self, web, empresa, comprador, producto, sri):
        assert 'no está disponible en Producción' in vender(web, comprador, producto, receipt='08')['error']
        assert 'TICKET DE VENTA' not in web.get(f'{VENTAS}add/').content.decode()

    def test_consumidor_final_propio_y_tope_de_50(self, web, empresa, producto, sri):
        # Las empresas de demostración ya usan el usuario 9999999999999: cada empresa tiene el suyo.
        User.objects.create(username='9999999999999', names='CONSUMIDOR FINAL')
        with company_context(empresa):
            cf = consumidor_final(empresa)
        assert cf.dni == '9999999999999' and cf.identification_type == '07' and cf.user.username != '9999999999999'
        r = vender(web, cf, producto, cantidad=5)                         # 5 × 10 + IVA = 57,50
        assert 'no puede superar USD 50,00' in r['error'] and not leer(empresa, lambda: Sale.objects.exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert vender(web, cf, producto, cantidad=4)['resp'] is True        # 46,00

    def test_identificacion_del_comprador(self):
        base = {'mobile': '0990000000', 'birthdate': '1990-01-01', 'address': 'Guayaquil', 'send_email_invoice': True}
        assert not ClientForm({**base, 'identification_type': '05', 'dni': '0912345670'}).is_valid()   # dígito verificador
        assert ClientForm({**base, 'identification_type': '05', 'dni': '2400000002'}).is_valid()       # Santa Elena (24)
        assert not ClientForm({**base, 'identification_type': '04', 'dni': '0912345678'}).is_valid()
        assert not ClientForm({**base, 'identification_type': '07', 'dni': '0912345678'}).is_valid()
        assert not ClientForm({**base, 'identification_type': '05', 'dni': '9999999999999'}).is_valid()
        assert ClientForm({**base, 'identification_type': '06', 'dni': 'ab123456'}).is_valid()

    def test_comprador_ya_registrado_en_otra_empresa(self, web, empresa):
        otra = helpers.crear_empresa('OTRA')
        helpers.crear_cliente('0912345675', otra, '0912345675', '0990000003')   # su usuario es la cédula
        datos = {'action': 'create_client', 'names': 'JUAN PÉREZ', 'email': 'juan@example.com', 'dni': '0912345675',
                 'identification_type': '05', 'mobile': '0990000004', 'birthdate': '1990-01-01', 'address': 'Quito'}
        r = web.post(f'{VENTAS}add/', datos).json()
        assert 'error' not in r, r
        with company_context(empresa):
            nuevo = Client.objects.get(dni='0912345675')
        assert nuevo.user.username != '0912345675' and nuevo.user.names == 'JUAN PÉREZ'


# ---------------------------------------------------------------- notas de crédito

class TestNotasCredito:

    @pytest.fixture
    def factura(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto, cantidad=2)
        return venta_de(empresa, 271)

    def nota(self, web, factura, cantidad, precio='0.01', motivo='Devolución por falla'):
        detalle = leer(factura.company, lambda: SaleDetail.objects.filter(sale=factura).first())
        return web.post('/pos/credit/note/admin/add/', {
            'action': 'add', 'sale': factura.pk, 'motive': motivo, 'create_electronic_invoice': 'on',
            'products': json.dumps([{'id': detalle.pk, 'quantity': cantidad, 'price': precio, 'dscto': 99}])}).json()

    def test_parcial_con_precio_de_la_factura_y_sin_exceder(self, web, empresa, factura, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = self.nota(web, factura, 1)                                     # el navegador intenta precio 0,01 y 99 % de descuento
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=factura))
        assert r['resp'] is True and nota.status == 'authorized' and nota.total == Decimal('11.50')
        assert '<numDocModificado>001-002-000000271</numDocModificado>' in nota.xml_signed and '<rise>' not in nota.xml_signed
        refrescar(factura)
        assert factura.status == 'authorized'                              # parcial: la factura sigue vigente
        assert 'solo quedan 1' in self.nota(web, factura, 2)['error']
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert self.nota(web, factura, 1)['resp'] is True
        refrescar(factura)
        assert factura.status == 'canceled'                                # las notas cubren el total
        assert 'autorizada por el SRI' in self.nota(web, factura, 1)['error']

    def test_motivo_obligatorio(self, web, factura):
        assert self.nota(web, factura, 1, motivo='   ')['error'] == 'Escribe el motivo de la nota de crédito.'

    def test_nota_total_desde_el_listado_no_se_duplica(self, web, empresa, factura, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert accion(web, 'create_credit_note', factura)['resp'] is True
        assert 'autorizada por el SRI' in accion(web, 'create_credit_note', factura)['error']
        assert leer(empresa, lambda: CreditNote.objects.filter(sale=factura).count()) == 1

    def test_nota_desde_el_listado_exige_permiso(self, client, empresa, factura):
        lector = helpers.crear_usuario('lector.emisora', empresa, ROLE_READONLY)
        helpers.iniciar_sesion(client, lector, empresa=empresa)
        assert client.post(VENTAS, {'action': 'create_credit_note', 'id': factura.pk}).json()['error'] == 'Tu perfil no puede emitir notas de crédito.'

    def test_no_sobre_consumidor_final(self, web, empresa, producto, sri):
        with company_context(empresa):
            cf = consumidor_final(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, cf, producto, cantidad=1)
        assert 'consumidor final' in self.nota(web, venta_de(empresa, 271), 1)['error']


# ---------------------------------------------------------------- correo al comprador

class TestCorreo:

    def test_xml_y_ride_adjuntos(self, web, empresa, comprador, producto, sri):
        leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))
        User.objects.filter(pk=comprador.user_id).update(email='comprador@example.com')
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert venta.status == 'authorized_and_sent_by_email' and len(mail.outbox) == 1
        correo = mail.outbox[0]
        assert correo.to == ['comprador@example.com'] and sorted(n.rsplit('.', 1)[1] for n, *_ in correo.attachments) == ['pdf', 'xml']
        assert 'vía FacturaPorAquí' in correo.from_email and correo.reply_to == ['empresa@example.com']

    def test_sin_correo_no_se_marca_enviada(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)                                   # el comprador no recibe correos
        assert venta_de(empresa, 271).status == 'authorized' and mail.outbox == []
