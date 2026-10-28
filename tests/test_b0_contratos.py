"""Contratos comunes de la fase contable (commit B0 del integrador), antes de Proformas, Compras y Ventas: señal
comprobante_autorizado (un receptor que falla no cambia el estado y se vuelve a llamar al reenviar), menú generalizado
por app, consultas de retenciones, dataclasses del 07 recibido y roles."""
import dataclasses
import importlib
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.dispatch import Signal
from django.utils import timezone

from core.comprobantes import retenciones as sv
from core.comprobantes.models import CodigoRetencion, Retencion
from core.configuracion import servicios as cfg
from core.importacion import recibidos
from core.pos import choices
from core.pos.models import Client, CreditNote, Provider, Purchase, Sale, VoucherErrors
from core.pos.senales_comprobantes import anulado_en_sri, comprobante_autorizado
from core.security import menu
from core.security.models import GroupModule, Module, ModuleType
from core.tenancy import roles
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from core.user.models import User
from tests.test_emision_sri import (accion, comprador, dueno, empresa, leer, p12, producto, refrescar, sri, vender,  # noqa: F401
                                    venta_de, web)

pytestmark = pytest.mark.django_db
ROLES = (ROLE_OWNER, ROLE_ADMIN, ROLE_ACCOUNTANT, ROLE_SELLER, ROLE_READONLY, ROLE_CLIENT)


@pytest.fixture
def receptores():
    """Conecta receptores de prueba a comprobante_autorizado y los desconecta al terminar."""
    conectados = []

    def conectar(funcion, sender):
        uid = f'prueba_b0_{len(conectados)}'
        comprobante_autorizado.connect(funcion, sender=sender, weak=False, dispatch_uid=uid)
        conectados.append((sender, uid))

    yield conectar
    for sender, uid in conectados:
        comprobante_autorizado.disconnect(sender=sender, dispatch_uid=uid)


def errores_de(empresa, comprobante):
    return leer(empresa, lambda: list(VoucherErrors.objects.filter(reference=comprobante.voucher_number_full)
                                      .order_by('id').values_list('stage', 'errors')))


# ---------------------------------------------------------------- señal comprobante_autorizado

class TestSenalAutorizado:

    def test_las_senales_son_las_del_contrato(self):
        assert isinstance(comprobante_autorizado, Signal) and isinstance(anulado_en_sri, Signal)
        recibido = []
        anulado_en_sri.connect(lambda sender, **kw: recibido.append((sender, sorted(kw))), weak=False, dispatch_uid='prueba_b0_anulado')
        try:
            anulado_en_sri.send(sender=Sale, instance=None, usuario=None, fecha=date(2026, 10, 28))
        finally:
            anulado_en_sri.disconnect(dispatch_uid='prueba_b0_anulado')
        assert recibido == [(Sale, ['fecha', 'instance', 'signal', 'usuario'])]

    def test_receptor_que_falla_no_cambia_el_estado_y_se_llama_otra_vez_al_reenviar(self, web, empresa, comprador, producto,
                                                                                    sri, receptores):
        llamadas = []

        def falla(sender, comprobante, **kwargs):
            llamadas.append((sender, comprobante.pk, comprobante.status))
            raise RuntimeError('ajuste de prueba')

        receptores(falla, Sale)
        receptores(lambda sender, comprobante, **kw: llamadas.append('nota'), CreditNote)   # otro sender: no se llama
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert r['resp'] is True and r['estado'] == 'authorized' and r['print_url']
        assert venta.status == 'authorized' and venta.pdf_authorized
        assert llamadas == [(Sale, venta.pk, 'authorized')]
        pendiente = ('xml_authorized', {'stage': 'xml_authorized',
                                        'error': 'Autorizada, pero un ajuste posterior quedó pendiente (RuntimeError).'})
        assert errores_de(empresa, venta) == [pendiente]
        # Reenviar una factura ya autorizada vuelve a emitir la señal: los receptores tienen que ser idempotentes.
        recepciones = len(sri.recepciones)
        r = accion(web, 'generate_invoice', venta)
        refrescar(venta)
        assert r['resp'] is True and 'Ya estaba autorizada' in r['mensaje'] and venta.status == 'authorized'
        assert llamadas == [(Sale, venta.pk, 'authorized')] * 2 and len(sri.recepciones) == recepciones
        assert errores_de(empresa, venta) == [pendiente] * 2

    def test_despues_del_ride_y_de_la_factura_y_antes_del_correo(self, web, empresa, comprador, producto, sri, receptores):
        leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))
        User.objects.filter(pk=comprador.user_id).update(email='comprador@example.com')
        vistos = []

        def anota(sender, comprobante, **kwargs):
            factura = Sale.all_companies.get(pk=comprobante.sale_id).status if sender is CreditNote else None
            vistos.append((sender.__name__, comprobante.status, bool(comprobante.pdf_authorized), len(mail.outbox), factura))

        receptores(anota, Sale)
        receptores(anota, CreditNote)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        factura = venta_de(empresa, 271)
        assert factura.status == 'authorized_and_sent_by_email'
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert accion(web, 'create_credit_note', factura)['resp'] is True
        # RIDE ya generado, factura ya «Anulado» por la nota total y correo aún sin enviar
        assert vistos == [('Sale', 'authorized', True, 0, None), ('CreditNote', 'authorized', True, 1, 'canceled')]
        assert len(mail.outbox) == 2 and errores_de(empresa, factura) == []


