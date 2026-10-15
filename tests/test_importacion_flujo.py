"""Importación — flujo completo con base de datos: lote, archivos privados con deduplicación, idempotencia por clave,
clasificación, PDF con recuperación del XML en el SRI simulado, verificación, revisión, vinculación, propuesta contable,
aislamiento entre empresas, API JSON, permisos y organización del menú. Documentos ficticios."""
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.importacion import servicios as sv, sri_autorizacion
from core.importacion.models import ArchivoImportado, DocumentoImportado, EntradaLote, ReglaImportacion
from core.pos import emision
from core.pos.models import Provider, Purchase, Receipt, Sale
from core.security.models import Module, ModuleType
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context, platform_scope
from core.tenancy.models import Membership, ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from tests import fabricas_sri as f, helpers
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = pytest.mark.django_db
RUC_EMPRESA = f.RUC_RECEPTOR


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


@pytest.fixture(autouse=True)
def archivos_temporales(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)


@pytest.fixture
def sri(monkeypatch):
    simulado = SRISimulado()
    monkeypatch.setattr(emision, '_cliente', simulado)
    return simulado


@pytest.fixture
def empresa():
    return helpers.crear_empresa('RECEPTORA', ruc=RUC_EMPRESA)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.importa', empresa, ROLE_OWNER)


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


def importar(empresa, usuario, *archivos):
    with company_context(empresa):
        return sv.crear_lote(empresa, usuario, [(n, d.encode() if isinstance(d, str) else d) for n, d in archivos])


def recibida(**cambios):
    return f.autorizacion(f.factura(**cambios))


class TestImportacion:

    def test_xml_recibido_privado_clasificado_sin_tocar_cupo_ni_secuencias(self, empresa, dueno, sri):
        helpers.configurar_facturacion(empresa)
        secuencias = leer(empresa, lambda: list(Receipt.objects.values_list('pk', 'sequence')))
        usados = SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used
        lote = importar(empresa, dueno, ('factura.xml', recibida()))
        with company_context(empresa):
            entrada = EntradaLote.objects.get(lote=lote)
            documento = DocumentoImportado.objects.get()
            assert entrada.estado == 'procesado' and lote.estado == 'terminado'
            assert documento.clasificacion == 'recibido' and documento.estado_verificacion == 'declarada_en_archivo'
            assert documento.importe_total == Decimal('135.00') and documento.impuestos.count() == 2
            assert documento.archivo_xml.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/importados/')
            assert documento.archivo_xml.sha256 == entrada.archivo.sha256 and len(documento.archivo_xml.sha256) == 64
            assert list(Receipt.objects.values_list('pk', 'sequence')) == secuencias          # no cambia numeraciones
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == usados   # no usa el cupo

    def test_duplicados_por_hash_y_por_clave(self, empresa, dueno, sri):
        xml = recibida()
        lote = importar(empresa, dueno, ('a.xml', xml), ('copia.xml', xml))
        otro = importar(empresa, dueno, ('escapado.xml', f.autorizacion(f.factura(), modo='escapado')))
        with company_context(empresa):
            assert [e.estado for e in EntradaLote.objects.filter(lote=lote)] == ['procesado', 'duplicado']
            assert EntradaLote.objects.get(lote=otro).estado == 'duplicado'
            assert ArchivoImportado.objects.count() == 2 and DocumentoImportado.objects.count() == 1
            assert DocumentoImportado.objects.get().eventos.filter(tipo='duplicado').count() == 2

    @pytest.mark.parametrize('emisor, receptor, clasificacion', [
        (RUC_EMPRESA, '0990000009001', 'emitido'),
        ('0990000001001', '0990000009001', 'ajeno'),
        (RUC_EMPRESA, RUC_EMPRESA, 'revision_manual'),
        ('0990000001001', RUC_EMPRESA[:10], 'ajeno'),          # una cédula igual a los 10 primeros dígitos no es la empresa
    ])
    def test_clasificacion_por_coincidencia_exacta(self, empresa, dueno, sri, emisor, receptor, clasificacion):
        tipo = '05' if len(receptor) == 10 else '04'
        importar(empresa, dueno, ('f.xml', f.autorizacion(f.factura(ruc=emisor, receptor_id=receptor, receptor_tipo=tipo))))
        assert leer(empresa, lambda: DocumentoImportado.objects.get().clasificacion) == clasificacion

    def test_lote_con_fallos_parciales(self, empresa, dueno, sri):
        lote = importar(empresa, dueno, ('bien.xml', recibida()), ('roto.xml', '<autorizacion><estado>'),
                        ('notas.txt', 'hola'), ('ride.pdf', f.pdf()), ('nc.xml', f.autorizacion(f.factura(cod_doc='04'))))
        with company_context(empresa):
            assert [e.estado for e in lote.entradas.order_by('orden')] == ['procesado', 'rechazado', 'rechazado', 'en_cola', 'rechazado']
            sv.procesar_lote(lote, dueno)
            entradas = list(lote.entradas.order_by('orden'))
            lote.refresh_from_db()
        assert entradas[3].estado == 'pendiente_clave' and lote.estado == 'con_errores'
        assert entradas[1].errores[0]['codigo'] == 'xml_malformado' and entradas[2].errores[0]['codigo'] == 'tipo_archivo'
        assert entradas[4].errores[0]['codigo'] == 'tipo_no_soportado'

    def test_limites_del_lote(self, empresa, dueno):
        with pytest.raises(sv.ErrorImportacion, match='al menos un archivo'):
            importar(empresa, dueno)
        with pytest.raises(sv.ErrorImportacion, match='hasta'):
            importar(empresa, dueno, *[(f'{i}.xml', '<a/>') for i in range(51)])


