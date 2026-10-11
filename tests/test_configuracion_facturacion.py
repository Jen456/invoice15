"""Asistente de configuración inicial de facturación: progreso, establecimientos y puntos,
numeración independiente, continuidad desde otro sistema, reservas atómicas, aislamiento,
permisos, auditoría y requisitos de emisión (empresas ficticias)."""
import json

import pytest
from django.db import IntegrityError, transaction

from core.configuracion import servicios as sv
from core.pos.models import BillingSetup, Company, EmissionPoint, Establishment, Receipt, Sale
from core.tenancy.context import company_context, platform_scope
from core.tenancy.models import ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import helpers

pytestmark = pytest.mark.django_db
URL = '/configuracion/facturacion/'


@pytest.fixture
def nueva(db):
    """Empresa recién registrada: sin establecimientos, sin secuencias y sin 001-001 asignado."""
    return helpers.crear_empresa('NUEVA', establishment_code='', issuing_point_code='', establishment_address='')


@pytest.fixture
def dueno(nueva):
    return helpers.crear_usuario('dueno.nueva', nueva, ROLE_OWNER)


@pytest.fixture
def cliente(client, dueno, nueva):
    helpers.iniciar_sesion(client, dueno, empresa=nueva)
    return client


def paso(cliente, n, datos, **kwargs):
    return cliente.post(f'{URL}paso/{n}/', datos, **kwargs)


def completar_pasos_1_y_2(cliente, empresa, estab='002', punto='001'):
    datos = {k: v for k, v in Company.objects.filter(pk=empresa.pk).values(
        'ruc', 'business_name', 'tradename', 'main_address', 'obligated_accounting', 'special_taxpayer',
        'retention_agent', 'mobile', 'phone', 'email')[0].items()}
    datos['ruc'] = '0991234567001'   # RUC de sociedad con formato válido (el de los datos ficticios no lo es)
    assert paso(cliente, 1, datos)['Location'] == f'{URL}paso/2/'
    paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': estab, 'name': 'Matriz', 'address': 'Av. 9 de Octubre 100',
                      'point_code': punto, 'point_description': 'Caja 1'})
    with company_context(empresa):
        pto = EmissionPoint.objects.get(establishment__code=estab, code=punto)
    return pto


def numeracion(cliente, factura, nota, ambiente=1):
    datos = {'ambiente': str(ambiente)}
    for tipo, (modo, ultimo, confirmar) in (('01', factura), ('04', nota)):
        datos.update({f'{tipo}-mode': modo, f'{tipo}-last_number': ultimo})
        if confirmar:
            datos[f'{tipo}-confirm'] = 'on'
    return paso(cliente, 3, datos)


# ---------------------------------------------------------------- empresa nueva

