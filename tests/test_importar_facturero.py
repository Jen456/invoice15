"""Migración desde Facturero Móvil (manage.py importar_facturero) y clientes sin teléfono o con teléfono repetido."""
import os
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from core.pos import facturero
from core.pos.forms import ClientForm
from core.pos.models import Category, Client, Product, Provider
from core.tenancy.context import company_context
from core.user.models import User
from tests import helpers

pytestmark = pytest.mark.django_db

CABECERA_PRODUCTOS = 'Cod. principal\tCod. auxiliar\tDescripcion\tTipo\tValor\tUnid. medida\tTarifa IVA\tTarifa ICE\tEstablecimiento\tCategoria\tEstado\tControl inventario\tExistencias\tPara venta\tPara compra'
CABECERA_CLIENTES = 'No\tRazon social\tTipo identificacion\tIdentificacion\tDireccion\tTelefonos\tEmail\tObservaciones'
CABECERA_PROVEEDORES = 'No\tRazon social\tTipo identificacion\tIdentificacion\tDireccion\tTelefonos\tEmail'


def reporte(tmp_path, nombre, titulo, titular, columnas, filas):
    ancho = columnas.count('\t')
    lineas = ([f'{titular}' + '\t' * ancho] if 'PRODUCTOS' in titulo else ['FACTURERO MÓVIL' + '\t' * ancho])
    lineas += [titulo + '\t' * ancho, 'Fecha de generación: 2026-10-11 15:18:30' + '\t' * ancho,
               f'Generado por: {titular}' + '\t' * ancho, '\t' * ancho, columnas]
    lineas += ['\t'.join(f) for f in filas]
    ruta = tmp_path / nombre
    ruta.write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return ruta


@pytest.fixture
def archivos(tmp_path, empresa):
    titular = empresa.business_name
    productos = reporte(tmp_path, 'productos.txt', 'REPORTE-PRODUCTOS-SERVICIOS', titular, CABECERA_PRODUCTOS, [
        ['000001', '', 'Adhesivos 30cmx30cm  REDONDOS ', 'Bien', '2.6', '', '15%', '', 'Todos', 'Ninguna', 'Activo', 'NO', '0', 'SI', 'SI'],
        ['000002', '', 'Camisetas polos negras, bordadas', 'Servicio', '9.7', '', '15%', '', 'Todos', 'Ninguna', 'Activo', 'NO', '0', 'SI', 'NO'],
        ['000003', 'AUX-9', 'Gorras traileras', 'Bien', '2.756', '', '0%', '', 'Todos', 'Gorras', 'Activo', 'SI', '12', 'SI', 'SI'],
        ['000004', '', 'Con tarifa vieja', 'Bien', '1', '', '12%', '', 'Todos', 'Ninguna', 'Activo', 'NO', '0', 'SI', 'SI'],
        ['000005', '', 'Producto inactivo', 'Bien', '1', '', '15%', '', 'Todos', 'Ninguna', 'Inactivo', 'NO', '0', 'SI', 'SI'],
    ])
    clientes = reporte(tmp_path, 'clientes.txt', 'REPORTE DE CLIENTES', titular, CABECERA_CLIENTES, [
        ['1', 'ACEROPARTES S.A.S', 'RUC', '0993385639001', 'Vía Daule km 8', '046008680', 'evillacis@aceropartes.com.ec', 'de contado'],
        ['2', 'TRACTO DIESEL CIA. LTDA.', 'RUC', '0992560541001', 'Km 7,5 vía a Daule', '046008680', 'proveedores@example.com', 'Contado'],
        ['3', 'Alimentsa S.A.', 'RUC', '0990881847001', 'Durán', '', 'a@example.com,b@example.com', 'Contado'],
        ['4', 'ARAKNE', 'RUC', '0993385134001', 'Calle Primera', '', 'facturación@mendotel.com', 'Contado'],
        ['5', 'John Villegas Delgado', 'Cedula de Identidad', '0914553755', 'Ricaurte', '04-5150410', '', 'Neto 30 dias fecha de factura'],
        ['6', 'PRILABSA LOGISTIC S,A', 'Identificación del exterior', '155652251-2-2017 DV7', 'Panamá', '', 'p@example.com', 'Contado'],
        ['7', 'RUC MAL ESCRITO', 'RUC', '0993385639', 'Guayaquil', '', '', 'Contado'],
        ['8', 'CONSUMIDOR', 'RUC', '9999999999999', 'Guayaquil', '', '', 'Contado'],
    ])
    proveedores = reporte(tmp_path, 'proveedores.txt', 'REPORTE DE PROVEEDORES', titular, CABECERA_PROVEEDORES, [
        ['1', 'ARGUELLO CORDOVA JORGE ANDRE', 'RUC', '0924649536001', 'Av. Pedro Moncayo', '', 'fe@barriochinoec.com'],
        ['2', 'OLMEDO ALVAREZ C.A.', 'RUC', '0990156174001', 'Clemente Ballén', '074078232', 'info@olmedoalvarez.com'],
        ['3', 'SIN TELEFONO TAMPOCO', 'RUC', '0990000689001', 'Guayaquil', '', 'otro@example.com'],
    ])
    return {'productos': productos, 'clientes': clientes, 'proveedores': proveedores}


