"""Captura rápida de gastos (core/adjuntos/capturas.py): recibo y/o nota guardados ahora y completados después.

Guardar sin importe ni categoría y sin efectos contables; idempotencia por clave; permisos por rol (el Vendedor solo ve lo
suyo); aislamiento entre empresas y archivo privado; completar como gasto o como compra y vincular a un documento existente
reutilizando el archivo (sin copiarlo) y sin duplicar; una segunda conversión no crea nada; borrar el documento devuelve el
recibo a pendiente; nota de respaldo en documentos y formularios; consulta mensual, ZIP y menú."""
import io
import json
import os
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.adjuntos import capturas as cp, servicios as sv
from core.adjuntos.models import Adjunto, Captura
from core.pos import compras, cuentas_por_pagar
from core.pos.models import DebtsPay, Expenses, PaymentsDebtsPay, Purchase
from core.security.models import Module
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import peticion

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
MES = HOY.replace(day=1)
PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
OTRO_PDF = b'%PDF-1.4\n% otro recibo\n%%EOF\n'
API = '/adjuntos/api/capturas/'


def subido(nombre='recibo.pdf', contenido=PDF):
    return SimpleUploadedFile(nombre, contenido, content_type='application/octet-stream')


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


def contables(empresa):
    """Lo que una captura pendiente nunca debe tocar."""
    return leer(empresa, lambda: (Expenses.objects.count(), Purchase.objects.count(), DebtsPay.objects.count(),
                                  PaymentsDebtsPay.objects.count()))


def guardar(client, archivo=None, nota='', clave=None):
    datos = {'clave': clave or cp.clave_sugerida(), 'nota': nota}
    if archivo is not None:
        datos['archivo'] = archivo
    return client.post(API, datos)


def datos_gasto(tipo, **cambios):
    datos = {'type_expense': tipo.pk, 'date_joined': HOY.isoformat(), 'valor': '8.50', 'medio_pago': 'transferencia',
             'referencia': 'T-55', 'description': 'Taxi al banco'}
    datos.update(cambios)
    return datos


def archivos_en(captura):
    carpeta = os.path.dirname(captura.archivo.storage.path(captura.archivo.name))
    return sorted(os.listdir(carpeta))


@pytest.fixture
def tipo(empresa):
    return ayuda_compras.crear_tipo_gasto(empresa, 'MOVILIZACIÓN')