class TestEmpresaNueva:

    def test_paso_1_valida_el_ruc(self, cliente, nueva):
        datos = {'ruc': '0912345678001', 'business_name': 'X', 'tradename': 'X', 'main_address': 'X',
                 'obligated_accounting': 'no', 'special_taxpayer': '000', 'retention_agent': 'no',
                 'mobile': '0990000000', 'phone': '042000000', 'email': 'x@example.com'}
        respuesta = paso(cliente, 1, datos)
        assert respuesta.status_code == 200 and 'Ingresa un RUC válido de 13 dígitos.' in respuesta.content.decode()

    def test_empieza_en_el_paso_1_y_permite_inventario(self, cliente, nueva):
        assert cliente.get(URL)['Location'] == f'{URL}paso/1/'
        estado = cliente.get(f'{URL}estado.json').json()
        assert estado['completo'] is False and estado['paso_actual'] == 1 and estado['punto'] is None
        assert [d['existe'] for d in estado['documentos']] == [False, False, False]
        assert cliente.get('/pos/product/').status_code == 200   # el inventario no se bloquea
        with company_context(nueva):
            assert not Establishment.objects.exists()
        for n in range(1, 6):
            assert cliente.get(f'{URL}paso/{n}/').status_code == 200

    def test_emitir_sin_configuracion_explica_como_resolverlo(self, cliente):
        respuesta = cliente.post('/pos/sale/admin/add/', {'action': 'add', 'date_joined': '2026-10-11', 'receipt': '01'})
        error = respuesta.json()['error']
        assert 'Para emitir facturas completa la configuración de facturación (paso 1).' in error
        assert '/configuracion/facturacion/paso/1/' in error

    def test_flujo_completo_con_continuidad_desde_otro_sistema(self, cliente, nueva):
        pto = completar_pasos_1_y_2(cliente, nueva, estab='002', punto='001')
        # Sin confirmar los códigos no avanza (no se asume nada)
        sin_confirmar = paso(cliente, 2, {'action': 'confirmar', 'point': pto.pk})
        assert sv.MENSAJES['confirmar_codigos'] in sin_confirmar.content.decode()
        assert paso(cliente, 2, {'action': 'confirmar', 'point': pto.pk, 'confirm': 'on'})['Location'] == f'{URL}paso/3/'
        nueva.refresh_from_db()
        assert (nueva.establishment_code, nueva.issuing_point_code) == ('002', '001')   # ceros iniciales intactos
        # Factura continúa desde otro sistema; nota de crédito empieza de cero (con confirmación)
        respuesta = numeracion(cliente, ('otro_sistema', '002-001-000000125', True), ('nuevo', '', True))
        assert respuesta['Location'] == f'{URL}paso/4/'
        with company_context(nueva):
            factura = Receipt.objects.get(voucher_type='01', environment_type=1)
            nota = Receipt.objects.get(voucher_type='04', environment_type=1)
        assert (factura.sequence, factura.next_number_full()) == (125, '002-001-000000126')
        assert (nota.sequence, nota.next_number_full()) == (0, '002-001-000000001')
        assert factura.confirmed_at is None   # se confirma en el paso 5
        assert paso(cliente, 4, {'environment_type': '1'})['Location'] == f'{URL}paso/5/'
        revision = cliente.get(f'{URL}paso/5/').content.decode()
        assert 'Número del próximo documento' in revision and '002-001-000000126' in revision and '002-001-000000001' in revision
        assert paso(cliente, 5, {'confirm': 'on'})['Location'] == f'{URL}paso/5/'
        estado = cliente.get(f'{URL}estado.json').json()
        assert estado['completo'] is True and estado['punto'] == '002-001'
        proximos = {d['tipo']: d['proximo_completo'] for d in estado['documentos']}
        assert proximos == {'01': '002-001-000000126', '04': '002-001-000000001', '08': '002-001-000000001'}
        # Factura sin firma: se puede emitir no electrónica; la electrónica pide la firma
        with company_context(nueva):
            assert sv.requisitos_de_emision(nueva, '01', electronica=False) == []
            assert [r['codigo'] for r in sv.requisitos_de_emision(nueva, '01', electronica=True)] == ['firma']
        assert AuditLog.objects.filter(action='billing_setup_confirm', company=nueva).exists()

    def test_retoma_donde_quedo(self, cliente, nueva):
        completar_pasos_1_y_2(cliente, nueva)
        assert cliente.get(URL)['Location'] == f'{URL}paso/2/'   # falta confirmar el punto
        with company_context(nueva):
            setup = BillingSetup.objects.get()
        assert setup.completed_steps == [1] and setup.current_step == 2


# ---------------------------------------------------------------- validaciones

