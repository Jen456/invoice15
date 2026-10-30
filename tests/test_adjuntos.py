"""Comprobantes de pago adjuntos (core/adjuntos): validación del archivo por su contenido, alta y baja lógica, permisos por
rol y por plan, aislamiento entre empresas, archivo protegido, comprobante enviado con el formulario de cobro, pago o
gasto (misma transacción), resumen y ZIP del mes, y módulo del menú con sus roles."""
import io
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from core.adjuntos import archivos, servicios as sv
from core.adjuntos.models import Adjunto
from core.pos import cuentas_por_pagar, cxc
from core.pos.models import DebtsPay, Expenses, PaymentsCtaCollect, PaymentsDebtsPay
from core.security.models import Module
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import cxc_de, factura_autorizada

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
MES = HOY.replace(day=1)
PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'


def imagen(formato='PNG', tamano=(40, 30)):
    salida = io.BytesIO()
    Image.new('RGB', tamano, (200, 50, 50)).save(salida, format=formato)
    return salida.getvalue()


def subido(nombre, contenido, tipo='application/octet-stream'):
    return SimpleUploadedFile(nombre, contenido, content_type=tipo)


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


def api(tipo, pk):
    return f'/adjuntos/api/{tipo}/{pk}/'


@pytest.fixture
def comprador(empresa):
    return helpers.crear_cliente('comprador.adj', empresa, '0912345678', '0990000001')


@pytest.fixture
def producto(empresa):
    return helpers.crear_producto(empresa, 'ADJ1', pvp='10.00')


@pytest.fixture
def venta_contado(empresa, comprador, admin, producto):
    """Factura de contado pagada por «otros con utilización del sistema financiero» (20): se espera un comprobante."""
    return factura_autorizada(empresa, comprador, admin, producto, fecha=HOY)


@pytest.fixture
def cobro(empresa, comprador, admin, producto):
    venta = factura_autorizada(empresa, comprador, admin, producto, credito=True, fecha=HOY - timedelta(days=3))
    with company_context(empresa):
        return cxc.registrar_cobro(empresa, admin, cxc_de(venta).pk, HOY, '10.00', 'transferencia', 'TRX-77', 'Abono')


@pytest.fixture
def pago(empresa, admin):
    proveedor = ayuda_compras.crear_proveedor(empresa)
    compra = ayuda_compras.compra_antigua(empresa, proveedor, '100.00', credito=True, fecha=HOY - timedelta(days=5))
    with company_context(empresa):
        deuda = DebtsPay.objects.get(purchase=compra)
        return cuentas_por_pagar.registrar_pago(deuda.pk, admin, fecha=HOY, valor='40.00', medio_pago='cheque', referencia='CH-5')


@pytest.fixture
def gasto(empresa):
    tipo = ayuda_compras.crear_tipo_gasto(empresa, 'MOVILIZACIÓN')
    with company_context(empresa):
        return Expenses.objects.create(type_expense=tipo, description='Taxi', valor=Decimal('8.50'), medio_pago='transferencia',
                                       referencia='T-1', date_joined=HOY)


# ---------------------------------------------------------------- archivo

class TestArchivos:

    def test_formatos_por_contenido(self):
        assert archivos.validar('recibo.PDF', PDF)[1] == 'application/pdf'
        assert archivos.validar('foto.jpg', imagen('JPEG'))[1] == 'image/jpeg'
        nombre, tipo, sha = archivos.validar('foto.png', imagen('PNG'))
        assert (nombre, tipo, len(sha)) == ('foto.png', 'image/png', 64)
        assert archivos.validar('mal nombrada.pdf', imagen('JPEG'))[0] == 'mal nombrada.jpg'   # la extensión sigue al contenido

    def test_webp(self):
        try:
            contenido = imagen('WEBP')
        except (OSError, KeyError):
            pytest.skip('Pillow sin WEBP')
        assert archivos.validar('foto.webp', contenido)[1] == 'image/webp'

    def test_rechazos(self, monkeypatch):
        with pytest.raises(archivos.ArchivoInvalido, match='Solo se admiten'):
            archivos.validar('nota.txt', b'hola')
        with pytest.raises(archivos.ArchivoInvalido, match='vac'):
            archivos.validar('nada.pdf', b'')
        with pytest.raises(archivos.ArchivoInvalido, match='pesa m'):
            archivos.validar('grande.pdf', b'%PDF-' + b'0' * archivos.MAX_BYTES)
        with pytest.raises(archivos.ArchivoInvalido, match='no se puede leer'):
            archivos.validar('rota.png', b'\x89PNG\r\n\x1a\n' + b'basura' * 10)
        monkeypatch.setattr(archivos, 'MAX_PIXELES', 100)
        with pytest.raises(archivos.ArchivoInvalido, match='demasiado grande'):
            archivos.validar('enorme.png', imagen('PNG', (20, 20)))

    def test_nombre_saneado(self):
        assert archivos.validar('..\\..\\x\x00y.txt', PDF)[0] == 'xy.pdf'
        assert archivos.validar('', PDF)[0] == 'comprobante.pdf'
        assert len(archivos.validar('a' * 400 + '.pdf', PDF)[0]) <= 150