# ---------------------------------------------------------------- menú generalizado

def estado_menu():
    """Grupos del menú, módulos (con sus permisos) y módulos y permisos de cada rol, para comparar."""
    tipos = sorted(ModuleType.objects.values_list('name', 'icon', 'orden'))
    modulos = {m.url: (m.name, m.icon, m.description, m.orden, m.module_type.name if m.module_type_id else None,
                       sorted(m.permissions.values_list('content_type__app_label', 'codename')))
               for m in Module.objects.select_related('module_type')}
    grupos = {g.name: (sorted(g.groupmodule_set.values_list('module__url', flat=True)),
                       sorted(g.permissions.values_list('codename', flat=True)))
              for g in Group.objects.filter(name__in=ROLES)}
    return tipos, modulos, grupos


def organizar_y_sincronizar():
    menu.organizar_menu(ModuleType, Module, Permission)
    roles.sync_roles(Group, Module, GroupModule)


class TestMenu:

    def test_cada_modulo_nuevo_declara_su_app_sin_entradas_nuevas(self):
        assert [m[:2] for m in menu.MODULOS_NUEVOS] == [
            ('importacion', '/importacion/recibidos/'), ('importacion', '/importacion/nueva/'), ('importacion', '/importacion/lotes/'),
            ('importacion', '/importacion/pendientes/'), ('importacion', '/importacion/reglas/')]

    def test_importacion_queda_igual_y_se_recrea_igual(self):
        antes = estado_menu()
        assert set(antes[1]['/importacion/nueva/'][5]) == {('importacion', 'view_documentoimportado'),
                                                           ('importacion', 'add_documentoimportado')}
        organizar_y_sincronizar()
        assert estado_menu() == antes
        Module.objects.filter(url__startswith='/importacion/').delete()   # como una base anterior a la importación
        organizar_y_sincronizar()
        assert estado_menu() == antes

    def test_no_crea_modulos_de_apps_sin_permisos(self, monkeypatch):
        antes = estado_menu()
        monkeypatch.setattr(menu, 'MODULOS_NUEVOS', menu.MODULOS_NUEVOS + (
            ('proformas', '/proformas/', 'fas fa-file-contract', 'App aún sin migrar', ('view_proforma', 'add_proforma')),
            ('pos', '/pos/inexistente/', 'fas fa-ban', 'Permisos que no existen', ('view_inexistente',)),
        ))
        organizar_y_sincronizar()
        assert not Module.objects.filter(url__in=['/proformas/', '/pos/inexistente/']).exists()
        assert estado_menu() == antes

    def test_migraciones_de_importacion_siguen_funcionando(self):
        antes = estado_menu()
        estados = MigrationExecutor(connection).loader
        for nombre in ('0003_menu_y_modulos', '0004_menu_con_guias'):
            migracion = importlib.import_module(f'core.importacion.migrations.{nombre}')
            migracion.forwards(estados.project_state(('importacion', nombre)).apps, None)   # modelos históricos
        assert estado_menu() == antes