class TestValidaciones:

    @pytest.mark.parametrize('codigo', ['1', '01', '0001', '000', 'A01'])
    def test_codigos_de_tres_digitos(self, cliente, nueva, codigo):
        respuesta = paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': codigo, 'address': 'x'})
        assert respuesta.status_code == 200 and 'invalid-feedback' in respuesta.content.decode()
        if len(codigo) <= 3:
            assert 'Usa tres dígitos, por ejemplo 001 (000 no es válido).' in respuesta.content.decode()
        with company_context(nueva):
            assert not Establishment.objects.exists()

    def test_primer_establecimiento_pide_su_punto_en_el_mismo_formulario(self, cliente, nueva):
        pagina = cliente.get(f'{URL}paso/2/').content.decode()
        assert 'Agrega tu establecimiento y su punto de emisión' in pagina
        assert 'value="agregar_punto"' not in pagina   # sin establecimientos no hay lista vacía que elegir
        respuesta = paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': '001', 'address': 'x'})
        assert sv.MENSAJES['falta_codigo_punto'] in respuesta.content.decode()
        with company_context(nueva):
            assert not Establishment.objects.exists()
        paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': '001', 'address': 'x', 'point_code': '002'})
        with company_context(nueva):
            assert [p.full_code for p in EmissionPoint.objects.all()] == ['001-002']
        assert AuditLog.objects.filter(action='billing_point_change', company=nueva).count() == 2
        pagina = cliente.get(f'{URL}paso/2/').content.decode()
        assert 'value="agregar_punto"' in pagina and 'Código del punto de emisión (opcional)' in pagina
        # Un segundo establecimiento puede agregarse sin punto; el punto se elige después
        paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': '003', 'address': 'y'})
        with company_context(nueva):
            assert Establishment.objects.filter(code='003', points__isnull=True).exists()

    def test_punto_sin_establecimiento_explica_que_hacer(self, cliente, nueva):
        respuesta = paso(cliente, 2, {'action': 'agregar_punto', 'code': '002'}, follow=True)
        pagina = respuesta.content.decode()
        assert sv.MENSAJES['elige_establecimiento'] in pagina and 'Agrega tu establecimiento y su punto de emisión' in pagina

    def test_duplicados(self, cliente, nueva):
        pto = completar_pasos_1_y_2(cliente, nueva, estab='001', punto='001')
        r1 = paso(cliente, 2, {'action': 'agregar_establecimiento', 'code': '001', 'address': 'x'})
        assert sv.MENSAJES['establecimiento_duplicado'].format(codigo='001') in r1.content.decode()
        r2 = paso(cliente, 2, {'action': 'agregar_punto', 'establishment': pto.establishment_id, 'code': '001'})
        assert sv.MENSAJES['punto_duplicado'].format(codigo='001', establecimiento='001') in r2.content.decode()

    def test_formatos_y_rangos_del_ultimo_numero(self, nueva):
        with company_context(nueva):
            est = Establishment.objects.create(code='001', address='x')
            pto = EmissionPoint.objects.create(establishment=est, code='002', is_default=True)
        assert sv.interpretar_ultimo('125', pto) == 125
        assert sv.interpretar_ultimo('000000125', pto) == 125
        assert sv.interpretar_ultimo('001-002-000000125', pto) == 125
        for texto, mensaje in (('abc', 'ultimo_formato'), ('0', 'ultimo_rango'), ('999999999', 'ultimo_rango'),
                               ('001-001-000000125', None), ('1-2-3', 'ultimo_formato')):
            with pytest.raises(sv.ErrorConfiguracion) as e:
                sv.interpretar_ultimo(texto, pto)
            if mensaje:
                assert str(e.value) == sv.MENSAJES[mensaje]
            else:
                assert 'es de otro punto de emisión (001-001); aquí configuras 001-002' in str(e.value)

    def test_empezar_en_uno_exige_confirmacion(self, cliente, nueva):
        pto = completar_pasos_1_y_2(cliente, nueva, estab='001', punto='001')
        paso(cliente, 2, {'action': 'confirmar', 'point': pto.pk, 'confirm': 'on'})
        respuesta = numeracion(cliente, ('nuevo', '', False), ('nuevo', '', False))
        assert 'Confirma que nunca has emitido facturas desde 001-001 en PRUEBAS.' in respuesta.content.decode()
        with company_context(nueva):
            assert not Receipt.objects.exists()


# ---------------------------------------------------------------- empresas existentes y secuencias usadas

