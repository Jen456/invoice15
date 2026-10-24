"""Imagen del código de barras de los productos: una por producto (no una por cada guardado), se borra al reemplazarla
o al borrar el producto, y `manage.py limpiar_codigos_barra` limpia las huérfanas y rehace las que faltan."""
import os
import time

import pytest
from django.conf import settings
from django.core.management import call_command

from core.pos.models import Product
from core.tenancy.context import company_context
from tests import helpers
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, sri, vender, web  # noqa: F401

pytestmark = pytest.mark.django_db


def imagenes(empresa):  # noqa: F811
    raiz = os.path.join(settings.MEDIA_ROOT, 'empresas', str(empresa.uuid), 'codigos')
    return sorted(os.path.relpath(os.path.join(d, f), settings.MEDIA_ROOT) for d, _, fs in os.walk(raiz) for f in fs)


def existe(nombre):
    return os.path.exists(os.path.join(settings.MEDIA_ROOT, nombre))


def test_guardar_otra_vez_no_crea_otra_imagen(empresa):  # noqa: F811
    producto = helpers.crear_producto(empresa, 'P100')
    nombre = producto.barcode.name
    with company_context(empresa):
        for stock in (99, 98, 97):
            producto.stock = stock
            producto.save()
        producto = Product.objects.get(pk=producto.pk)
        producto.name = 'OTRO NOMBRE'
        producto.save()
    assert producto.barcode.name == nombre and imagenes(empresa) == [nombre]


def test_vender_no_deja_imagenes_nuevas(web, empresa, comprador, sri):  # noqa: F811
    producto = helpers.crear_producto(empresa, 'P200')
    antes = imagenes(empresa)
    sri.respuestas_autorizacion = ['AUTORIZADO']
    assert vender(web, comprador, producto, cantidad=3)['resp'] is True
    assert leer(empresa, lambda: Product.objects.get(pk=producto.pk).stock) == 97
    assert imagenes(empresa) == antes


def test_cambiar_el_codigo_rehace_la_imagen_y_borra_la_anterior(empresa, django_capture_on_commit_callbacks):  # noqa: F811
    producto = helpers.crear_producto(empresa, 'P300')
    anterior = producto.barcode.name
    with company_context(empresa), django_capture_on_commit_callbacks(execute=True):
        producto.code = 'P301'
        producto.save()
    assert producto.barcode.name != anterior and not existe(anterior) and imagenes(empresa) == [producto.barcode.name]


def test_si_falta_la_imagen_se_rehace_al_guardar(empresa):  # noqa: F811
    producto = helpers.crear_producto(empresa, 'P400')
    os.remove(os.path.join(settings.MEDIA_ROOT, producto.barcode.name))
    with company_context(empresa):
        producto.save()
    assert existe(producto.barcode.name) and imagenes(empresa) == [producto.barcode.name]


def test_borrar_el_producto_borra_su_imagen(empresa, django_capture_on_commit_callbacks):  # noqa: F811
    producto = helpers.crear_producto(empresa, 'P500')
    otro = helpers.crear_producto(empresa, 'P501')
    nombre = producto.barcode.name
    with company_context(empresa), django_capture_on_commit_callbacks(execute=True):
        producto.delete()
        Product.objects.filter(pk=otro.pk).delete()   # en bloque también
    assert not existe(nombre) and imagenes(empresa) == []


def test_comando_borra_huerfanas_viejas_y_rehace_las_que_faltan(empresa, empresa_b):  # noqa: F811
    usado = helpers.crear_producto(empresa, 'P600')
    sin_imagen = helpers.crear_producto(empresa, 'P601')
    ajeno = helpers.crear_producto(empresa_b, 'P602')
    carpeta = os.path.dirname(os.path.join(settings.MEDIA_ROOT, usado.barcode.name))
    vieja, reciente = os.path.join(carpeta, 'vieja.png'), os.path.join(carpeta, 'reciente.png')
    for ruta in (vieja, reciente):
        with open(ruta, 'wb') as archivo:
            archivo.write(b'png')
    hace_dos_horas = time.time() - 7200
    os.utime(vieja, (hace_dos_horas, hace_dos_horas))
    os.remove(os.path.join(settings.MEDIA_ROOT, sin_imagen.barcode.name))

    call_command('limpiar_codigos_barra')
    assert os.path.exists(vieja) and os.path.exists(reciente) and not existe(sin_imagen.barcode.name)

    call_command('limpiar_codigos_barra', '--empresa', empresa.ruc, '--aplicar')
    assert not os.path.exists(vieja) and os.path.exists(reciente)   # la reciente puede ser de un guardado en curso
    rehecho = leer(empresa, lambda: Product.objects.get(pk=sin_imagen.pk))
    assert rehecho.barcode.name != sin_imagen.barcode.name and existe(rehecho.barcode.name)
    assert existe(usado.barcode.name) and existe(ajeno.barcode.name)