@pytest.fixture
def entrar(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


@pytest.fixture
def gasto(empresa, tipo):
    with company_context(empresa):
        return Expenses.objects.create(type_expense=tipo, description='Parqueo', valor=Decimal('2.00'), medio_pago='transferencia',
                                       referencia='P-1', date_joined=HOY)


@pytest.fixture
def pago(empresa, admin):
    proveedor = ayuda_compras.crear_proveedor(empresa)
    compra = ayuda_compras.compra_antigua(empresa, proveedor, '100.00', credito=True, fecha=MES)
    with company_context(empresa):
        deuda = DebtsPay.objects.get(purchase=compra)
        return cuentas_por_pagar.registrar_pago(deuda.pk, admin, fecha=HOY, valor='40.00', medio_pago='cheque', referencia='CH-5')


# ---------------------------------------------------------------- guardar

class TestGuardar:

    def test_archivo_nota_o_ambos_sin_efectos_contables(self, entrar, empresa, admin):
        antes = contables(empresa)
        solo_archivo = guardar(entrar, subido())
        solo_nota = guardar(entrar, nota='  Taxi   al banco, pagado por Ana ')
        ambos = guardar(entrar, subido('foto.pdf', OTRO_PDF), nota='Almuerzo con cliente')
        assert [r.status_code for r in (solo_archivo, solo_nota, ambos)] == [201, 201, 201]
        a, n, b = solo_archivo.json()['captura'], solo_nota.json()['captura'], ambos.json()['captura']
        assert a['estado'] == {'id': 'pendiente', 'name': 'Pendiente de completar'} and a['nota'] == '' and a['archivo']['nombre'] == 'recibo.pdf'
        assert n['archivo'] is None and n['nota'] == 'Taxi al banco, pagado por Ana'
        assert b['archivo']['extension'] == 'pdf' and b['nota'] == 'Almuerzo con cliente'
        assert a['creado_por'] == admin.username and a['documento'] is None and a['numero'] == f'C-{a["id"]}'
        guardada = leer(empresa, lambda: Captura.objects.get(pk=a['id']))
        assert guardada.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/comprobantes-pago/')
        assert guardada.company_id == empresa.pk and guardada.creado_por == admin
        assert contables(empresa) == antes and not leer(empresa, lambda: Adjunto.objects.exists())   # nada contable ni adjuntos
        assert leer(empresa, lambda: AuditLog.objects.filter(action='captura_registro', company=empresa).count()) == 3

    @pytest.mark.parametrize('datos, codigo', [
        ({}, 'respaldo_requerido'),
        ({'nota': '   '}, 'respaldo_requerido'),
        ({'nota': 'x' * 501}, 'nota_larga'),
        ({'archivo': SimpleUploadedFile('nota.txt', b'hola')}, 'archivo'),
        ({'nota': 'ok', 'clave': 'corta'}, 'clave'),
        ({'nota': 'ok', 'clave': 'con espacios 123'}, 'clave'),
    ])
    def test_rechazos_no_guardan_nada(self, entrar, empresa, datos, codigo):
        cuerpo = {'clave': cp.clave_sugerida(), **datos}
        respuesta = entrar.post(API, cuerpo)
        assert respuesta.status_code == 400 and respuesta.json()['codigo'] == codigo, respuesta.content
        assert not leer(empresa, lambda: Captura.objects.exists())

    def test_misma_clave_es_el_mismo_envio(self, entrar, empresa):
        clave = cp.clave_sugerida()
        primera = guardar(entrar, subido(), nota='Recibo', clave=clave)
        segunda = guardar(entrar, subido(), nota='Recibo', clave=clave)          # doble clic o reintento
        assert (primera.status_code, segunda.status_code) == (201, 200)
        assert segunda.json()['repetido'] is True and segunda.json()['captura']['id'] == primera.json()['captura']['id']
        assert primera.json()['clave_sugerida'] != clave                           # cada envío nuevo lleva otra clave
        captura = leer(empresa, lambda: Captura.objects.get())
        assert len(archivos_en(captura)) == 1                                       # el reintento no dejó otro archivo
        otra = guardar(entrar, subido('otro.pdf', OTRO_PDF), nota='Recibo', clave=clave)   # misma clave, otro contenido
        assert otra.status_code == 409 and otra.json()['codigo'] == 'clave_usada'
        assert leer(empresa, lambda: Captura.objects.count()) == 1 and len(archivos_en(captura)) == 1

    def test_archivo_privado_y_aislamiento(self, entrar, client, empresa, empresa_b):
        datos = guardar(entrar, subido(), nota='Privado').json()['captura']
        archivo = entrar.get(datos['archivo']['url'])
        assert archivo.status_code == 200 and b''.join(archivo.streaming_content) == PDF
        assert archivo['Cache-Control'] == 'private, no-store' and archivo['X-Content-Type-Options'] == 'nosniff'
        assert archivo['Content-Security-Policy'].startswith('sandbox')
        assert entrar.get(datos['archivo']['url_descarga'])['Content-Disposition'].startswith('attachment')
        captura = leer(empresa, lambda: Captura.objects.get(pk=datos['id']))
        assert entrar.get('/media/' + captura.archivo.name).status_code == 404    # privado/: nunca por /media/
        dueno_b = helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno_b, empresa=empresa_b)
        assert client.get(f'{API}{datos["id"]}/').status_code == 404
        assert client.get(datos['archivo']['url']).status_code == 404
        assert client.post(f'{API}{datos["id"]}/descartar/').status_code == 404
        assert client.get(API).json()['capturas'] == []
        assert leer(empresa, lambda: Captura.objects.get(pk=datos['id'])).estado == 'pendiente'