class TestPdfYSri:

    def test_pdf_con_clave_recupera_el_xml_autorizado(self, empresa, dueno, sri):
        sri.comprobantes[f.clave()] = f.factura()
        lote = importar(empresa, dueno, ('ride.pdf', f.pdf(('barras', f.clave()))))
        with company_context(empresa):
            sv.procesar_lote(lote, dueno)
            entrada = lote.entradas.get()
            documento = DocumentoImportado.objects.get()
            assert entrada.estado == 'procesado' and documento.origen == 'pdf' and documento.estado_procesamiento == 'procesado'
            assert documento.estado_verificacion == 'verificada_sri' and documento.archivo_xml.origen == 'sri' and documento.archivo_pdf
            assert documento.importe_total == Decimal('135.00')

    def test_sri_no_disponible_deja_pendiente_y_se_reintenta_con_la_clave(self, empresa, dueno, sri, web):
        sri.caido = True
        lote = importar(empresa, dueno, ('ride.pdf', f.pdf(('qr', f.clave()))))
        with company_context(empresa):
            sv.procesar_lote(lote, dueno)
            entrada = lote.entradas.get()
            documento = DocumentoImportado.objects.get()
        assert entrada.estado == 'pendiente_xml' and documento.estado_procesamiento == 'pendiente_xml'
        assert documento.estado_verificacion == 'sri_no_disponible' and documento.importe_total == Decimal('0.00')   # no se inventan datos
        sri.caido, sri.comprobantes[f.clave()] = False, f.factura()
        respuesta = web.post(f'/importacion/api/entradas/{entrada.pk}/clave/', {'clave': f.clave()})
        assert respuesta.status_code == 200 and respuesta.json()['entrada']['estado']['id'] == 'procesado'
        assert leer(empresa, lambda: DocumentoImportado.objects.get().estado_verificacion) == 'verificada_sri'

    def test_pdf_sin_clave_admite_ingreso_manual(self, empresa, dueno, sri):
        sri.comprobantes[f.clave()] = f.factura()
        lote = importar(empresa, dueno, ('ride.pdf', f.pdf()))
        with company_context(empresa):
            sv.procesar_lote(lote, dueno)
            entrada = lote.entradas.get()
            with pytest.raises(sv.ErrorImportacion, match='dígito verificador'):
                sv.usar_clave_manual(entrada, dueno, f.clave()[:48] + '0' if f.clave()[48] != '0' else f.clave()[:48] + '1')
            sv.usar_clave_manual(entrada, dueno, f.clave())
            assert lote.entradas.get().estado == 'procesado' and DocumentoImportado.objects.get().origen == 'manual'

    def test_clave_de_tipo_no_soportado(self, empresa, dueno, sri):
        lote = importar(empresa, dueno, ('nd.pdf', f.pdf(('barras', f.clave(cod_doc='05')))))
        with company_context(empresa):
            sv.procesar_lote(lote, dueno)
            entrada = lote.entradas.get()
        assert entrada.estado == 'rechazado' and 'tipo no soportado' in entrada.errores[-1]['texto']


