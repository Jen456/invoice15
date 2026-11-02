"""Concurrencia real en PostgreSQL del kardex (core/contabilidad/servicios.py): (a) tres envíos simultáneos con la misma
clave guardan un solo movimiento manual; (b) dos anulaciones a la vez: una anula y la otra recibe 409 `ya_anulado`;
(c) dos ajustes de stock simultáneos del mismo producto quedan encadenados (el segundo parte del stock que dejó el primero)
y el kardex cuadra con el stock. Transacciones reales (transaction=True) y una conexión por hilo; va al final (test_zz_*)
y crea todos sus datos, porque las pruebas transaccionales vacían la base."""
import threading
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection, connections
from django.utils import timezone

from core.contabilidad import kardex as kx, servicios as sv
from core.contabilidad.models import AjusteInventario, MovimientoManual
from core.pos.models import Category, Company, Product
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, Membership
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
CODIGOS = ('view_kardex', 'add_movimientomanual', 'change_movimientomanual')


def preparar():
    empresa = Company.objects.create(ruc='0990000906001', business_name='KARDEX S.A.', tradename='KARDEX', main_address='x',
                                     establishment_address='x', establishment_code='001', issuing_point_code='001',
                                     special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                     website='https://example.com', electronic_signature_key='', email_host_user='',
                                     email_host_password='')
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(codename__in=CODIGOS))
    usuarios = []
    for n in range(3):
        usuario = User.objects.create(username=f'kdx.conc.{n}', names=f'Usuario {n}', email=f'k{n}@example.com')
        usuarios.append((usuario, Membership.objects.create(user=usuario, company=empresa, group=grupo)))
    with company_context(empresa):
        categoria = Category.objects.create(name='CATEGORÍA KARDEX')
        producto = Product.objects.create(name='PRODUCTO KARDEX', code='KXC1', category=categoria, price=Decimal('1.00'),
                                          pvp=Decimal('2.00'), stock=10, inventoried=True, tarifa_iva='4')
    return empresa, usuarios, producto


def peticion(empresa, usuario, membresia):
    return SimpleNamespace(user=usuario, company=empresa, membership=membresia, META={'REMOTE_ADDR': '127.0.0.1'}, method='POST')


def en_paralelo(tareas):
    """Ejecuta cada tarea en su hilo y su conexión, a la vez (barrera). Devuelve (resultados, errores)."""
    barrera, resultados, errores, cerrojo = threading.Barrier(len(tareas)), [], [], threading.Lock()

    def correr(tarea):
        try:
            barrera.wait()
            resultado = tarea()
            with cerrojo:
                resultados.append(resultado)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            with cerrojo:
                errores.append(e)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(t,)) for t in tareas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados, errores


def datos(producto, clave='kardex-simultaneo-1'):
    return {'clave': clave, 'producto': str(producto.pk), 'tipo': 'saldo_inicial', 'fecha': (timezone.localdate() - timedelta(days=3)).isoformat(),
            'cantidad': '10', 'costo_unitario': '1.50', 'documento': 'Conteo físico', 'nota': ''}


def test_misma_clave_un_movimiento():
    empresa, usuarios, producto = preparar()
    usuario, membresia = usuarios[0]

    def guardar():
        with company_context(empresa):
            movimiento, repetido = sv.registrar(peticion(empresa, usuario, membresia), datos(producto))
            return movimiento.pk, repetido

    resultados, errores = en_paralelo([guardar, guardar, guardar])
    assert not errores, errores
    assert len({pk for pk, _ in resultados}) == 1 and sum(1 for _, rep in resultados if not rep) == 1
    with company_context(empresa):
        assert MovimientoManual.objects.count() == 1


def test_dos_anulaciones_a_la_vez():
    empresa, usuarios, producto = preparar()
    with company_context(empresa):
        movimiento, _ = sv.registrar(peticion(empresa, *usuarios[0]), datos(producto, 'kardex-anular-001'))

    def anular(n):
        def tarea():
            with company_context(empresa):
                try:
                    sv.anular(peticion(empresa, *usuarios[n]), movimiento.pk, f'Duplicado {n}')
                    return 'anulado'
                except sv.ErrorKardex as e:
                    return e.codigo
        return tarea

    resultados, errores = en_paralelo([anular(1), anular(2)])
    assert not errores, errores
    assert sorted(resultados) == ['anulado', 'ya_anulado']
    with company_context(empresa):
        guardado = MovimientoManual.objects.get(pk=movimiento.pk)
    assert guardado.anulado_en is not None and guardado.motivo_anulacion in ('Duplicado 1', 'Duplicado 2')


def test_dos_ajustes_de_stock_a_la_vez_quedan_encadenados():
    empresa, usuarios, producto = preparar()

    def ajustar(nuevo, n):
        def tarea():
            with company_context(empresa):
                return sv.ajustar_stock(producto.pk, nuevo, usuarios[n][0]).stock
        return tarea

    resultados, errores = en_paralelo([ajustar(15, 0), ajustar(7, 1)])
    assert not errores, errores
    with company_context(empresa):
        primero, segundo = AjusteInventario.objects.order_by('id')
        final = Product.objects.get(pk=producto.pk).stock
        k = kx.kardex(Product.objects.get(pk=producto.pk), timezone.localdate() - timedelta(days=1), timezone.localdate())
    assert primero.anterior == 10 and segundo.anterior == primero.nuevo and final == segundo.nuevo
    assert k['saldo_final']['cantidad'] == final - 10 and k['diferencia_stock'] == 10   # el kardex solo ve los ajustes registrados