# ---------------------------------------------------------------- servicio

class TestServicio:

    def test_adjuntar_listar_y_quitar(self, empresa, admin, cobro):
        with company_context(empresa):
            adjunto = sv.adjuntar(empresa, admin, 'cobro', cobro, subido('transf.pdf', PDF), referencia=' TRX  77 ', fecha=HOY.isoformat(),
                                  importe='10', descripcion='  pago   cliente ')
            assert adjunto.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/comprobantes-pago/')
            assert (adjunto.clase, adjunto.referencia, adjunto.fecha, adjunto.importe, adjunto.descripcion, adjunto.tamano, adjunto.tipo_mime) == (
                'transferencia', 'TRX 77', HOY, Decimal('10.00'), 'pago cliente', len(PDF), 'application/pdf')
            assert adjunto.subido_por == admin and adjunto.vigente and adjunto.nombre == 'transf.pdf'
            assert list(sv.listar('cobro', cobro.pk)) == [adjunto]
            with pytest.raises(sv.ErrorAdjunto) as error:
                sv.adjuntar(empresa, admin, 'cobro', cobro, subido('otra-copia.pdf', PDF))
            assert (error.value.codigo, error.value.estado) == ('duplicado', 409)
            otro = sv.adjuntar(empresa, admin, 'cobro', cobro, subido('foto.jpg', imagen('JPEG')), clase='bitcoin')
            assert otro.clase == 'transferencia'   # clase desconocida: la sugerida por el medio de pago del cobro
            sv.quitar(admin, adjunto, '  Subí el  archivo equivocado ')
            assert list(sv.listar('cobro', cobro.pk)) == [otro]
            assert list(sv.listar('cobro', cobro.pk, eliminados=True)) == [adjunto, otro]
            adjunto.refresh_from_db()
            assert adjunto.eliminado_por == admin and adjunto.eliminado_motivo == 'Subí el archivo equivocado'
            assert adjunto.archivo.storage.exists(adjunto.archivo.name)   # el archivo se conserva (historial)
            with pytest.raises(sv.ErrorAdjunto, match='ya se había quitado'):
                sv.quitar(admin, adjunto)
            assert sv.adjuntar(empresa, admin, 'cobro', cobro, subido('de-nuevo.pdf', PDF)).sha256 == adjunto.sha256   # quitado: se puede volver a subir

    @pytest.mark.parametrize('datos, codigo', [({'fecha': (HOY + timedelta(days=1)).isoformat()}, 'fecha'), ({'fecha': '31/10/2026'}, 'fecha'),
                                               ({'importe': 'abc'}, 'importe'), ({'importe': '0'}, 'importe'), ({'importe': '-3'}, 'importe')])
    def test_datos_invalidos_no_guardan_nada(self, empresa, admin, gasto, datos, codigo):
        with company_context(empresa):
            with pytest.raises(sv.ErrorAdjunto) as error:
                sv.adjuntar(empresa, admin, 'gasto', gasto, subido('t.pdf', PDF), **datos)
            assert error.value.codigo == codigo
            assert not Adjunto.objects.exists()

    def test_limite_por_documento(self, empresa, admin, gasto, monkeypatch):
        monkeypatch.setattr(archivos, 'MAX_POR_DOCUMENTO', 2)
        with company_context(empresa):
            sv.adjuntar(empresa, admin, 'gasto', gasto, subido('1.pdf', PDF))
            sv.adjuntar(empresa, admin, 'gasto', gasto, subido('2.png', imagen('PNG')))
            with pytest.raises(sv.ErrorAdjunto) as error:
                sv.adjuntar(empresa, admin, 'gasto', gasto, subido('3.jpg', imagen('JPEG')))
            assert error.value.codigo == 'limite'

    def test_abonos_automaticos_y_cobros_anulados_no_admiten(self, empresa, admin, cobro):
        with company_context(empresa):
            nota = cxc.crear_abono(cobro.ctas_collect, 'nota_credito', '1.00', HOY, 'NC de prueba')
            with pytest.raises(sv.ErrorAdjunto) as error:
                sv.adjuntar(empresa, admin, 'cobro', nota, subido('t.pdf', PDF))
            assert error.value.codigo == 'abono'
            cobro.anulado_en = timezone.now()
            cobro.save(update_fields=['anulado_en'])
            with pytest.raises(sv.ErrorAdjunto) as error:
                sv.adjuntar(empresa, admin, 'cobro', cobro, subido('t.pdf', PDF))
            assert error.value.codigo == 'anulado'

    def test_clase_sugerida_y_documento(self, empresa, venta_contado, pago, gasto, cobro):
        with company_context(empresa):
            assert sv.clase_sugerida('venta', venta_contado) == 'transferencia'   # forma de pago 20 del SRI
            assert sv.clase_sugerida('pago', pago) == 'cheque'
            assert sv.clase_sugerida('cobro', cobro) == 'transferencia'
            gasto.medio_pago = 'efectivo'
            assert sv.clase_sugerida('gasto', gasto) == 'recibo'
            venta = sv.dict_documento('venta', venta_contado)
            assert (venta['titulo'], venta['tercero'], venta['importe'], venta['requiere']) == (
                f'Factura {venta_contado.voucher_number_full}', 'comprador.adj', '23.00', True)
            assert sv.dict_documento('cobro', cobro)['titulo'] == f'Cobro de {cobro.ctas_collect.sale.voucher_number_full}'
            assert sv.dict_documento('pago', pago)['requiere'] is True and sv.dict_documento('gasto', gasto)['requiere'] is False

    def test_tambien_en(self, empresa, admin, cobro, gasto):
        with company_context(empresa):
            sv.adjuntar(empresa, admin, 'cobro', cobro, subido('t.pdf', PDF))
            del_gasto = sv.adjuntar(empresa, admin, 'gasto', gasto, subido('t.pdf', PDF))
            assert sv.tambien_en(del_gasto) == [{'tipo': 'cobro', 'id': cobro.pk, 'titulo': f'Cobro de {cobro.ctas_collect.sale.voucher_number_full}'}]