class TestNumeracionExistente:

    @pytest.fixture
    def con_legado(self, empresa):
        """Empresa con secuencias anteriores al asistente (último usado 980 en facturas) y sin confirmar."""
        with company_context(empresa):
            est = Establishment.objects.create(code='001', address='x')
            pto = EmissionPoint.objects.create(establishment=est, code='001', is_default=True)
            Receipt.objects.create(voucher_type='01', establishment_code='001', issuing_point_code='001', sequence=980,
                                   emission_point=pto, origin='existente')
        return empresa, pto

    def test_no_se_reinicia_ni_retrocede(self, con_legado):
        empresa, pto = con_legado
        with company_context(empresa):
            with pytest.raises(sv.ErrorConfiguracion, match='Esta numeración ya existía'):
                sv.configurar_secuencia(empresa, pto, 1, '01', 'nuevo', confirmado=True)
            with pytest.raises(sv.ErrorConfiguracion, match='no puede ser menor que 000000980'):
                sv.configurar_secuencia(empresa, pto, 1, '01', 'otro_sistema', '500', confirmado=True)
            r = sv.configurar_secuencia(empresa, pto, 1, '01', 'mantener')
            assert r.sequence == 980 and r.next_number_full() == '001-001-000000981'
            r = sv.configurar_secuencia(empresa, pto, 1, '01', 'otro_sistema', '1200', confirmado=True)
            assert r.sequence == 1200
        cambio = AuditLog.objects.filter(action='billing_sequence_change', company=empresa).latest('created_at')
        assert cambio.detail['antes'] == 980 and cambio.detail['ultimo'] == 1200 and cambio.detail['proximo'] == 1201

    def test_secuencia_usada_solo_avanza(self, empresa, admin):
        pto = helpers.configurar_facturacion(empresa, ultimo_factura=4)
        cli = helpers.crear_cliente('cli.sec', empresa, '0911111111', '0991111111')
        with company_context(empresa):
            receipt = Receipt.objects.get(voucher_type='01')
            numero = receipt.reservar_numero()
            assert numero == '000000005'
            Sale.objects.create(client=cli, receipt=receipt, employee=admin, voucher_number=numero,
                                voucher_number_full=f'001-001-{numero}')
            with pytest.raises(sv.ErrorConfiguracion, match='no se puede reiniciar'):
                sv.configurar_secuencia(empresa, pto, 1, '01', 'nuevo', confirmado=True)
            Receipt.objects.filter(pk=receipt.pk).update(sequence=2)   # aunque alguien bajara el contador
            with pytest.raises(sv.ErrorConfiguracion, match='no puede ser menor que 000000005'):
                sv.configurar_secuencia(empresa, pto, 1, '01', 'otro_sistema', '3', confirmado=True)
            r = sv.configurar_secuencia(empresa, pto, 1, '01', 'otro_sistema', '20', confirmado=True)
            assert r.next_number_full() == '001-001-000000021' and r.confirmed_at is None

    def test_migracion_de_datos_no_toca_los_numeros(self, empresa, empresa_b, admin):
        import importlib
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        migracion = importlib.import_module('core.pos.migrations.0009_configuracion_datos_existentes')
        # Modelos históricos (gestores sin filtro de empresa), como al ejecutar la migración real.
        apps = MigrationExecutor(connection).loader.project_state(('pos', '0009_configuracion_datos_existentes')).apps
        nueva = helpers.crear_empresa('SIN SECUENCIAS')   # recién registrada, con 001-001 heredado
        with company_context(empresa):
            Receipt.objects.create(voucher_type='01', establishment_code='001', issuing_point_code='001', sequence=4321)
        with company_context(empresa_b):
            r = Receipt.objects.create(voucher_type='01', establishment_code='001', issuing_point_code='001', sequence=77)
        cli = helpers.crear_cliente('cli.mig', empresa_b, '0911111111', '0991111111')
        with company_context(empresa_b):
            Sale.objects.create(client=cli, receipt=r, employee=admin, voucher_number='000000077', voucher_number_full='001-001-000000077')
        with platform_scope():
            migracion.forwards(apps, None)
            a = Receipt.all_companies.get(company=empresa)
            b = Receipt.all_companies.get(company=empresa_b)
            assert (a.sequence, a.origin, a.confirmed_at) == (4321, 'existente', None)
            assert b.sequence == 77 and b.confirmed_at is not None
            assert BillingSetup.all_companies.get(company=empresa).completed_at is None        # debe confirmar en el asistente
            assert BillingSetup.all_companies.get(company=empresa_b).completed_at is not None  # ya emitía: no se bloquea
            assert not Establishment.all_companies.filter(company=nueva).exists()              # sin 001-001 asumido


# ---------------------------------------------------------------- separación de secuencias y reservas