class TestVerificacionYRevision:

    @pytest.fixture
    def documento(self, empresa, dueno, sri):
        importar(empresa, dueno, ('f.xml', recibida()))
        return leer(empresa, lambda: DocumentoImportado.objects.get())

    def verificar(self, empresa, documento, dueno):
        with company_context(empresa):
            return sv.verificar_en_sri(documento, dueno)

    def test_verificacion_coincide(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()] = f.factura()
        assert self.verificar(empresa, documento, dueno).estado_verificacion == 'verificada_sri'

    def test_archivo_alterado_difiere_del_sri(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()] = f.factura(importe='1350.00', pagos=(('20', '1350.00'),))
        documento = self.verificar(empresa, documento, dueno)
        assert documento.estado_verificacion == 'discrepancia_sri' and documento.clasificacion == 'revision_manual'
        with company_context(empresa), pytest.raises(sv.ErrorImportacion):
            sv.revisar(documento, dueno, 'aprobar', {'confirmar_sin_verificar': True})

    def test_no_existe_o_no_autorizado_en_el_sri(self, empresa, dueno, documento, sri):
        assert self.verificar(empresa, documento, dueno).estado_verificacion == 'no_encontrada_sri'
        sri.comprobantes[f.clave()], sri.estado = f.factura(), 'NO AUTORIZADO'
        assert self.verificar(empresa, documento, dueno).estado_verificacion == 'no_autorizada_sri'

    def test_aprobar_exige_verificacion_y_genera_propuesta_que_cuadra(self, empresa, dueno, documento, sri):
        with company_context(empresa):
            regla = sv.reglas_de(empresa)
            ReglaImportacion.objects.filter(pk=regla.pk).update(cuenta_gasto='5.1.01', cuenta_iva_compras='1.1.05', cuenta_proveedores='2.1.01')
            with pytest.raises(sv.ErrorImportacion, match='no está verificado'):
                sv.revisar(documento, dueno, 'aprobar')
            documento = sv.revisar(documento, dueno, 'aprobar', {'confirmar_sin_verificar': True})
        propuesta = documento.propuesta_contable
        assert documento.estado_revision == 'aprobado' and documento.estado_contable == 'propuesta'
        assert propuesta['contabilizado'] is False and propuesta['cuadra'] and propuesta['debe'] == propuesta['haber'] == '135.00'
        assert [(l['cuenta'], l['debe'], l['haber']) for l in propuesta['lineas']] == [
            ('5.1.01', '120.00', '0.00'), ('1.1.05', '15.00', '0.00'), ('2.1.01', '0.00', '135.00')]
        with company_context(empresa), pytest.raises(sv.ErrorImportacion, match='Reábrelo'):
            sv.revisar(documento, dueno, 'aprobar', {'confirmar_sin_verificar': True})

    def test_descartar_reabrir_y_crear_proveedor(self, empresa, dueno, documento, sri):
        with company_context(empresa):
            sv.revisar(documento, dueno, 'descartar', {'motivo': 'Duplicado de otro sistema'})
            documento = sv.revisar(documento, dueno, 'reabrir')
            assert documento.estado_revision == 'pendiente'
            with pytest.raises(sv.ErrorImportacion, match='celular y su correo'):
                sv.revisar(documento, dueno, 'crear_proveedor', {})
            documento = sv.revisar(documento, dueno, 'crear_proveedor', {'mobile': '0990001111', 'email': 'prov@example.com'})
            assert documento.proveedor.ruc == f.RUC_EMISOR and Provider.objects.count() == 1

    def test_vincular_con_la_compra_existente(self, empresa, dueno, documento, sri):
        with company_context(empresa):
            proveedor = Provider.objects.create(name='PROVEEDOR FICTICIO', ruc=f.RUC_EMISOR, mobile='0990002222', email='p@example.com')
            otro = Provider.objects.create(name='OTRO', ruc='0990000005001', mobile='0990003333', email='o@example.com')
            compra = Purchase.objects.create(number='271', provider=proveedor, subtotal=Decimal('120.00'), date_joined=date(2026, 10, 11))
            ajena = Purchase.objects.create(number='9', provider=otro, subtotal=Decimal('120.00'))
            candidatos = sv.candidatos_conciliacion(DocumentoImportado.objects.get())
            assert candidatos[0]['id'] == compra.pk and candidatos[0]['exacto'] and ajena.pk not in [c['id'] for c in candidatos]
            with pytest.raises(sv.ErrorImportacion, match='otro proveedor'):
                sv.revisar(documento, dueno, 'vincular_compra', {'id': ajena.pk, 'confirmar_sin_verificar': True})
            documento = sv.revisar(documento, dueno, 'vincular_compra', {'id': compra.pk, 'confirmar_sin_verificar': True})
        assert documento.estado_revision == 'vinculado' and documento.compra_id == compra.pk
        assert leer(empresa, lambda: Purchase.objects.count()) == 2   # no se creó otra compra

    def test_emitido_se_vincula_con_la_venta_existente(self, empresa, dueno, sri):
        cliente = helpers.crear_cliente('cliente.emitido', empresa, '0990000009001', '0990004444')
        venta = helpers.crear_venta(empresa, cliente, dueno, helpers.crear_producto(empresa, 'P9', pvp='10.00'))
        clave = f.clave(ruc=RUC_EMPRESA)
        leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).update(access_code=clave))
        importar(empresa, dueno, ('mia.xml', f.autorizacion(f.factura(ruc=RUC_EMPRESA, receptor_id='0990000009001'))))
        with company_context(empresa):
            documento = DocumentoImportado.objects.get()
            assert documento.clasificacion == 'emitido' and documento.cliente_id == cliente.pk
            assert sv.candidatos_conciliacion(documento)[0] == {'tipo': 'venta', 'id': venta.pk, 'numero': venta.voucher_number_full,
                                                                 'razones': ['misma clave de acceso'], 'total': f'{venta.total:.2f}',
                                                                 'exacto': True}
            documento = sv.revisar(documento, dueno, 'vincular_venta', {'id': venta.pk, 'confirmar_sin_verificar': True})
        assert documento.estado_revision == 'vinculado' and 'La venta ya existe' in documento.propuesta_contable['avisos'][-1]
        assert leer(empresa, lambda: Sale.objects.count()) == 1

    def test_ajeno_no_se_incorpora(self, empresa, dueno, sri):
        importar(empresa, dueno, ('ajena.xml', f.autorizacion(f.factura(receptor_id='0990000009001'))))
        with company_context(empresa), pytest.raises(sv.ErrorImportacion, match='Solo se incorporan'):
            sv.revisar(DocumentoImportado.objects.get(), dueno, 'aprobar', {'confirmar_sin_verificar': True})