# ---------------------------------------------------------------- roles

class TestRoles:

    def test_entradas_de_proformas_y_retenciones_recibidas(self):
        assert '/proformas/' in roles.SELLER_URLS and '/proformas/' in roles.ACCOUNTANT_URLS
        assert '/comprobantes/retenciones-recibidas/' in roles.ACCOUNTANT_URLS
        assert '/comprobantes/retenciones-recibidas/' not in roles.SELLER_URLS
        assert {'add_proforma', 'change_proforma'} <= roles.SELLER_WRITE and 'delete_proforma' not in roles.SELLER_WRITE

    def test_sin_esos_modulos_sync_roles_no_cambia_nada(self):
        antes = estado_menu()
        roles.sync_roles(Group, Module, GroupModule)
        assert estado_menu() == antes
        assert not Module.objects.filter(url__in=['/proformas/', '/comprobantes/retenciones-recibidas/']).exists()

    def test_con_el_modulo_vendedor_escribe_y_contador_solo_lee(self):
        # Módulo simulado (la app de Proformas aún no existe): el reparto por rol ya queda listo.
        tipo = ContentType.objects.create(app_label='proformas_prueba', model='proforma')
        permisos = [Permission.objects.create(content_type=tipo, codename=f'{a}_proforma', name=f'Can {a} proforma')
                    for a in ('view', 'add', 'change', 'delete')]
        Module.objects.create(url='/proformas/', name='Proformas', icon='fas fa-file-contract').permissions.set(permisos)
        roles.sync_roles(Group, Module, GroupModule)

        def codigos(rol):
            return set(Group.objects.get(name=rol).permissions.filter(content_type=tipo).values_list('codename', flat=True))

        assert codigos(ROLE_SELLER) == {'view_proforma', 'add_proforma', 'change_proforma'}
        assert codigos(ROLE_ACCOUNTANT) == codigos(ROLE_READONLY) == {'view_proforma'}
        assert codigos(ROLE_OWNER) == {'view_proforma', 'add_proforma', 'change_proforma', 'delete_proforma'}
        assert codigos(ROLE_CLIENT) == set()


# ---------------------------------------------------------------- retenciones

DATOS_RETENCION = {'num_doc_sustento': '001-001-000000123', 'aut_doc_sustento': '1' * 49, 'base_0': '0',
                   'base_iva': '100.00', 'tarifa_iva': '15.00', 'cod_sustento': '01', 'forma_pago': '20'}


class TestRetenciones:
    HOY = date(2026, 10, 28)

    def test_retenciones_autorizadas_solo_las_autorizadas(self, empresa, dueno):
        with company_context(empresa):
            cfg.configurar_otro_documento(empresa, '07', 'otro_sistema', '001-002-000000040', True)
            proveedor = Provider.objects.create(name='PROVEEDOR B0 S.A.', ruc='0990000001001', mobile='0990000000',
                                                email='compras@proveedor.example', address='Av. Quito 100')
            compra = Purchase.objects.create(number='123', provider=proveedor, subtotal=Decimal('100.00'))
            otra = Purchase.objects.create(number='124', provider=proveedor, subtotal=Decimal('100.00'))
            codigo = sv.codigo_retencion_vigente('1', '312', self.HOY)
            datos = dict(DATOS_RETENCION, fecha_doc_sustento=timezone.localdate() - timedelta(days=1))

            def retencion(sobre, estado):
                with transaction.atomic():
                    ret = sv.crear(empresa, dueno, sobre, datos, [(codigo.pk, None, None)])
                Retencion.objects.filter(pk=ret.pk).update(status=estado)
                return ret

            retencion(compra, 'returned')
            autorizada = retencion(compra, 'authorized')
            retencion(otra, 'authorized')
            assert list(sv.retenciones_autorizadas(compra)) == [autorizada]
            Retencion.objects.filter(pk=autorizada.pk).update(status='authorized_and_sent_by_email')
            assert list(sv.retenciones_autorizadas(compra)) == [autorizada]
            for estado in ('in_process', 'without_authorizing', 'canceled', 'not_authorized'):
                Retencion.objects.filter(pk=autorizada.pk).update(status=estado)
                assert not sv.retenciones_autorizadas(compra).exists(), estado

    def test_codigo_retencion_vigente(self):
        fila = sv.codigo_retencion_vigente('1', '312', self.HOY)
        assert (fila.impuesto, fila.codigo, fila.activo) == ('1', '312', True)
        assert sv.codigo_retencion_vigente('2', '312', self.HOY) is None            # la pareja, no solo el código
        assert sv.codigo_retencion_vigente('1', '99999', self.HOY, incluir_inactivos=True) is None
        CodigoRetencion.objects.filter(pk=fila.pk).update(activo=False)
        assert sv.codigo_retencion_vigente('1', '312', self.HOY) is None
        assert sv.codigo_retencion_vigente('1', '312', self.HOY, incluir_inactivos=True).pk == fila.pk

    def test_codigos_retencion_vigentes(self):
        catalogo = list(CodigoRetencion.objects.all())
        CodigoRetencion.objects.filter(pk=catalogo[0].pk).update(activo=False)
        activos = list(sv.codigos_retencion_vigentes(self.HOY))
        todos = list(sv.codigos_retencion_vigentes(self.HOY, incluir_inactivos=True))
        assert [c.pk for c in todos] == [c.pk for c in catalogo]                      # orden del catálogo
        assert [c.pk for c in activos] == [c.pk for c in catalogo[1:] if c.activo]
        assert len({(c.impuesto, c.codigo) for c in todos}) == len(todos)               # una fila por pareja


