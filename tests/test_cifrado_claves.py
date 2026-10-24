"""Clave de la firma electrónica (.p12) cifrada en la base (core/tenancy/cifrado.py): en la base solo queda 'fernet:<token>',
el modelo la entrega en claro, las anteriores al cambio se leen y se cifran al guardar, la rotación de llaves funciona y una
llave equivocada no borra las claves guardadas."""
import importlib
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from django.apps import apps
from django.core.checks import run_checks
from django.core.management import CommandError, call_command
from django.db import connection

from core.pos.forms import CompanyForm
from core.pos.models import Company
from core.tenancy import cifrado
from core.tenancy.context import platform_scope
from tests import helpers

pytestmark = pytest.mark.django_db
CLAVE = 'Clave de la Firma 2026!'


def guardado(empresa):
    """Lo que hay en la columna, sin pasar por el modelo."""
    with platform_scope(), connection.cursor() as cursor:
        cursor.execute(f'SELECT electronic_signature_key FROM {Company._meta.db_table} WHERE id = %s', [empresa.pk])
        return cursor.fetchone()[0]


def poner_en_la_base(empresa, valor):
    with platform_scope(), connection.cursor() as cursor:
        cursor.execute(f'UPDATE {Company._meta.db_table} SET electronic_signature_key = %s WHERE id = %s', [valor, empresa.pk])


@pytest.fixture
def empresa():
    empresa = helpers.crear_empresa('CIFRADA')
    empresa.electronic_signature_key = CLAVE
    empresa.save()
    return empresa


def releer(empresa):
    return Company.objects.get(pk=empresa.pk)


class TestCifrado:

    def test_en_la_base_queda_cifrada_y_el_modelo_la_entrega_en_claro(self, empresa):
        crudo = guardado(empresa)
        assert crudo.startswith('fernet:') and CLAVE not in crudo
        assert releer(empresa).electronic_signature_key == CLAVE
        empresa.save()
        assert guardado(empresa) != crudo and releer(empresa).electronic_signature_key == CLAVE   # cada cifrado es distinto

    def test_vacia_se_guarda_vacia(self):
        empresa = helpers.crear_empresa('SIN CLAVE')
        assert guardado(empresa) == '' and releer(empresa).electronic_signature_key == ''
        assert Company.objects.filter(pk=empresa.pk, electronic_signature_key='').exists()

    def test_clave_anterior_sin_cifrar_se_lee_y_se_cifra_al_guardar(self, empresa):
        poner_en_la_base(empresa, CLAVE)
        anterior = releer(empresa)
        assert anterior.electronic_signature_key == CLAVE
        anterior.save()
        assert guardado(empresa).startswith('fernet:') and releer(empresa).electronic_signature_key == CLAVE

    def test_rotacion_de_llaves(self, empresa, settings, capsys):
        vieja = settings.FPA_CLAVES_CIFRADO[0]
        nueva = Fernet.generate_key().decode()
        settings.FPA_CLAVES_CIFRADO = [nueva, vieja]          # la nueva cifra; la vieja aún descifra
        assert releer(empresa).electronic_signature_key == CLAVE
        call_command('claves_firma', '--recifrar')
        assert 'cifradas 1' in capsys.readouterr().out
        settings.FPA_CLAVES_CIFRADO = [nueva]                 # ya sin la vieja
        assert releer(empresa).electronic_signature_key == CLAVE

    def test_llave_equivocada_no_borra_la_clave(self, empresa, settings):
        crudo, original = guardado(empresa), list(settings.FPA_CLAVES_CIFRADO)
        settings.FPA_CLAVES_CIFRADO = [Fernet.generate_key().decode()]
        ilegible = releer(empresa)
        assert ilegible.electronic_signature_key == '' and not ilegible.electronic_signature_key   # como si faltara
        ilegible.tradename = 'OTRO NOMBRE'
        ilegible.save()
        form = CompanyForm(instance=releer(empresa))
        form.cleaned_data = {'electronic_signature_key': ''}
        assert form.clean_electronic_signature_key().crudo == crudo        # el formulario también la conserva
        with pytest.raises(CommandError, match='no se pueden descifrar'):
            call_command('claves_firma')
        assert guardado(empresa) == crudo
        settings.FPA_CLAVES_CIFRADO = original                              # con la llave correcta, la clave sigue ahí
        assert releer(empresa).electronic_signature_key == CLAVE

    def test_informe_sin_mostrar_claves(self, empresa, capsys):
        otra = helpers.crear_empresa('ANTERIOR')
        poner_en_la_base(otra, 'clave-vieja')
        call_command('claves_firma')
        salida = capsys.readouterr().out
        assert 'cifradas 1' in salida and 'sin cifrar 1' in salida and CLAVE not in salida and 'clave-vieja' not in salida


class TestMigracion:

    def test_cifra_las_existentes_y_al_revertir_las_deja_en_claro(self, empresa):
        migracion = importlib.import_module('core.pos.migrations.0017_clave_firma_cifrada')
        poner_en_la_base(empresa, CLAVE)
        with platform_scope():
            migracion.cifrar(apps, None)
        assert guardado(empresa).startswith('fernet:') and releer(empresa).electronic_signature_key == CLAVE
        with platform_scope():
            migracion.descifrar(apps, SimpleNamespace(connection=connection))
        assert guardado(empresa) == CLAVE


class TestConfiguracion:

    def test_sin_llave_el_servidor_no_arranca(self, settings):
        settings.FPA_CLAVES_CIFRADO = []
        assert 'fpa.E002' in [e.id for e in run_checks()]
        with pytest.raises(Exception, match='FPA_CLAVES_CIFRADO'):
            cifrado.cifrar('x')

    def test_llave_invalida(self, settings):
        settings.FPA_CLAVES_CIFRADO = ['no-es-una-llave']
        assert 'fpa.E003' in [e.id for e in run_checks()]

    def test_en_desarrollo_avisa_y_usa_una_llave_derivada(self, settings):
        settings.FPA_CLAVES_CIFRADO, settings.DEBUG = [], True
        assert 'fpa.W002' in [e.id for e in run_checks()]
        assert cifrado.descifrar(cifrado.cifrar(CLAVE)) == CLAVE