class TestAislamientoYArchivos:

    def test_cada_empresa_tiene_su_documento_y_no_ve_el_ajeno(self, client, empresa, dueno, web, sri):
        importar(empresa, dueno, ('f.xml', recibida()))
        documento = leer(empresa, lambda: DocumentoImportado.objects.get())
        otra = helpers.crear_empresa('OTRA RECEPTORA')
        dueno_otra = helpers.crear_usuario('dueno.otra.imp', otra, ROLE_OWNER)
        importar(otra, dueno_otra, ('f.xml', recibida()))
        with platform_scope():
            assert DocumentoImportado.all_companies.filter(clave_acceso=f.clave()).count() == 2   # única por empresa, no global
        assert leer(otra, lambda: DocumentoImportado.objects.get()).clasificacion == 'ajeno'
        client.logout()
        helpers.iniciar_sesion(client, dueno_otra, empresa=otra)
        assert client.get(f'/importacion/api/documentos/{documento.pk}/').status_code == 404
        assert client.get(f'/importacion/archivos/{documento.archivo_xml_id}/descargar/').status_code == 404

    def test_los_archivos_privados_no_salen_por_media(self, web, empresa, dueno, sri):
        importar(empresa, dueno, ('f.xml', recibida()))
        archivo = leer(empresa, lambda: DocumentoImportado.objects.get().archivo_xml)
        assert web.get(f'/media/{archivo.archivo.name}').status_code == 404
        respuesta = web.get(f'/importacion/archivos/{archivo.pk}/descargar/')
        assert respuesta.status_code == 200 and b'<autorizacion>' in b''.join(respuesta.streaming_content)
        assert respuesta['Cache-Control'] == 'private, no-store' and 'attachment' in respuesta['Content-Disposition']