# ---------------------------------------------------------------- 07 recibido: dataclasses y firmas

class TestRecibidos:

    def test_dataclasses_del_contrato(self):
        linea = recibidos.RetencionLineaLeida('1', '312', Decimal('100.00'), Decimal('2.00'), Decimal('2.00'))
        sustento = recibidos.SustentoLeido('01', '001002000000271', date(2026, 10, 1), '1' * 49, '01', (linea,))
        leida = recibidos.RetencionLeida(
            documento_id=1, clave_acceso='1' * 49, ambiente=2, numero='001-001-000000010', fecha_emision=date(2026, 10, 2),
            periodo_fiscal='10/2026', agente_ruc='0990000001001', agente_razon_social='CLIENTE S.A.', version='2.0.0',
            total_retenido=Decimal('2.00'), verificado_sri=True, estado_verificacion='verificada_sri', sustentos=(sustento,))
        assert sustento.numero_con_guiones == '001-002-000000271'
        assert recibidos.SustentoLeido('01', '123', None, '', '', ()).numero_con_guiones == '123'
        assert [f.name for f in dataclasses.fields(recibidos.RetencionLeida)] == [
            'documento_id', 'clave_acceso', 'ambiente', 'numero', 'fecha_emision', 'periodo_fiscal', 'agente_ruc',
            'agente_razon_social', 'version', 'total_retenido', 'verificado_sri', 'estado_verificacion', 'sustentos']
        assert leida.ambiente == 2 and leida.verificado_sri is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            leida.ambiente = 1

    @pytest.mark.parametrize('funcion, argumentos', [
        ('retencion_recibida_de', (None,)), ('marcar_incorporado', (None, None, 'Retenciones recibidas #1')),
        ('desmarcar_incorporado', (None, None, 'Anulada')),
    ])
    def test_firmas_pendientes_de_compras(self, funcion, argumentos):
        with pytest.raises(NotImplementedError, match='O1'):
            getattr(recibidos, funcion)(*argumentos)


# ---------------------------------------------------------------- medios de pago

def test_medios_de_pago_y_su_forma_de_pago_del_sri():
    medios = dict(choices.MEDIOS_DE_PAGO)
    assert list(medios) == ['efectivo', 'transferencia', 'deposito', 'cheque', 'tarjeta_debito', 'tarjeta_credito',
                            'compensacion', 'otro']
    assert all(len(m) <= 15 for m in medios)                                  # CharField(max_length=15) de O1 y O2
    assert set(choices.FORMA_PAGO_SRI_DE_MEDIO) == set(medios) - {'otro'}
    assert set(choices.FORMA_PAGO_SRI_DE_MEDIO.values()) <= set(dict(choices.PAYMENT_METHOD))
