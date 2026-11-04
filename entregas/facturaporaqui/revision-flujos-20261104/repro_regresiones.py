"""Regresión propuesta para Claude. Solo datos ficticios, SQLite y API local de pruebas.

Ejecutar desde la raíz con: python RUTA/repro_empresa_cliente.py
Usa un archivo temporal dentro de tests para heredar sus fixtures normales;
lo elimina al finalizar. No forma parte de la suite por defecto.
"""
if __name__ == '__main__':
    import os
    import sys
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='_auditoria_',suffix='.py',dir=Path.cwd()/'tests',delete=False) as target:
        target.write(Path(__file__).read_text())
        temporary = Path(target.name)
    try:
        result = subprocess.run([sys.executable,'-m','pytest','-q',str(temporary)],env={**os.environ,'DJANGO_SETTINGS_MODULE':'config.settings_test','FPA_TEST_DATABASE_URL':'sqlite://:memory:'})
    finally:
        temporary.unlink()
    raise SystemExit(result.returncode)

import re
import pytest
from django.core.cache import cache
from core.pos.models import Client
from core.tenancy.context import company_context
from core.tenancy.models import Membership
from tests import helpers

pytestmark = pytest.mark.django_db
URL = '/pos/sale/admin/add/'
PAYLOAD = {
    'action': 'create_client', 'identification_type': '04', 'dni': '0992560541001',
    'names': 'CLIENTE FICTICIO DE AUDITORIA', 'address': 'Direccion ficticia',
    'mobile': '0990000011', 'email': 'cliente@example.test', 'birthdate': '', 'extra_emails': ''
}


@pytest.fixture(autouse=True)
def limpiar_cache(db):
    # Al cargar el conftest como plugin, fijar expresamente la dependencia de BD.
    cache.clear()
    yield
    cache.clear()


def test_alta_en_empresa_actual_sigue_funcionando(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    response = client.post(URL, {**PAYLOAD, 'empresa': empresa.pk})
    assert response.status_code == 200
    assert response.json().get('id'), response.json()
    with company_context(empresa):
        assert Client.objects.filter(dni=PAYLOAD['dni']).count() == 1


def test_alta_rapida_conserva_empresa_en_el_formulario(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    html = client.get(URL).content.decode()
    modal = re.search(r'<form\b[^>]*\bid="frmClient"[^>]*>(.*?)</form>', html, re.S).group(1)
    assert re.search(r'name=["\']empresa["\']', modal), 'El formulario de alta rápida no conserva la empresa de origen'


def test_otra_pestana_no_crea_cliente_en_empresa_equivocada(client, empresa, empresa_b, admin):
    group = Membership.objects.get(user=admin, company=empresa).group
    Membership.objects.create(user=admin, company=empresa_b, group=group)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    assert client.get(URL).status_code == 200
    client.post('/empresas/cambiar/', {'company': empresa_b.pk})
    assert client.session['company_id'] == empresa_b.pk
    # Incluso si la interfaz enviara la empresa original, el backend hoy la ignora.
    response = client.post(URL, {**PAYLOAD, 'empresa': empresa.pk})
    with company_context(empresa):
        in_a = Client.objects.filter(dni=PAYLOAD['dni']).count()
    with company_context(empresa_b):
        in_b = Client.objects.filter(dni=PAYLOAD['dni']).count()
    assert (response.status_code, in_a, in_b) == (409, 0, 0), {
        'status':response.status_code, 'clientes_en_A':in_a, 'clientes_en_B':in_b
    }


def test_consulta_no_modifica_productos_importando_excel(client, empresa):
    from io import BytesIO
    from decimal import Decimal
    from openpyxl import Workbook
    from django.core.files.uploadedfile import SimpleUploadedFile
    from core.tenancy.models import ROLE_READONLY
    from core.pos.models import Product
    usuario = helpers.crear_usuario('consulta.ficticia.auditoria', empresa, ROLE_READONLY)
    assert not Membership.objects.get(user=usuario, company=empresa).group.permissions.filter(codename='change_product').exists()
    producto = helpers.crear_producto(empresa, 'AUD-PROD-01')
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    book = Workbook()
    book.active.append(['Id','Nombre','Codigo','Categoria','Costo','PVP','Stock','Inventariado','IVA','Tarifa'])
    book.active.append([producto.pk,producto.name,producto.code,'CATEGORIA FICTICIA',5,19.99,100,'no','si','15%'])
    buf = BytesIO()
    book.save(buf)
    response = client.post('/pos/product/', {'action':'upload_excel', 'archive':SimpleUploadedFile('catalogo-ficticio.xlsx',buf.getvalue())})
    with company_context(empresa):
        precio = Product.objects.get(pk=producto.pk).pvp
    assert (response.status_code, precio) == (403, Decimal('10.00')), {
        'status':response.status_code, 'precio_anterior':'10.00','precio_posterior':str(precio),
        'body':response.content.decode()
    }