def correr(empresa, archivos, *extra):
    argumentos = ['--empresa', empresa.ruc] + [a for tipo, ruta in archivos.items() for a in (f'--{tipo}', str(ruta))]
    call_command('importar_facturero', *argumentos, *extra)


def codigos_de_barra(empresa):
    raiz = settings.MEDIA_ROOT
    return [os.path.join(d, f) for d, _, fs in os.walk(raiz) for f in fs if 'codigos' in d and str(empresa.uuid) in d]


def test_el_ensayo_no_guarda_nada_ni_deja_archivos(empresa, archivos):
    antes = codigos_de_barra(empresa)
    correr(empresa, archivos)
    with company_context(empresa):
        assert (Product.objects.count(), Client.objects.count(), Provider.objects.count(), Category.objects.count()) == (0, 0, 0, 0)
    assert not User.objects.filter(username='0993385639001').exists()
    assert codigos_de_barra(empresa) == antes


def test_aplicar_crea_lo_valido_con_sus_campos(empresa, empresa_b, archivos, tmp_path):
    correr(empresa, archivos, '--aplicar', '--informe', str(tmp_path / 'informe.json'))
    with company_context(empresa):
        productos = {p.code: p for p in Product.objects.select_related('category')}
        assert sorted(productos) == ['000001', '000002', '000003']
        adhesivo = productos['000001']
        assert (adhesivo.name, adhesivo.pvp, adhesivo.price, adhesivo.tarifa_iva, adhesivo.with_tax, adhesivo.inventoried,
                adhesivo.category.name) == ('Adhesivos 30cmx30cm REDONDOS', Decimal('2.60'), Decimal('0.00'), '4', True, False, 'Bien')
        assert productos['000002'].category.name == 'Servicio'
        gorra = productos['000003']
        assert (gorra.category.name, gorra.pvp, gorra.tarifa_iva, gorra.with_tax, gorra.inventoried, gorra.stock,
                gorra.description) == ('Gorras', Decimal('2.76'), '0', False, True, 12, 'Código auxiliar: AUX-9')
        assert all(p.barcode.name for p in productos.values())

        clientes = {c.dni: c for c in Client.objects.select_related('user')}
        assert sorted(clientes) == ['0914553755', '0990881847001', '0992560541001', '0993385134001', '0993385639001',
                                    '155652251-2-2017 DV7']
        assert clientes['155652251-2-2017 DV7'].identification_type == '08'   # del exterior, hasta 20 caracteres
        assert clientes['0993385639001'].mobile == clientes['0992560541001'].mobile == '046008680'   # teléfono compartido
        assert clientes['0990881847001'].mobile == '' and clientes['0993385134001'].mobile == ''      # sin teléfono
        assert clientes['0914553755'].mobile == '045150410'
        assert (clientes['0914553755'].identification_type, clientes['0993385639001'].identification_type) == ('05', '04')
        assert clientes['0990881847001'].user.email == 'a@example.com' and clientes['0990881847001'].extra_emails == 'b@example.com'
        assert clientes['0990881847001'].correos() == ['a@example.com', 'b@example.com']
        arakne = clientes['0993385134001']
        assert arakne.user.email is None and arakne.send_email_invoice is False
        for cliente in clientes.values():
            assert cliente.user.is_active is False and not cliente.user.has_usable_password()
            assert not cliente.user.groups.exists()

        proveedores = {p.ruc: p for p in Provider.objects.all()}
        assert sorted(proveedores) == ['0924649536001', '0990156174001']
        assert (proveedores['0990156174001'].mobile, proveedores['0924649536001'].mobile) == ('074078232', '')
    with company_context(empresa_b):
        assert (Product.objects.count(), Client.objects.count(), Provider.objects.count()) == (0, 0, 0)

    informe = (tmp_path / 'informe.json').read_text(encoding='utf-8')
    for texto in ('tarifa de IVA desconocida', 'Inactivo', 'El RUC no es válido', 'consumidor final', 'facturación@mendotel.com',
                  'Neto 30 dias', 'el teléfono «vacío» ya lo tiene otro proveedor'):
        assert texto in informe, texto
    assert 'PRILABSA' not in informe and 'b@example.com' not in informe