# ---------------------------------------------------------------- permisos por rol

class TestPermisos:

    @pytest.mark.parametrize('rol, esperado', [
        # (lista, guardar, completar la propia, ve la del propietario, vincular)
        (ROLE_OWNER, (200, 201, 201, True, True)),
        (ROLE_ADMIN, (200, 201, 201, True, True)),
        (ROLE_ACCOUNTANT, (200, 201, 201, True, True)),
        (ROLE_SELLER, (200, 201, 201, False, False)),    # solo lo que guardó; no ve gastos para vincular
        (ROLE_READONLY, (200, 403, None, True, False)),
        (ROLE_CLIENT, (403, 403, None, False, False)),
    ])
    def test_por_rol(self, client, empresa, admin, tipo, gasto, rol, esperado):
        de_otro = leer(empresa, lambda: cp.registrar(peticion(admin, empresa), clave=cp.clave_sugerida(), nota='Del propietario')[0])
        usuario = helpers.crear_usuario(f'cap.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        lista = client.get(API)
        assert lista.status_code == esperado[0], (rol, lista.content)
        propia = guardar(client, nota=f'Nota de {rol}')
        assert propia.status_code == esperado[1], (rol, propia.content)
        if esperado[1] == 201:
            pk = propia.json()['captura']['id']
            completar = client.post(f'{API}{pk}/completar/', datos_gasto(tipo))
            assert completar.status_code == esperado[2], (rol, completar.content)
        if esperado[0] == 200:
            ids = [c['id'] for c in client.get(API + '?estado=todas').json()['capturas']]
            assert (de_otro.pk in ids) is esperado[3], rol
            assert (client.get(f'{API}{de_otro.pk}/').status_code == 200) is esperado[3], rol
        vincular = client.post(f'{API}{de_otro.pk}/vincular/', {'tipo': 'gasto', 'documento_id': gasto.pk})
        assert (vincular.status_code == 201) is esperado[4], (rol, vincular.content)

    def test_capacidades_del_vendedor_y_de_consulta(self, client, empresa):
        vendedor = helpers.crear_usuario('cap.vendedor', empresa, ROLE_SELLER)
        helpers.iniciar_sesion(client, vendedor, empresa=empresa)
        capacidades = client.get(API).json()['capacidades']
        assert capacidades['registrar'] and capacidades['completar_gasto'] and not capacidades['ver_todas']
        assert capacidades['vincular'] == {'compra': False, 'gasto': False, 'pago': False} and not capacidades['registrar_compra']
        consulta = helpers.crear_usuario('cap.consulta', empresa, ROLE_READONLY)
        helpers.iniciar_sesion(client, consulta, empresa=empresa)
        capacidades = client.get(API).json()['capacidades']
        assert capacidades['ver_todas'] and not capacidades['registrar'] and not capacidades['completar_gasto']

    def test_plan_gratuito_guarda_pero_no_completa_como_gasto(self, client):
        gratuita = helpers.crear_empresa('GRATIS CAP', plan=None)
        dueno = helpers.crear_usuario('dueno.cap.gratis', gratuita, ROLE_OWNER)
        tipo = ayuda_compras.crear_tipo_gasto(gratuita, 'VARIOS')
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        captura = guardar(client, nota='Recibo con plan gratuito')
        assert captura.status_code == 201          # guardar no exige plan (como Compras)
        capacidades = captura.json()['captura']['capacidades']
        assert capacidades['completar_gasto'] is False and 'plan anual' in capacidades['bloqueos']['gasto']
        assert capacidades['registrar_compra'] is True
        respuesta = client.post(f'{API}{captura.json()["captura"]["id"]}/completar/', datos_gasto(tipo))
        assert respuesta.status_code == 403 and respuesta.json()['codigo'] == 'plan'
        assert leer(gratuita, Expenses.objects.count) == 0


# ---------------------------------------------------------------- completar y vincular

class TestCompletarYVincular:

    def test_completar_como_gasto_reutiliza_el_archivo(self, entrar, empresa, admin, tipo):
        datos = guardar(entrar, subido(), nota='Taxi al banco').json()['captura']
        captura = leer(empresa, lambda: Captura.objects.get(pk=datos['id']))
        en_disco = archivos_en(captura)
        detalle = entrar.get(f'{API}{captura.pk}/').json()
        assert detalle['sugerencias'] == {'date_joined': HOY.isoformat(), 'description': 'Taxi al banco'}
        assert {'id': tipo.pk, 'nombre': 'MOVILIZACIÓN'} in detalle['opciones']['categorias']
        respuesta = entrar.post(f'{API}{captura.pk}/completar/', datos_gasto(tipo))
        assert respuesta.status_code == 201, respuesta.content
        cuerpo = respuesta.json()
        gasto = leer(empresa, lambda: Expenses.objects.get())
        assert (gasto.type_expense_id, gasto.valor, gasto.medio_pago, gasto.referencia) == (tipo.pk, Decimal('8.50'), 'transferencia', 'T-55')
        assert cuerpo['gasto'] == {'id': gasto.pk, 'titulo': f'Gasto #{gasto.pk} · MOVILIZACIÓN'}
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert adjunto.archivo.name == captura.archivo.name and adjunto.captura_id == captura.pk   # mismo archivo, sin copia
        assert (adjunto.documento_tipo, adjunto.documento_id, adjunto.descripcion, adjunto.clase) == ('gasto', gasto.pk, 'Taxi al banco', 'recibo')
        assert (adjunto.importe, adjunto.fecha, adjunto.referencia, adjunto.subido_por) == (Decimal('8.50'), HOY, 'T-55', admin)
        assert archivos_en(captura) == en_disco
        captura.refresh_from_db()
        assert (captura.estado, captura.documento_tipo, captura.documento_id, captura.completado_por) == ('completada', 'gasto', gasto.pk, admin)
        assert cuerpo['captura']['documento']['titulo'] == f'Gasto #{gasto.pk} · MOVILIZACIÓN'
        with company_context(empresa):
            fila = next(f for f in sv.resumen_mes(MES)['filas'] if (f['tipo'], f['id']) == ('gasto', gasto.pk))
        assert fila['falta'] is False and fila['adjuntos'][0]['captura'] == captura.pk

    def test_segunda_conversion_no_crea_nada(self, entrar, empresa, tipo):
        pk = guardar(entrar, nota='Recibo de taxi').json()['captura']['id']
        assert entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo)).status_code == 201
        otra = entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo, valor='99.00'))   # otra pestaña o un reintento
        assert otra.status_code == 409 and otra.json()['codigo'] == 'captura_usada'
        assert 'ya se registró como Gasto #' in otra.json()['error'] and otra.json()['captura']['estado']['id'] == 'completada'
        assert leer(empresa, lambda: (Expenses.objects.count(), Adjunto.objects.count())) == (1, 1)

    @pytest.mark.parametrize('cambios, codigo, campo', [
        ({'type_expense': ''}, 'datos', 'type_expense'),
        ({'medio_pago': ''}, 'datos', 'medio_pago'),
        ({'medio_pago': 'cheque', 'referencia': ''}, 'datos', 'referencia'),
        ({'valor': '0'}, 'valor', 'valor'),
    ])
    def test_datos_invalidos_no_crean_gasto(self, entrar, empresa, tipo, cambios, codigo, campo):
        pk = guardar(entrar, nota='Recibo').json()['captura']['id']
        respuesta = entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo, **cambios))
        assert respuesta.status_code == 400 and respuesta.json()['codigo'] == codigo and campo in respuesta.json()['errores']
        assert leer(empresa, Expenses.objects.count) == 0 and leer(empresa, lambda: Captura.objects.get(pk=pk).estado) == 'pendiente'

    def test_vincular_sin_duplicar_el_archivo(self, entrar, empresa, gasto):
        with company_context(empresa):
            existente = sv.adjuntar(empresa, None, 'gasto', gasto, subido())         # el mismo PDF ya está en el gasto
        pk = guardar(entrar, subido(), nota='Es el mismo recibo').json()['captura']['id']
        respuesta = entrar.post(f'{API}{pk}/vincular/', {'tipo': 'gasto', 'documento_id': gasto.pk})
        assert respuesta.status_code == 201, respuesta.content
        cuerpo = respuesta.json()
        assert cuerpo['ya_adjunto']['id'] == existente.pk                             # no se duplica: se informa
        assert [a['nota'] for a in cuerpo['adjuntos']] == [True] and cuerpo['adjuntos'][0]['descripcion'] == 'Es el mismo recibo'
        assert cuerpo['captura']['estado']['id'] == 'vinculada' and cuerpo['captura']['documento']['id'] == gasto.pk
        assert leer(empresa, lambda: Adjunto.objects.filter(documento_tipo='gasto', documento_id=gasto.pk).count()) == 2

    def test_vincular_a_pago_y_errores(self, entrar, empresa, empresa_b, pago):
        pk = guardar(entrar, subido(), nota='Cheque entregado').json()['captura']['id']
        assert entrar.post(f'{API}{pk}/vincular/', {'tipo': 'venta', 'documento_id': 1}).json()['codigo'] == 'tipo'
        ajeno = helpers.crear_usuario('dueno.vb', empresa_b, ROLE_OWNER)
        tipo_b = ayuda_compras.crear_tipo_gasto(empresa_b, 'OTRA')
        gasto_b = leer(empresa_b, lambda: Expenses.objects.create(type_expense=tipo_b, valor=Decimal('1.00'), medio_pago='efectivo'))
        assert ajeno and entrar.post(f'{API}{pk}/vincular/', {'tipo': 'gasto', 'documento_id': gasto_b.pk}).status_code == 404
        assert leer(empresa, lambda: Captura.objects.get(pk=pk).estado) == 'pendiente'
        respuesta = entrar.post(f'{API}{pk}/vincular/', {'tipo': 'pago', 'documento_id': pago.pk})
        assert respuesta.status_code == 201 and respuesta.json()['adjuntos'][0]['captura'] == pk
        adjunto = leer(empresa, lambda: Adjunto.objects.get(documento_tipo='pago'))
        assert (adjunto.importe, adjunto.referencia, adjunto.descripcion) == (None, '', 'Cheque entregado')   # no se inventan datos
        assert leer(empresa, lambda: DebtsPay.objects.get(pk=pago.debts_pay_id).saldo) == Decimal('60.00')   # saldo intacto

    def test_buscar_documentos_para_vincular(self, entrar, gasto, pago):
        assert [d['id'] for d in entrar.get(f'{API}documentos/?tipo=gasto&q=parqueo').json()['documentos']] == [gasto.pk]
        assert [d['id'] for d in entrar.get(f'{API}documentos/?tipo=gasto&q=%23{gasto.pk}').json()['documentos']] == [gasto.pk]
        assert [d['id'] for d in entrar.get(f'{API}documentos/?tipo=pago').json()['documentos']] == [pago.pk]
        assert entrar.get(f'{API}documentos/?tipo=venta').json()['codigo'] == 'tipo'

    def test_descartar_y_corregir_nota(self, entrar, empresa, tipo):
        pk = guardar(entrar, subido(), nota='Primera nota').json()['captura']['id']
        corregida = entrar.post(f'{API}{pk}/nota/', {'nota': 'Nota corregida'})
        assert corregida.status_code == 200 and corregida.json()['captura']['nota'] == 'Nota corregida'
        assert entrar.post(f'{API}{pk}/nota/', {'nota': 'Nota corregida'}).json()['codigo'] == 'nada_que_cambiar'
        assert entrar.post(f'{API}{pk}/descartar/', {'motivo': 'x' * 301}).json()['codigo'] == 'motivo_largo'
        descartada = entrar.post(f'{API}{pk}/descartar/', {'motivo': 'Era personal'})
        assert descartada.status_code == 200 and descartada.json()['captura']['estado']['id'] == 'descartada'
        assert entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo)).json()['codigo'] == 'captura_usada'
        assert entrar.post(f'{API}{pk}/nota/', {'nota': 'otra'}).status_code == 409
        captura = leer(empresa, lambda: Captura.objects.get(pk=pk))
        assert captura.archivo.storage.exists(captura.archivo.name)                  # el archivo se conserva
        acciones = leer(empresa, lambda: list(AuditLog.objects.filter(company=empresa, action__startswith='captura_')
                                              .order_by('id').values_list('action', flat=True)))
        assert acciones == ['captura_registro', 'captura_nota', 'captura_descartada']
        assert leer(empresa, Expenses.objects.count) == 0

    def test_registrar_como_compra_desde_la_pantalla_de_compras(self, entrar, empresa, admin, tipo):
        proveedor = ayuda_compras.crear_proveedor(empresa)
        pk = guardar(entrar, subido(), nota='Factura del proveedor').json()['captura']['id']
        pantalla = entrar.get(f'/pos/purchase/add/?tipo=gasto&captura={pk}')
        assert pantalla.context['captura']['id'] == pk and f'name="captura" value="{pk}"' in pantalla.content.decode()
        datos = {**{k: v for k, v in ayuda_compras.datos_compra(proveedor).items() if v is not None}, 'action': 'add', 'captura': pk,
                 'lineas': json.dumps([ayuda_compras.linea_gasto('Mantenimiento', price='20.00', type_expense=tipo)])}
        respuesta = json.loads(entrar.post('/pos/purchase/add/', datos).content)
        assert 'error' not in respuesta, respuesta
        compra = leer(empresa, lambda: Purchase.objects.get(pk=respuesta['id']))
        adjunto = leer(empresa, lambda: Adjunto.objects.get(documento_tipo='compra'))
        captura = leer(empresa, lambda: Captura.objects.get(pk=pk))
        assert adjunto.documento_id == compra.pk and adjunto.archivo.name == captura.archivo.name
        assert (captura.estado, captura.documento_tipo, captura.documento_id) == ('completada', 'compra', compra.pk)
        datos['secuencial'] = '999001'
        otra = json.loads(entrar.post('/pos/purchase/add/', datos).content)              # la misma captura otra vez
        assert otra['codigo'] == 'captura_usada' and leer(empresa, Purchase.objects.count) == 1
        aviso = entrar.get(f'/pos/purchase/add/?tipo=gasto&captura={pk}')
        assert aviso.context['captura'] is None and 'ya se registró como Compra' in aviso.context['captura_aviso']


