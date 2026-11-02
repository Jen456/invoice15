"""Concurrencia real en PostgreSQL de la captura rápida (core/adjuntos/capturas.py): (a) tres envíos simultáneos con la misma
clave guardan una sola captura; (b) dos personas que completan a la vez la misma captura crean un solo gasto; (c) vincular y
descartar a la vez: gana una sola transición. Transacciones reales (transaction=True) y una conexión por hilo; va al final
(test_zz_*) y crea todos sus datos, porque las pruebas transaccionales vacían la base."""
import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection, connections

from core.adjuntos import capturas as cp, servicios as sv
from core.adjuntos.models import Adjunto, Captura
from core.pos.models import Company, Expenses, TypeExpense
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, Membership
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
CODIGOS = ('view_captura', 'add_captura', 'change_captura', 'view_adjunto', 'add_adjunto', 'view_expenses', 'add_expenses')


def preparar(monkeypatch):
    empresa = Company.objects.create(ruc='0990000905001', business_name='CAPTURAS S.A.', tradename='CAPTURAS', main_address='x',
                                     establishment_address='x', establishment_code='001', issuing_point_code='001',
                                     special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                     website='https://example.com', electronic_signature_key='', email_host_user='',
                                     email_host_password='')
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(codename__in=CODIGOS))
    usuarios = []
    for n in range(3):
        usuario = User.objects.create(username=f'cap.conc.{n}', names=f'Usuario {n}', email=f'u{n}@example.com')
        usuarios.append((usuario, Membership.objects.create(user=usuario, company=empresa, group=grupo)))
    with company_context(empresa):
        tipo = TypeExpense.objects.create(name='MOVILIZACIÓN')
        gasto = Expenses.objects.create(type_expense=tipo, description='Existente', valor=Decimal('5.00'), medio_pago='efectivo')
    # Sin plan en esta base vaciada: la regla de plan se prueba en test_capturas; aquí solo los bloqueos.
    monkeypatch.setattr(cp, '_bloqueo_gasto', lambda request: None)
    monkeypatch.setattr(sv, 'permisos', lambda request, tipo: {'ver': True, 'subir': True, 'quitar': True, 'bloqueo': None})
    return empresa, usuarios, tipo, gasto


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


def test_misma_clave_una_captura(monkeypatch):
    empresa, usuarios, _, _ = preparar(monkeypatch)
    usuario, membresia = usuarios[0]

    def guardar():
        with company_context(empresa):
            captura, repetida = cp.registrar(peticion(empresa, usuario, membresia), clave='clave-simultanea-1', nota='Recibo del peaje')
            return captura.pk, repetida

    resultados, errores = en_paralelo([guardar, guardar, guardar])
    assert not errores, errores
    assert len({pk for pk, _ in resultados}) == 1 and sum(1 for _, rep in resultados if not rep) == 1
    with company_context(empresa):
        assert Captura.objects.count() == 1


def test_dos_personas_completan_la_misma_captura(monkeypatch):
    empresa, usuarios, tipo, _ = preparar(monkeypatch)
    usuario, membresia = usuarios[0]
    with company_context(empresa):
        captura, _ = cp.registrar(peticion(empresa, usuario, membresia), clave='clave-para-completar', nota='Taxi')
    datos = {'type_expense': str(tipo.pk), 'date_joined': '2026-11-02', 'valor': '8.50', 'medio_pago': 'transferencia',
             'referencia': 'T-1', 'description': 'Taxi'}

    def completar(n):
        def tarea():
            otro, otra_membresia = usuarios[n]
            with company_context(empresa):
                return cp.completar_gasto(peticion(empresa, otro, otra_membresia), captura.pk, datos)[1].pk
        return tarea

    resultados, errores = en_paralelo([completar(1), completar(2)])
    assert len(resultados) == 1 and len(errores) == 1, (resultados, errores)
    assert isinstance(errores[0], cp.ErrorCaptura) and errores[0].codigo == 'captura_usada'
    with company_context(empresa):
        assert Expenses.objects.exclude(description='Existente').count() == 1
        assert Adjunto.objects.count() == 1 and Captura.objects.get(pk=captura.pk).estado == 'completada'


def test_vincular_y_descartar_a_la_vez(monkeypatch):
    empresa, usuarios, _, gasto = preparar(monkeypatch)
    usuario, membresia = usuarios[0]
    with company_context(empresa):
        captura, _ = cp.registrar(peticion(empresa, usuario, membresia), clave='clave-vincular-descartar', nota='Parqueo')

    def vincular():
        otro, otra_membresia = usuarios[1]
        with company_context(empresa):
            return cp.vincular(peticion(empresa, otro, otra_membresia), captura.pk, 'gasto', gasto.pk)[0].estado

    def descartar():
        otro, otra_membresia = usuarios[2]
        with company_context(empresa):
            return cp.descartar(peticion(empresa, otro, otra_membresia), captura.pk, 'No corresponde').estado

    resultados, errores = en_paralelo([vincular, descartar])
    assert len(resultados) == 1 and len(errores) == 1, (resultados, errores)
    assert errores[0].codigo == 'captura_usada'
    with company_context(empresa):
        final = Captura.objects.get(pk=captura.pk)
        assert final.estado == resultados[0]
        assert Adjunto.objects.count() == (1 if final.estado == 'vinculada' else 0)