class TestApiYPermisos:

    def test_flujo_por_la_api(self, web, empresa, sri):
        subida = web.post('/importacion/api/lotes/', {'archivos': [SimpleUploadedFile('a.xml', recibida().encode(), 'text/plain'),
                                                                  SimpleUploadedFile('b.pdf', f.pdf(), 'application/octet-stream')]})
        assert subida.status_code == 201
        lote = subida.json()['lote']
        assert [e['estado']['id'] for e in lote['entradas']] == ['procesado', 'en_cola'] and lote['pendientes'] == 1
        procesado = web.post(f'/importacion/api/lotes/{lote["id"]}/procesar/').json()['lote']
        assert procesado['pendientes'] == 0 and procesado['entradas'][1]['estado']['id'] == 'pendiente_clave'
        assert web.get(f'/importacion/api/lotes/{lote["id"]}/').json()['lote']['progreso'] == 100
        bandeja = web.get('/importacion/api/documentos/?bandeja=pendientes').json()
        assert bandeja['total'] == 1 and bandeja['documentos'][0]['importes']['importe_total'] == '135.00'
        documento_id = bandeja['documentos'][0]['id']
        detalle = web.get(f'/importacion/api/documentos/{documento_id}/').json()['documento']
        assert detalle['impuestos'][0]['tarifa'] == '15.00' and 'aprobar' in detalle['acciones'] and detalle['archivos']['xml']['descarga']
        r = web.post(f'/importacion/api/documentos/{documento_id}/revisar/', data=json.dumps({'accion': 'descartar', 'motivo': 'prueba'}),
                     content_type='application/json')
        assert r.status_code == 200 and r.json()['documento']['estados']['revision']['id'] == 'descartado'
        assert web.post(f'/importacion/api/documentos/{documento_id}/revisar/', {'accion': 'inventada'}).status_code == 400
        assert web.get('/importacion/api/documentos/?bandeja=nada').status_code == 400

    def test_subida_por_partes_al_mismo_lote(self, web, empresa, monkeypatch):
        from core.importacion import limites
        lote = web.post('/importacion/api/lotes/', {'archivos': [SimpleUploadedFile('a.xml', recibida().encode())]}).json()['lote']
        otra = recibida(secuencial='000000272')
        r = web.post(f'/importacion/api/lotes/{lote["id"]}/archivos/', {'archivos': [SimpleUploadedFile('b.xml', otra.encode())]})
        assert r.status_code == 201 and r.json()['lote']['total_archivos'] == 2
        assert [e['orden'] for e in r.json()['lote']['entradas']] == [0, 1]
        monkeypatch.setattr(limites, 'MAX_BYTES_POR_PETICION', 100)
        r = web.post(f'/importacion/api/lotes/{lote["id"]}/archivos/', {'archivos': [SimpleUploadedFile('c.xml', recibida().encode())]})
        assert r.status_code == 400 and 'por vez' in r.json()['error']

    def test_reglas_por_la_api(self, web):
        assert web.get('/importacion/api/reglas/').json()['reglas']['naturaleza_compra'] == 'gasto'
        r = web.post('/importacion/api/reglas/', data=json.dumps({'naturaleza_compra': 'inventario', 'cuenta_inventario': '1.1.03'}),
                     content_type='application/json')
        assert r.json()['reglas']['naturaleza_compra'] == 'inventario' and r.json()['reglas']['verificar_con_sri'] is True
        assert web.post('/importacion/api/reglas/', {'naturaleza_compra': 'otra'}).status_code == 400

    def test_contador_consulta_pero_no_importa_y_vendedor_no_entra(self, client, empresa):
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.imp', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get('/importacion/api/documentos/').status_code == 200
        assert client.get('/importacion/recibidos/').status_code == 200
        assert client.post('/importacion/api/lotes/', {}).status_code == 403
        assert client.get('/importacion/nueva/').status_code == 302
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario('vendedor.imp', empresa, ROLE_SELLER), empresa=empresa)
        assert client.get('/importacion/api/documentos/').status_code == 403
        assert client.get('/importacion/pendientes/').status_code == 302

    def test_paginas_de_los_modulos(self, web):
        for url in ('/importacion/nueva/', '/importacion/lotes/', '/importacion/pendientes/', '/importacion/recibidos/', '/importacion/reglas/'):
            assert web.get(url).status_code == 200, url
        assert 'Importar XML / RIDE' in web.get('/importacion/recibidos/').content.decode()