# ---------------------------------------------------------------- borrar el documento

class TestBorrarDocumento:

    def test_borrar_el_gasto_devuelve_el_recibo_a_pendiente(self, entrar, empresa, tipo):
        pk = guardar(entrar, subido(), nota='Taxi').json()['captura']['id']
        gasto_id = entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo)).json()['gasto']['id']
        assert json.loads(entrar.post(f'/pos/expenses/delete/{gasto_id}/').content) == {}
        captura = leer(empresa, lambda: Captura.objects.get(pk=pk))
        assert (captura.estado, captura.documento_tipo, captura.documento_id) == ('pendiente', '', None)
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert adjunto.eliminado_en is not None and adjunto.eliminado_motivo == f'Gasto #{gasto_id} eliminado'
        assert captura.archivo.storage.exists(captura.archivo.name)
        assert leer(empresa, lambda: AuditLog.objects.filter(action='captura_liberada').count()) == 1
        assert entrar.post(f'{API}{pk}/completar/', datos_gasto(tipo)).status_code == 201   # se puede volver a completar

    def test_borrar_el_pago_o_la_compra(self, entrar, empresa, admin, pago):
        pk = guardar(entrar, nota='Pago con cheque').json()['captura']['id']
        assert entrar.post(f'{API}{pk}/vincular/', {'tipo': 'pago', 'documento_id': pago.pk}).status_code == 201
        with company_context(empresa):
            cuentas_por_pagar.eliminar_pago(peticion(admin, empresa), pago.pk)
        assert leer(empresa, lambda: Captura.objects.get(pk=pk).estado) == 'pendiente'
        compra = ayuda_compras.compra_antigua(empresa, ayuda_compras.crear_proveedor(empresa), '30.00', fecha=MES)
        assert entrar.post(f'{API}{pk}/vincular/', {'tipo': 'compra', 'documento_id': compra.pk}).status_code == 201
        with company_context(empresa):
            compras.eliminar_compra(compra, admin, request=peticion(admin, empresa))
        assert leer(empresa, lambda: Captura.objects.get(pk=pk).estado) == 'pendiente'


