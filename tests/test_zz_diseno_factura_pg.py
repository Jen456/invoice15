"""Diseño de factura en PostgreSQL con transacciones reales: dos guardados simultáneos del primer diseño de una empresa
terminan en una sola fila (UniqueConstraint por empresa, sin error para ninguno), cada uno queda en la auditoría, y la
seguridad por filas no deja ver ni escribir el diseño de otra empresa.

transaction=True y una conexión por hilo; se ejecuta al final (test_zz_*) y crea todos sus datos, porque las pruebas
transaccionales vacían la base al terminar. Empresas ficticias.
"""
import threading
from types import SimpleNamespace

import pytest
from django.db import DatabaseError, connection, connections, transaction

from core.configuracion import diseno as dz
from core.configuracion.models import DisenoFactura
from core.pos.models import Company
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos y RLS reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def comercio(ruc, nombre):
    return Company.objects.create(ruc=ruc, business_name=f'{nombre} S.A.', tradename=nombre, main_address='x',
                                  establishment_address='x', establishment_code='001', issuing_point_code='001',
                                  special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                  website='https://example.com', electronic_signature_key='', email_host_user='',
                                  email_host_password='')


def test_dos_primeros_guardados_simultaneos_dejan_una_fila_y_la_rls_aisla():
    rojo, azul = comercio('0990000911001', 'DISEÑO ROJO'), comercio('0990000912001', 'DISEÑO AZUL')
    usuarios = [User.objects.create(username=f'disena.{i}', names=f'disena.{i}', email=f'disena.{i}@example.com')
                for i in range(2)]
    disenos = [{'estilo': 'banda', 'color_principal': '#AA0000', 'color_secundario': '#FFEEEE'},
               {'estilo': 'compacto', 'color_principal': '#0000AA', 'color_secundario': '#EEEEFF'}]
    barrera, errores = threading.Barrier(2), []

    def guardar(i):
        try:
            peticion = SimpleNamespace(user=usuarios[i], META={})
            barrera.wait()
            with company_context(rojo):
                dz.guardar(peticion, rojo, disenos[i])
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=guardar, args=(i,)) for i in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores
    with company_context(rojo):
        filas = list(DisenoFactura.objects.values('estilo', 'color_principal', 'color_secundario'))
    assert len(filas) == 1 and filas[0] in disenos
    assert AuditLog.objects.filter(action='diseno_factura_guardado', company=rojo).count() == 2
    with company_context(azul):
        assert not DisenoFactura.all_companies.exists()   # la RLS oculta el diseño de rojo
        assert dz.diseno_guardado(rojo) is None
        # y no deja escribir en nombre de otra empresa (bulk_create salta la guardia de TenantModel.save: responde la RLS)
        with pytest.raises(DatabaseError), transaction.atomic():
            DisenoFactura.all_companies.bulk_create([DisenoFactura(company=rojo, estilo='clasico', color_principal='#CA462C',
                                                                   color_secundario='#E5F1F6')])