class TestMenu:

    def test_grupos_nombres_y_orden(self):
        assert list(ModuleType.objects.order_by('orden').values_list('name', flat=True)) == [
            'Comprobantes Electrónicos', 'Clientes y promociones', 'Compras y gastos', 'Importación de documentos', 'Bodega',
            'Administrativo', 'Reportes', 'Configuración', 'Seguridad']
        assert Module.objects.get(url='/pos/sale/admin/').name == 'Facturas emitidas'   # misma URL
        compras = Module.objects.filter(module_type__name='Compras y gastos').order_by('orden').values_list('name', flat=True)
        assert list(compras)[:3] == ['Compras registradas', 'Documentos recibidos', 'Proveedores']
        guias = Module.objects.get(url='/comprobantes/guias/')                            # implementada: aparece en su lugar
        assert guias.module_type.name == 'Comprobantes Electrónicos' and guias.orden == 5 and guias.name == 'Guías de remisión'
        assert Module.objects.get(url='/importacion/reglas/').module_type.name == 'Configuración'

    def test_modulos_por_rol(self, empresa):
        from django.contrib.auth.models import Group
        def urls(rol):
            return set(Group.objects.get(name=rol).groupmodule_set.values_list('module__url', flat=True))
        assert {'/importacion/nueva/', '/importacion/lotes/', '/importacion/pendientes/', '/importacion/recibidos/',
                '/importacion/reglas/'} <= urls(ROLE_OWNER)
        assert '/importacion/nueva/' not in urls(ROLE_ACCOUNTANT) and '/importacion/recibidos/' in urls(ROLE_ACCOUNTANT)
        assert '/importacion/nueva/' not in urls(ROLE_READONLY) and not any(u.startswith('/importacion/') for u in urls(ROLE_SELLER))