# ---------------------------------------------------------------- nota de respaldo en documentos y formularios

class TestNotaDeRespaldo:

    def test_nota_sin_archivo_en_un_documento(self, entrar, empresa, gasto):
        url = f'/adjuntos/api/gasto/{gasto.pk}/'
        respuesta = entrar.post(url, {'nota': 'Pagado en ventanilla; el banco no entrega comprobante'})
        assert respuesta.status_code == 201, respuesta.content
        nota = respuesta.json()['adjunto']
        assert nota['nota'] is True and nota['url'] == '' and nota['clase'] == {'id': 'nota', 'name': 'Nota de respaldo'}
        assert entrar.post(url, {'nota': 'Pagado en ventanilla; el banco no entrega comprobante'}).json()['codigo'] == 'duplicado'
        assert entrar.get(f'/adjuntos/{nota["id"]}/archivo/').status_code == 404
        assert 'nota' not in [c['id'] for c in entrar.get(url).json()['clases']]     # la nota no es una clase de archivo
        with company_context(empresa):
            resumen = sv.resumen_mes(MES)
        fila = next(f for f in resumen['filas'] if (f['tipo'], f['id']) == ('gasto', gasto.pk))
        assert (fila['falta'], fila['con_nota']) == (False, True) and resumen['totales']['notas'] == 1
        zip_ = entrar.get(f'/adjuntos/zip/?mes={MES:%Y-%m}')
        assert zip_.status_code == 200
        with zipfile.ZipFile(io.BytesIO(zip_.content)) as zf:
            assert zf.namelist() == [f'{MES:%Y-%m}/indice.csv']                      # una nota no es un archivo del ZIP
            indice = zf.read(f'{MES:%Y-%m}/indice.csv').decode('utf-8-sig')
        assert ';adjuntos;nota;' in indice and 'banco no entrega' in indice

    def test_nota_de_respaldo_al_registrar_el_gasto(self, entrar, empresa, tipo):
        datos = {'action': 'add', **datos_gasto(tipo, description='Taxi'), 'nota_respaldo': 'Sin recibo: el taxista no lo dio'}
        assert json.loads(entrar.post('/pos/expenses/add/', datos).content) == {}
        con_nota = leer(empresa, lambda: Expenses.objects.get())
        adjunto = leer(empresa, lambda: Adjunto.objects.get())
        assert (adjunto.documento_id, adjunto.clase, adjunto.descripcion, bool(adjunto.archivo)) == (
            con_nota.pk, 'nota', 'Sin recibo: el taxista no lo dio', False)
        del datos['nota_respaldo']
        assert json.loads(entrar.post('/pos/expenses/add/', datos).content) == {}
        assert leer(empresa, Adjunto.objects.count) == 1           # la descripción del gasto no se convierte en respaldo