# ---------------------------------------------------------------- API y archivo

class TestApi:

    def test_propietario_sube_ve_y_quita(self, client, empresa, admin, venta_contado):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        url = api('venta', venta_contado.pk)
        datos = client.get(url).json()
        assert datos['documento']['titulo'] == f'Factura {venta_contado.voucher_number_full}' and datos['documento']['requiere'] is True
        assert datos['permisos'] == {'subir': True, 'quitar': True} and datos['adjuntos'] == [] and datos['bloqueo'] is None
        assert datos['documento']['clase_sugerida'] == 'transferencia' and datos['limites']['max_por_documento'] == archivos.MAX_POR_DOCUMENTO
        respuesta = client.post(url, {'archivo': subido('t.pdf', PDF), 'clase': 'deposito', 'referencia': 'DEP-1', 'fecha': HOY.isoformat(),
                                      'importe': '23.00', 'descripcion': 'Depósito en ventanilla'})
        assert respuesta.status_code == 201, respuesta.content
        adjunto = respuesta.json()['adjunto']
        assert (adjunto['clase']['id'], adjunto['referencia'], adjunto['importe'], adjunto['fecha'], adjunto['subido_por']) == (
            'deposito', 'DEP-1', '23.00', HOY.isoformat(), admin.username)
        assert adjunto['url'] == f'/adjuntos/{adjunto["id"]}/archivo/' and respuesta.json()['tambien_en'] == []
        archivo = client.get(adjunto['url'])
        assert archivo.status_code == 200 and archivo['Content-Type'] == 'application/pdf' and b''.join(archivo.streaming_content) == PDF
        assert archivo['X-Content-Type-Options'] == 'nosniff' and archivo['Content-Security-Policy'].startswith('sandbox')
        assert archivo['Cache-Control'] == 'private, no-store' and 'attachment' not in archivo.get('Content-Disposition', '')
        descarga = client.get(adjunto['url_descarga'])
        assert descarga['Content-Disposition'].startswith('attachment') and 't.pdf' in descarga['Content-Disposition']
        guardado = Adjunto.all_companies.get(pk=adjunto['id'])
        assert client.get('/media/' + guardado.archivo.name).status_code == 404   # privado/: nunca por /media/
        quitado = client.post(f'/adjuntos/api/quitar/{adjunto["id"]}/', {'motivo': 'Equivocado'})
        assert quitado.status_code == 200 and quitado.json()['adjunto']['eliminado'] is True
        historial = client.get(url).json()['adjuntos']
        assert historial[0]['eliminado'] is True and historial[0]['eliminado_motivo'] == 'Equivocado' and historial[0]['eliminado_por'] == admin.username
        assert client.post(f'/adjuntos/api/quitar/{adjunto["id"]}/').status_code == 400

    def test_errores(self, client, empresa, admin, venta_contado):
        url = api('venta', venta_contado.pk)
        assert client.get(url).status_code == 403   # sin sesión: JSON, no redirección
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert client.post(url, {}).json()['error'] == 'Elige el archivo del comprobante.'
        respuesta = client.post(url, {'archivo': subido('nota.txt', b'hola')})
        assert respuesta.status_code == 400 and 'Solo se admiten' in respuesta.json()['error'] and respuesta.json()['codigo'] == 'archivo'
        assert client.get(api('cheque', 1)).status_code == 404
        assert client.get(api('venta', 999999)).status_code == 404
        assert client.post('/adjuntos/api/quitar/999999/').status_code == 404
        assert client.get('/adjuntos/999999/archivo/').status_code == 404
        assert client.get(url + '?x=1', HTTP_ACCEPT='text/html').status_code == 200

    @pytest.mark.parametrize('rol, venta, cobro_', [
        (ROLE_OWNER, (200, True, True), (200, True, True)),
        (ROLE_ADMIN, (200, True, True), (200, True, True)),
        (ROLE_ACCOUNTANT, (200, True, True), (200, True, True)),     # add_adjunto y delete_adjunto del módulo
        (ROLE_SELLER, (200, True, False), (403, None, None)),        # add_sale; sin cuentas por cobrar
        (ROLE_READONLY, (200, False, False), (200, False, False)),
        (ROLE_CLIENT, (403, None, None), (403, None, None)),
    ])
    def test_permisos_por_rol(self, client, empresa, admin, venta_contado, cobro, rol, venta, cobro_):
        usuario = helpers.crear_usuario(f'rol.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        for tipo, documento, esperado in (('venta', venta_contado, venta), ('cobro', cobro, cobro_)):
            respuesta = client.get(api(tipo, documento.pk))
            assert respuesta.status_code == esperado[0], (rol, tipo, respuesta.content)
            if esperado[0] == 200:
                assert respuesta.json()['permisos'] == {'subir': esperado[1], 'quitar': esperado[2]}, (rol, tipo)
            subida = client.post(api(tipo, documento.pk), {'archivo': subido(f'{tipo}.pdf', PDF)})
            assert subida.status_code == (201 if esperado[1] else 403), (rol, tipo, subida.content)
            if esperado[1]:
                quitar = client.post(f'/adjuntos/api/quitar/{subida.json()["adjunto"]["id"]}/')
                assert quitar.status_code == (200 if esperado[2] else 403), (rol, tipo)

    def test_aislamiento_entre_empresas(self, client, empresa, empresa_b, admin, cobro):
        with company_context(empresa):
            adjunto = sv.adjuntar(empresa, admin, 'cobro', cobro, subido('t.pdf', PDF))
        dueno_b = helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno_b, empresa=empresa_b)
        assert client.get(api('cobro', cobro.pk)).status_code == 404
        assert client.post(api('cobro', cobro.pk), {'archivo': subido('t.pdf', PDF)}).status_code == 404
        assert client.get(f'/adjuntos/{adjunto.pk}/archivo/').status_code == 404
        assert client.post(f'/adjuntos/api/quitar/{adjunto.pk}/').status_code == 404
        assert client.get('/media/' + adjunto.archivo.name).status_code == 404
        assert leer(empresa, lambda: Adjunto.objects.get(pk=adjunto.pk)).vigente

    def test_plan_gratuito_y_vencido(self, client):
        gratuita = helpers.crear_empresa('GRATIS', plan=None)
        dueno = helpers.crear_usuario('dueno.gratis', gratuita, ROLE_OWNER)
        comprador = helpers.crear_cliente('comprador.gratis', gratuita, '0912345679', '0990000003')
        venta = factura_autorizada(gratuita, comprador, dueno, helpers.crear_producto(gratuita, 'G1'))
        compra = ayuda_compras.compra_antigua(gratuita, ayuda_compras.crear_proveedor(gratuita), '50.00')
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        bloqueo = client.get(api('venta', venta.pk))
        assert bloqueo.status_code == 403 and 'plan anual' in bloqueo.json()['error']   # el módulo de ventas exige plan
        assert client.get(api('compra', compra.pk)).json()['permisos'] == {'subir': True, 'quitar': True}   # Compras es gratis
        assert client.post(api('compra', compra.pk), {'archivo': subido('c.pdf', PDF)}).status_code == 201
        vencida = helpers.crear_empresa('VENCIDA', plan=None)
        helpers.dar_plan(vencida, inicio=timezone.now() - timedelta(days=400))
        dueno_v = helpers.crear_usuario('dueno.vencida', vencida, ROLE_OWNER)
        venta_v = factura_autorizada(vencida, helpers.crear_cliente('comprador.v', vencida, '0912345680', '0990000004'), dueno_v,
                                     helpers.crear_producto(vencida, 'V1'))
        helpers.iniciar_sesion(client, dueno_v, empresa=vencida)
        consulta = client.get(api('venta', venta_v.pk))
        assert consulta.status_code == 200 and consulta.json()['permisos'] == {'subir': False, 'quitar': False}
        assert 'venció' in consulta.json()['bloqueo']
        assert client.post(api('venta', venta_v.pk), {'archivo': subido('v.pdf', PDF)}).status_code == 403