class TestTareaProgramada:

    def test_avanza_los_lotes_en_cola_y_reintenta_el_sri(self, empresa, dueno, sri):
        from django.core.management import call_command
        from django.utils import timezone
        sri.comprobantes[f.clave()] = f.factura()
        lote = importar(empresa, dueno, ('ride.pdf', f.pdf(('barras', f.clave()))))
        call_command('procesar_importaciones')
        assert leer(empresa, lambda: lote.entradas.get().estado) == 'procesado'
        sri.caido = True
        importar(empresa, dueno, ('otro.pdf', f.pdf(('barras', f.clave(secuencial='000000300')))))
        call_command('procesar_importaciones')
        with company_context(empresa):
            pendiente = DocumentoImportado.objects.get(secuencial='000000300')
            assert pendiente.estado_verificacion == 'sri_no_disponible'
            DocumentoImportado.objects.filter(pk=pendiente.pk).update(verificado_en=timezone.now() - timezone.timedelta(minutes=30))
        sri.caido, sri.comprobantes[f.clave(secuencial='000000300')] = False, f.factura(secuencial='000000300')
        call_command('procesar_importaciones')
        assert leer(empresa, lambda: DocumentoImportado.objects.get(secuencial='000000300').estado_procesamiento) == 'procesado'


class TestPlanes:
    """Decisión comercial (15/10/2026): la importación está incluida solo en Ilimitado y Multiempresa; no usa cupo."""

    def entrar(self, client, plan, **extra):
        empresa = helpers.crear_empresa(f'PLAN {plan}', plan=plan, **extra)
        helpers.iniciar_sesion(client, helpers.crear_usuario(f'dueno.{plan or "gratis"}.{empresa.pk}', empresa, ROLE_OWNER), empresa=empresa)
        return empresa

    @pytest.mark.parametrize('plan', ['plan-1000', None])
    def test_plan_1000_y_gratuito_no_importan(self, client, plan):
        self.entrar(client, plan)
        respuesta = client.get('/importacion/nueva/')
        assert respuesta.status_code == 302 and respuesta.url == '/suscripcion/'
        api = client.post('/importacion/api/lotes/', {'archivos': [SimpleUploadedFile('a.xml', recibida().encode())]})
        assert api.status_code == 403 and api.json()['plan'] == 'ilimitado' and 'Ilimitado y Multiempresa' in api.json()['error']
        assert client.get('/importacion/api/documentos/').status_code == 403

    def test_multiempresa_y_empresa_cubierta_importan(self, client):
        from core.suscripciones import servicios as suscripciones
        titular = self.entrar(client, 'multiempresa')
        assert client.get('/importacion/nueva/').status_code == 200
        dueno = Membership.objects.get(company=titular).user
        adicional = suscripciones.agregar_empresa(titular, dueno, {'ruc': '0990000007001', 'business_name': 'CUBIERTA S.A.', 'tradename': '',
                                                                   'main_address': 'Guayaquil', 'email': 'c@example.com', 'mobile': '0990000000'})
        client.post('/empresas/cambiar/', {'company': adicional.pk})
        assert client.get('/importacion/nueva/').status_code == 200

    def test_ilimitado_vencido_solo_consulta(self, client):
        from django.utils import timezone
        empresa = self.entrar(client, 'ilimitado')
        SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timezone.timedelta(days=1))
        assert client.get('/importacion/lotes/').status_code == 200
        assert client.post('/importacion/api/lotes/', {'archivos': [SimpleUploadedFile('a.xml', recibida().encode())]}).status_code == 403

    def test_candado_en_el_menu_y_beneficio_en_planes(self, client):
        from core.suscripciones.servicios import estado_empresa
        from core.suscripciones.templatetags.suscripciones import bloqueado_por_plan
        mil = helpers.crear_empresa('MIL', plan='plan-1000')
        ilimitada = helpers.crear_empresa('ILIMITADA', plan='ilimitado')
        assert bloqueado_por_plan('/importacion/nueva/', estado_empresa(mil))
        assert not bloqueado_por_plan('/importacion/nueva/', estado_empresa(ilimitada))
        assert not bloqueado_por_plan('/pos/purchase/', estado_empresa(mil))
        self.entrar(client, 'plan-1000')
        html = client.get('/suscripcion/').content.decode()
        assert html.count('Importación de comprobantes recibidos (XML y RIDE)') == 2   # Ilimitado y Multiempresa, no Plan 1000