# ---------------------------------------------------------------- consulta mensual, ZIP, menú y roles

class TestMes:

    def test_recibos_por_completar_en_la_consulta_y_el_zip(self, entrar, empresa, gasto):
        con_archivo = guardar(entrar, subido(), nota='Peaje').json()['captura']
        solo_nota = guardar(entrar, nota='Almuerzo con proveedor').json()['captura']
        anterior = guardar(entrar, nota='Del mes pasado').json()['captura']
        with company_context(empresa):
            Captura.objects.filter(pk=anterior['id']).update(creado_en=timezone.now() - timedelta(days=40))
            resumen = sv.resumen_mes(MES)
        assert resumen['totales']['documentos'] == 1                                  # los recibos no son documentos
        assert (resumen['totales']['capturas_del_mes'], resumen['totales']['capturas_pendientes']) == (2, 3)
        filas = {f['id']: f for f in resumen['capturas']}
        assert set(filas) == {con_archivo['id'], solo_nota['id']}
        assert filas[con_archivo['id']]['pendiente_completar'] is True and filas[con_archivo['id']]['falta'] is False
        assert filas[solo_nota['id']]['adjuntos'][0]['nota'] is True and filas[solo_nota['id']]['adjuntos'][0]['url'] == ''
        zip_ = entrar.get(f'/adjuntos/zip/?mes={MES:%Y-%m}')
        with zipfile.ZipFile(io.BytesIO(zip_.content)) as zf:
            assert f'{MES:%Y-%m}/recibos-por-completar/C-{con_archivo["id"]}.pdf' in zf.namelist()
            indice = zf.read(f'{MES:%Y-%m}/indice.csv').decode('utf-8-sig')
        assert indice.count('Recibo por completar') == 2 and 'Almuerzo con proveedor' in indice
        pagina = entrar.get('/adjuntos/').content.decode()
        assert 'Recibos y notas por completar' in pagina and f'C-{con_archivo["id"]}' in pagina
        assert f'data-adjuntos-tipo="captura"' not in pagina

    def test_pantalla_funcional(self, entrar, client, empresa):
        guardar(entrar, nota='Recibo de prueba')
        pagina = entrar.get('/adjuntos/capturas/')
        assert pagina.status_code == 200 and 'Recibo de prueba' in pagina.content.decode()
        assert 'name="clave"' in pagina.content.decode() and pagina.context['capacidades']['registrar']
        cliente = helpers.crear_usuario('cap.cliente', empresa, ROLE_CLIENT)
        helpers.iniciar_sesion(client, cliente, empresa=empresa)
        assert client.get('/adjuntos/capturas/').status_code == 302


def test_modulo_del_menu_y_roles():
    modulo = Module.objects.get(url='/adjuntos/capturas/')
    assert (modulo.name, modulo.icon, modulo.module_type.name, modulo.orden) == ('Recibos por completar', 'fas fa-camera', 'Compras y gastos', 6)
    todos = {'view_captura', 'add_captura', 'change_captura'}
    assert set(modulo.permissions.values_list('codename', flat=True)) == todos

    def de(rol):
        grupo = Group.objects.get(name=rol)
        return (grupo.groupmodule_set.filter(module=modulo).exists(),
                set(grupo.permissions.filter(codename__in=todos).values_list('codename', flat=True)))
    assert de(ROLE_OWNER) == de(ROLE_ADMIN) == de(ROLE_ACCOUNTANT) == de(ROLE_SELLER) == (True, todos)
    assert de(ROLE_READONLY) == (True, {'view_captura'})
    assert de(ROLE_CLIENT) == (False, set())
    vendedor = Group.objects.get(name=ROLE_SELLER)
    assert not vendedor.permissions.filter(codename__in=('add_expenses', 'view_expenses', 'view_adjunto')).exists()