# ---------------------------------------------------------------- comprobante junto con el formulario

class TestFormularios:

    def test_cobro_con_comprobante(self, client, empresa, admin, comprador, producto):
        venta = factura_autorizada(empresa, comprador, admin, producto, credito=True, fecha=HOY - timedelta(days=2))
        cuenta = cxc_de(venta)
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        datos = {'action': 'add', 'ctas_collect': cuenta.pk, 'date_joined': HOY.isoformat(), 'valor': '5.00', 'medio_pago': 'transferencia',
                 'referencia': 'TRX-1', 'description': 'Abono', 'comprobante': subido('t.pdf', PDF), 'comprobante_clase': ''}
        assert client.post('/pos/ctas/collect/add/', datos).json() == {}
        abono = leer(empresa, lambda: PaymentsCtaCollect.objects.get(tipo='cobro'))
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert (adjunto.documento_tipo, adjunto.documento_id, adjunto.clase, adjunto.referencia, adjunto.fecha, adjunto.importe) == (
            'cobro', abono.pk, 'transferencia', 'TRX-1', HOY, Decimal('5.00'))
        datos.update(comprobante=subido('nota.txt', b'hola'), comprobante_clase='deposito')
        respuesta = client.post('/pos/ctas/collect/add/', datos).json()
        assert 'Solo se admiten' in respuesta['error']
        assert leer(empresa, lambda: (PaymentsCtaCollect.objects.filter(tipo='cobro').count(), Adjunto.objects.count())) == (1, 1)   # nada nuevo
        datos.update(comprobante=subido('foto.jpg', imagen('JPEG')), comprobante_clase='deposito')
        assert client.post('/pos/ctas/collect/add/', datos).json() == {}
        assert leer(empresa, lambda: Adjunto.objects.order_by('id').last()).clase == 'deposito'
        pagina = client.get('/pos/ctas/collect/add/')
        assert b'name="comprobante"' in pagina.content and b'comprobante_clase' in pagina.content

    def test_pago_con_comprobante(self, client, empresa, admin):
        compra = ayuda_compras.compra_antigua(empresa, ayuda_compras.crear_proveedor(empresa), '100.00', credito=True, fecha=HOY - timedelta(days=5))
        deuda = leer(empresa, lambda: DebtsPay.objects.get(purchase=compra))
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        datos = {'action': 'add', 'debts_pay': deuda.pk, 'date_joined': HOY.isoformat(), 'valor': '40.00', 'medio_pago': 'cheque', 'referencia': 'CH-1',
                 'description': 'Pago parcial', 'comprobante': subido('cheque.png', imagen('PNG'))}
        assert client.post('/pos/debts/pay/add/', datos).json() == {}
        pago = leer(empresa, lambda: PaymentsDebtsPay.objects.get())
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert (adjunto.documento_tipo, adjunto.documento_id, adjunto.clase, adjunto.referencia, adjunto.importe) == ('pago', pago.pk, 'cheque', 'CH-1', Decimal('40.00'))
        datos['comprobante'] = subido('nota.txt', b'hola')
        assert 'Solo se admiten' in client.post('/pos/debts/pay/add/', datos).json()['error']
        assert leer(empresa, lambda: PaymentsDebtsPay.objects.count()) == 1

    def test_gasto_con_comprobante(self, client, empresa, admin):
        tipo = ayuda_compras.crear_tipo_gasto(empresa, 'VARIOS')
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        datos = {'action': 'add', 'type_expense': tipo.pk, 'description': 'Taxi', 'date_joined': HOY.isoformat(), 'valor': '8.50',
                 'medio_pago': 'transferencia', 'referencia': 'T-1', 'comprobante': subido('t.pdf', PDF)}
        assert client.post('/pos/expenses/add/', datos).json() == {}
        gasto = leer(empresa, lambda: Expenses.objects.get())
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert (adjunto.documento_tipo, adjunto.documento_id, adjunto.clase, adjunto.importe) == ('gasto', gasto.pk, 'transferencia', Decimal('8.50'))
        datos['comprobante'] = subido('nota.txt', b'hola')
        assert 'Solo se admiten' in client.post('/pos/expenses/add/', datos).json()['error']
        assert leer(empresa, lambda: Expenses.objects.count()) == 1   # el gasto no se registró
        del datos['comprobante']
        assert client.post('/pos/expenses/add/', datos).json() == {}   # sin archivo, como siempre
        assert leer(empresa, lambda: (Expenses.objects.count(), Adjunto.objects.count())) == (2, 1)