def test_lo_que_ya_existe_no_se_toca(empresa, archivos):
    with company_context(empresa):
        categoria = Category.objects.create(name='Servicio')
        Product.objects.create(code='000001', name='Mío', category=categoria, pvp=Decimal('5.00'))
    cliente = helpers.crear_cliente('0993385639001', empresa, '0993385639001', '0990000001')
    correr(empresa, archivos, '--aplicar')
    with company_context(empresa):
        assert Product.objects.get(code='000001').name == 'Mío'
        assert Product.objects.get(code='000002').category == categoria
        assert Category.objects.filter(name='Servicio').count() == 1
        assert list(Client.objects.filter(dni='0993385639001').values_list('pk', flat=True)) == [cliente.pk]
        nuevo = Client.objects.get(dni='0992560541001')
    assert nuevo.user.username == '0992560541001'


def test_identificacion_tomada_en_otra_empresa_crea_usuario_aparte(empresa, empresa_b, archivos):
    otro = helpers.crear_cliente('0993385639001', empresa_b, '0993385639001', '0990000002')
    correr(empresa, archivos, '--aplicar')
    with company_context(empresa):
        nuevo = Client.objects.select_related('user').get(dni='0993385639001')
    assert nuevo.user_id != otro.user_id and nuevo.user.username.startswith('0993385639001-')


def test_rechaza_reportes_de_otro_titular_o_de_otro_tipo(empresa, archivos):
    otra = helpers.crear_empresa('OTRA')
    with pytest.raises(CommandError, match='titular'):
        call_command('importar_facturero', '--empresa', otra.ruc, '--productos', str(archivos['productos']))
    with pytest.raises(CommandError, match='reporte de proveedores'):
        call_command('importar_facturero', '--empresa', empresa.ruc, '--proveedores', str(archivos['clientes']))
    call_command('importar_facturero', '--empresa', otra.ruc, '--productos', str(archivos['productos']), '--otro-titular', '--aplicar')
    with company_context(otra):
        assert Product.objects.count() == 3


def test_reporte_en_windows_1252(tmp_path):
    contenido = ('FACTURERO MÓVIL\nREPORTE DE CLIENTES\nGenerado por: PEÑA\n\n' + CABECERA_CLIENTES +
                 '\n1\tJUAN PEÑA\tCedula de Identidad\t0914677265\tGuayaquil\t\t\tContado\n').encode('cp1252')
    leido = facturero.leer_reporte(contenido, 'clientes')
    assert leido.titular == 'PEÑA' and leido.filas[0]['razon social'] == 'JUAN PEÑA' and leido.filas[0]['_linea'] == 6


def test_cliente_sin_telefono_y_con_telefono_repetido_desde_el_formulario(empresa):
    helpers.crear_cliente('0993385639001', empresa, '0993385639001', '046008680')
    with company_context(empresa):
        for dni, telefono in (('0992560541001', '046008680'), ('0990881847001', ''), ('0993385134001', '')):
            formulario = ClientForm(data={'dni': dni, 'mobile': telefono, 'birthdate': '2026-01-01', 'address': 'Guayaquil',
                                          'identification_type': '04', 'send_email_invoice': ''})
            assert formulario.is_valid(), formulario.errors
            cliente = formulario.save(commit=False)
            cliente.user = User.objects.create(username=f'u-{dni}', names=dni)
            cliente.save()
        assert Client.objects.filter(mobile='').count() == 2
        assert Client.objects.filter(mobile='046008680').count() == 2