class TestSecuencias:

    def test_factura_y_nota_independientes_y_por_ambiente(self, empresa):
        pto = helpers.configurar_facturacion(empresa, ultimo_factura=125, ultimo_nota=7)
        with company_context(empresa):
            factura = Receipt.objects.get(voucher_type='01', environment_type=1)
            nota = Receipt.objects.get(voucher_type='04', environment_type=1)
            assert [factura.reservar_numero(), factura.reservar_numero()] == ['000000126', '000000127']
            assert nota.reservar_numero() == '000000008'
            prod = sv.configurar_secuencia(empresa, pto, 2, '01', 'nuevo', confirmado=True)
            assert prod.next_number_full() == '001-001-000000001'
            factura.refresh_from_db()
            assert factura.sequence == 127   # producción no altera pruebas

    def test_reserva_salta_numeros_ya_usados_y_unicidad_en_base(self, empresa, admin):
        helpers.configurar_facturacion(empresa, ultimo_factura=4)
        cli = helpers.crear_cliente('cli.res', empresa, '0911111111', '0991111111')
        with company_context(empresa):
            receipt = Receipt.objects.get(voucher_type='01')
            Sale.objects.create(client=cli, receipt=receipt, employee=admin, voucher_number='000000005', voucher_number_full='001-001-000000005')
            Receipt.objects.filter(pk=receipt.pk).update(sequence=4)   # contador desalineado a propósito
            receipt.refresh_from_db()
            assert receipt.reservar_numero() == '000000006'
            with pytest.raises(IntegrityError), transaction.atomic():
                Sale.objects.create(client=cli, receipt=receipt, employee=admin, voucher_number='000000005', voucher_number_full='x')

    def test_cambiar_de_ambiente_exige_numeracion_y_reconfirmar(self, cliente, nueva):
        pto = completar_pasos_1_y_2(cliente, nueva, estab='001', punto='001')
        paso(cliente, 2, {'action': 'confirmar', 'point': pto.pk, 'confirm': 'on'})
        numeracion(cliente, ('nuevo', '', True), ('nuevo', '', True))
        paso(cliente, 4, {'environment_type': '1'})
        paso(cliente, 5, {'confirm': 'on'})
        assert cliente.get(f'{URL}estado.json').json()['completo'] is True
        sin_confirmar = paso(cliente, 4, {'environment_type': '2'})
        assert sv.MENSAJES['confirmar_produccion'] in sin_confirmar.content.decode()
        assert paso(cliente, 4, {'environment_type': '2', 'confirm_production': 'on'})['Location'] == f'{URL}paso/3/'
        estado = cliente.get(f'{URL}estado.json').json()
        assert estado['completo'] is False and estado['ambiente']['codigo'] == 2
        respuesta = cliente.post('/pos/sale/admin/add/', {'action': 'add', 'date_joined': '2026-10-11', 'receipt': '01'})
        assert 'completa la configuración de facturación' in respuesta.json()['error']


# ---------------------------------------------------------------- permisos, aislamiento y pantallas unificadas

class TestPermisosYAislamiento:

    @pytest.mark.parametrize('rol, permitido', [(ROLE_OWNER, True), (ROLE_ADMIN, True), (ROLE_SELLER, False), (ROLE_READONLY, False)])
    def test_solo_propietario_y_administrador(self, client, nueva, rol, permitido):
        usuario = helpers.crear_usuario(f'u.{rol.lower()}', nueva, rol)
        helpers.iniciar_sesion(client, usuario, empresa=nueva)
        assert (client.get(f'{URL}paso/1/').status_code == 200) == permitido
        respuesta = client.post(f'{URL}paso/2/', {'action': 'agregar_establecimiento', 'code': '009', 'address': 'x', 'point_code': '001'})
        with company_context(nueva):
            assert Establishment.objects.filter(code='009').exists() == permitido
        if not permitido:
            assert respuesta.status_code == 403

    def test_una_empresa_no_toca_los_puntos_de_otra(self, cliente, nueva, empresa_b):
        ajeno = helpers.configurar_facturacion(empresa_b, estab='005', punto='009')
        respuesta = paso(cliente, 2, {'action': 'desactivar_punto', 'point': ajeno.pk})
        assert respuesta.status_code == 404
        with company_context(empresa_b):
            assert EmissionPoint.objects.get(pk=ajeno.pk).is_active
        assert '005-009' not in json.dumps(cliente.get(f'{URL}estado.json').json())

    def test_comprobantes_solo_consulta_y_compania_unificada(self, client, empresa, admin):
        helpers.configurar_facturacion(empresa, estab='003', punto='002', ultimo_factura=41)
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert client.get('/pos/receipt/add/')['Location'] == f'{URL}paso/3/'
        bloqueo = client.post('/pos/receipt/add/', {'action': 'add', 'sequence': '1'})
        assert bloqueo.status_code == 403 and 'paso 3' in bloqueo.json()['error']
        filas = client.post('/pos/receipt/', {'action': 'search'}).json()
        factura = next(f for f in filas if f['voucher_type']['id'] == '01')
        assert factura['next_number_full'] == '003-002-000000042' and factura['confirmed'] is True
        html = client.get('/pos/company/update/').content.decode()
        assert 'name="establishment_code"' not in html and 'name="environment_type"' not in html
        assert '003-002' in html and '003-002-000000042' in html
        # Enviar esos campos desde Compañía no cambia nada
        empresa.refresh_from_db()
        assert (empresa.establishment_code, empresa.issuing_point_code) == ('003', '002')

    def test_aviso_de_configuracion_pendiente_con_plan(self, client, empresa, admin):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        html = client.get('/dashboard/').content.decode()
        assert 'fp-aviso-configuracion' in html and 'Continuar configuración' in html
        helpers.configurar_facturacion(empresa)
        assert 'fp-aviso-configuracion' in client.get('/dashboard/').content.decode()   # aún falta la firma