# ---------------------------------------------------------------- resumen del mes, ZIP y página

class TestMes:

    def test_resumen_y_zip(self, empresa, admin, venta_contado, cobro, gasto, pago):
        with company_context(empresa):
            sv.adjuntar(empresa, admin, 'cobro', cobro, subido('c.pdf', PDF), referencia='TRX-77', importe='10')
            en_efectivo = Expenses.objects.create(type_expense=gasto.type_expense, description='Parqueo', valor=Decimal('1.00'), medio_pago='efectivo')
            resumen = sv.resumen_mes(MES)
            filas = {(f['tipo'], f['id']): f for f in resumen['filas']}
            assert filas[('venta', venta_contado.pk)]['falta'] is True
            assert filas[('cobro', cobro.pk)]['falta'] is False and filas[('cobro', cobro.pk)]['adjuntos'][0]['referencia'] == 'TRX-77'
            assert filas[('gasto', gasto.pk)]['falta'] is True and filas[('pago', pago.pk)]['falta'] is True
            assert filas[('gasto', en_efectivo.pk)]['requiere'] is False and filas[('gasto', en_efectivo.pk)]['falta'] is False
            venta_credito = cobro.ctas_collect.sale
            assert filas[('venta', venta_credito.pk)]['requiere'] is False   # a crédito: el comprobante va en el cobro
            compra = pago.debts_pay.purchase
            assert filas[('compra', compra.pk)]['requiere'] is False   # compra antigua a crédito sin forma de pago: no se exige
            assert {k: v for k, v in resumen['totales'].items() if k != 'bytes_texto'} == {
                'documentos': 7, 'con_comprobante': 1, 'sin_comprobante': 3, 'adjuntos': 1, 'bytes': len(PDF)}
            assert [f['id'] for f in resumen['faltantes']] == [venta_contado.pk, gasto.pk, pago.pk]
            contenido = sv.zip_mes(MES)
        with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
            nombres = zf.namelist()
            [archivo] = [n for n in nombres if n.endswith('.pdf')]
            assert archivo.startswith(f'{MES:%Y-%m}/cobros/') and archivo.endswith('_1.pdf') and zf.read(archivo) == PDF
            indice = zf.read(f'{MES:%Y-%m}/indice.csv').decode('utf-8-sig').splitlines()
        assert indice[0].startswith('tipo;documento;tercero;')
        assert sum('SIN COMPROBANTE' in linea for linea in indice) == 3
        assert any('TRX-77' in linea and archivo in linea for linea in indice)

    def test_mes_sin_nada_y_mes_invalido(self, empresa):
        with company_context(empresa):
            resumen = sv.resumen_mes(MES.replace(year=2020, month=1))
            assert resumen['filas'] == [] and resumen['totales']['documentos'] == 0
            with zipfile.ZipFile(io.BytesIO(sv.zip_mes(MES.replace(year=2020, month=1)))) as zf:
                assert zf.namelist() == ['2020-01/indice.csv']
        with pytest.raises(ValueError):
            sv.primer_dia('2026-13-01')
        assert sv.primer_dia(' 2026-02 ') == MES.replace(year=2026, month=2)

    def test_pagina_y_zip_por_la_web(self, client, empresa, admin, venta_contado):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        pagina = client.get('/adjuntos/')
        assert pagina.status_code == 200
        html = pagina.content.decode()
        assert 'Pendientes de comprobante' in html and venta_contado.voucher_number_full in html and 'fpAdjuntosModal' in html
        assert f'data-adjuntos-tipo="venta" data-adjuntos-id="{venta_contado.pk}"' in html
        assert 'No hay facturas, compras, gastos' in client.get('/adjuntos/?mes=2020-01').content.decode()
        assert client.get('/adjuntos/?mes=2026-13').status_code == 200   # mes inválido: el actual
        zip_ = client.get(f'/adjuntos/zip/?mes={MES:%Y-%m}')
        assert zip_.status_code == 200 and zip_['Content-Type'] == 'application/zip' and f'comprobantes-de-pago-{MES:%Y-%m}.zip' in zip_['Content-Disposition']
        assert client.get('/adjuntos/zip/?mes=2026-13').status_code == 404

    @pytest.mark.parametrize('rol, estado', [(ROLE_ACCOUNTANT, 200), (ROLE_READONLY, 200), (ROLE_SELLER, 302), (ROLE_CLIENT, 302)])
    def test_pagina_por_rol(self, client, empresa, rol, estado):
        usuario = helpers.crear_usuario(f'pagina.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        assert client.get('/adjuntos/').status_code == estado
        assert client.get('/adjuntos/zip/').status_code == estado


# ---------------------------------------------------------------- menú y roles

def test_modulo_del_menu_y_roles():
    modulo = Module.objects.get(url='/adjuntos/')
    assert (modulo.name, modulo.icon, modulo.module_type.name, modulo.orden) == ('Comprobantes de pago', 'fas fa-paperclip', 'Administrativo', 4)
    todos = {'view_adjunto', 'add_adjunto', 'delete_adjunto'}
    assert set(modulo.permissions.values_list('codename', flat=True)) == todos

    def de(rol):
        grupo = Group.objects.get(name=rol)
        return (grupo.groupmodule_set.filter(module=modulo).exists(),
                set(grupo.permissions.filter(content_type__app_label='adjuntos').values_list('codename', flat=True)))
    assert de(ROLE_OWNER) == de(ROLE_ADMIN) == de(ROLE_ACCOUNTANT) == (True, todos)
    assert de(ROLE_READONLY) == (True, {'view_adjunto'})
    assert de(ROLE_SELLER) == de(ROLE_CLIENT) == (False, set())
    # El Contador no gana ninguna otra escritura por el cambio de roles.py.
    contador = Group.objects.get(name=ROLE_ACCOUNTANT)
    escritura = set(contador.permissions.filter(codename__regex=r'^(add|change|delete|adjust)_').values_list('codename', flat=True))
    assert escritura == {'add_adjunto', 'delete_adjunto'}
