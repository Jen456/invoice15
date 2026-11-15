"""Convivencia de la versión publicada con la base ya migrada (decisión común 18b de contable/bloque-2-especificacion.md):
mientras `migrate` corre y hasta que el proceso nuevo atiende, el código anterior sigue escribiendo sobre las tablas que
conoce, y una vuelta de solo código lo deja atendiendo sobre la base migrada.

- Toda columna que una migración de los bloques 2 a 6 añade a una tabla que ya existía es nula o lleva `db_default`: el
  INSERT de quien no la conoce no falla (se comprueba también por SQL en `contabilidad_cuenta`).
- Ninguna tabla nueva tiene una clave foránea fuera de contabilidad salvo la empresa (introspección de la base real).
- Ninguna migración de los bloques crea una clave foránea hacia una tabla anterior a ellos (lo publicado y el bloque 1)
  fuera de la migración corta del final que solo hace eso (hallazgo C2E-1; recorrido de las operaciones, sin base).
- Borrar por SQL directo, sin los modelos nuevos de por medio, una venta, una compra, una cuenta por cobrar o por pagar,
  un producto o un usuario a los que se refieren filas contables no falla (ni al comprobar las restricciones diferidas), y
  las filas contables siguen como estaban.

Si la rama integrada con fase/primera-entrega trae ya este archivo, se amplía con estas pruebas (dependencia anotada)."""
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

from core.contabilidad.models import (AuxiliarApertura, Contabilizacion, Cuenta, EventoApertura, LineaAsiento,
                                      VinculoHistorico)
from core.pos.models import CtasCollect, DebtsPay, Product, Purchase, PurchaseDetail, Sale, SaleDetail
from core.tenancy.context import company_context
from core.user.models import User
from tests import ayuda_compras, ayudas_contables as ac, ayudas_ventas, helpers

pytestmark = pytest.mark.django_db

# Primera migración de los bloques 2 a 6 en cada app que tocan (lo anterior es de antes de la fase de cierre o del bloque 1,
# que acaba en contabilidad 0009_anular_autores_en_la_base).
DESDE = {'contabilidad': 10, 'tributario': 4}


def migraciones_de_los_bloques():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    return sorted(((app, nombre), migracion) for (app, nombre), migracion in loader.disk_migrations.items()
                  if app in DESDE and nombre[:4].isdigit() and int(nombre[:4]) >= DESDE[app])


def test_columnas_nuevas_en_tablas_existentes_son_nulas_o_con_db_default():
    bloques = migraciones_de_los_bloques()
    assert ('contabilidad', '0010_clases_de_cuenta') in {clave for clave, _ in bloques}
    creadas = {(app, op.name.lower()) for (app, _), m in bloques for op in m.operations if isinstance(op, migrations.CreateModel)}
    revisadas, malas = [], []
    for (app, nombre), migracion in bloques:
        for op in migracion.operations:
            if isinstance(op, (migrations.AddField, migrations.AlterField)) and (app, op.model_name.lower()) not in creadas:
                revisadas.append((app, op.model_name.lower(), op.name))
                if not (op.field.null or op.field.has_db_default()):
                    malas.append(f'{app}.{nombre}: {op.model_name}.{op.name}')
    assert not malas, malas
    assert {('contabilidad', 'cuenta', 'clase'), ('contabilidad', 'cuenta', 'auxiliar')} <= set(revisadas)



# Las cuatro claves hacia el usuario a las que contabilidad 0009 (bloque 1) pone ON DELETE SET NULL en PostgreSQL.
CLAVES_DE_0009 = {('cuenta', 'creada_por'), ('cuenta', 'actualizada_por'), ('importacioncuentas', 'creado_por'),
                  ('importacioncuentas', 'confirmado_por')}


def test_ninguna_migracion_de_los_bloques_cambia_las_claves_de_quien_del_plan():
    """Django 5.2 no conoce la acción que pone 0009: un AlterField (o quitar o renombrar uno de esos campos) en una migración
    posterior recrearía la restricción sin ella, y borrar a un usuario que creó cuentas en otra empresa volvería a fallar
    con la seguridad por filas (tests/test_cuentas.py::TestBorrarAlAutor lo comprueba en PostgreSQL con todo migrado). La
    migración que tenga que cambiarlas debe volver a ponerla, como hace 0009, y entonces se quita de esta prueba."""
    tocadas = []
    for (app, nombre), migracion in migraciones_de_los_bloques():
        for op in migracion.operations:
            if app == 'contabilidad' and isinstance(op, (migrations.AlterField, migrations.RemoveField, migrations.RenameField)):
                campo = op.old_name if isinstance(op, migrations.RenameField) else op.name
                if (op.model_name.lower(), campo.lower()) in CLAVES_DE_0009:
                    tocadas.append(f'{app}.{nombre}: {type(op).__name__} {op.model_name}.{campo}')
    assert not tocadas, tocadas


def _apunta_a(app, campo):
    """(app, modelo en minúsculas) al que apunta un campo de relación tal como lo escribe la migración."""
    destino = campo.remote_field.model
    etiqueta = destino if isinstance(destino, str) else destino._meta.label
    app_destino, modelo = etiqueta.split('.') if '.' in etiqueta else (app, etiqueta)
    return app_destino, modelo.lower()


SQL_DE_CLAVE = re.compile(r'\bFOREIGN\s+KEY\b|\bREFERENCES\b', re.IGNORECASE)


def test_claves_hacia_tablas_anteriores_solo_en_la_migracion_corta_del_final():
    """Hallazgo C2E-1 (ensayo del corte 1 con e0f2902 atendiendo): en PostgreSQL, cada clave foránea hacia una tabla que
    ya existía toma `ShareRowExclusiveLock` sobre ella (choca con toda escritura) desde que se crea hasta que la migración
    confirma, y Django crea las de un `CreateModel` al final, entre los índices de la migración: 0011 y 0012 retenían
    así `pos_company` 6 y 12 s y `contabilidad_movimientomanual` 8 s. Ahora la migración que crea la tabla las aplaza
    (`AplazarClaves`, core/contabilidad/migrations/_claves_aplazadas.py) y las crea otra que solo hace eso
    (`CrearClavesAplazadas`), detrás. «Anterior» es toda tabla que no crea un `CreateModel` de los bloques 2 a 6 (la
    empresa, el usuario, la operación, el kardex, el plan de cuentas del bloque 1...), como en la prueba de las columnas.

    Falla si una migración de los bloques: crea en un `CreateModel` una clave (o una ManyToMany) hacia una tabla anterior
    sin aplazarla; la añade o la cambia con `AddField` o `AlterField` (en PostgreSQL va en línea y bloquea en el acto);
    tiene SQL con FOREIGN KEY o REFERENCES (RunSQL o RunPython) fuera de la migración corta; aplaza lo que no es una clave
    hacia una tabla anterior de un `CreateModel` suyo; o si lo aplazado y lo creado al final no coinciden, la migración
    corta no va sola o va antes que lo que aplaza. tests/test_zz_claves_anteriores_pg.py mide los bloqueos de verdad."""
    bloques = migraciones_de_los_bloques()
    creadas = {(app, op.name.lower()) for (app, _), m in bloques for op in m.operations
               if isinstance(op, migrations.CreateModel)}
    malas, aplazadas, al_final = [], {}, {}
    for (app, nombre), migracion in bloques:
        operaciones = migracion.operations
        aqui = {clave for op in operaciones if type(op).__name__ == 'AplazarClaves' for clave in op.claves}
        hacia_anteriores = set()
        for op in operaciones:
            tipo = type(op).__name__
            if tipo == 'CrearClavesAplazadas':
                if len(operaciones) != 1:
                    malas.append(f'{app}.{nombre}: CrearClavesAplazadas no va sola en su migración')
                al_final.update({(app, *clave): nombre for clave in op.claves})
            elif tipo == 'AplazarClaves':
                aplazadas.update({(app, *clave): nombre for clave in op.claves})
            elif isinstance(op, (migrations.CreateModel, migrations.AddField, migrations.AlterField)):
                crea = isinstance(op, migrations.CreateModel)
                modelo = (op.name if crea else op.model_name).lower()
                for campo_nombre, campo in (op.fields if crea else [(op.name, op.field)]):
                    if not campo.is_relation or not getattr(campo, 'db_constraint', True):
                        continue
                    destino = _apunta_a(app, campo)
                    if destino in creadas:
                        continue
                    hacia_anteriores.add((modelo, campo_nombre))
                    if not (crea and not campo.many_to_many and (modelo, campo_nombre) in aqui):
                        malas.append(f'{app}.{nombre}: {tipo} {modelo}.{campo_nombre} → {".".join(destino)} sin aplazar')
        malas += [f'{app}.{nombre}: AplazarClaves nombra {m}.{c}, que no es una clave hacia una tabla anterior de un '
                  'CreateModel de esta migración' for m, c in sorted(aqui - hacia_anteriores)]
        if not any(type(op).__name__ == 'CrearClavesAplazadas' for op in operaciones):
            if SQL_DE_CLAVE.search(Path(sys.modules[type(migracion).__module__].__file__).read_text()):
                malas.append(f'{app}.{nombre}: SQL con FOREIGN KEY o REFERENCES fuera de la migración corta')
    malas += [f'{".".join(clave)}: aplazada en {aplazadas.get(clave)}, creada al final en {al_final.get(clave)}'
              for clave in sorted(set(aplazadas) ^ set(al_final))]
    malas += [f'{".".join(clave)}: se crea en {nombre}, que no va detrás de {aplazadas[clave]}'
              for clave, nombre in sorted(al_final.items()) if clave in aplazadas and nombre <= aplazadas[clave]]
    assert not malas, malas
    # Las del corte 1 del bloque 2: la empresa en las 19 tablas, el plan de cuentas en seis y el kardex en una.
    del_corte = {clave for clave, nombre in al_final.items() if nombre == '0016_claves_hacia_tablas_anteriores'}
    assert len(del_corte) == 26 and {('contabilidad', 'asiento', 'company'), ('contabilidad', 'lineaasiento', 'cuenta'),
                                     ('contabilidad', 'auxiliarapertura', 'movimiento_kardex')} <= del_corte


def test_insert_que_no_conoce_las_columnas_nuevas_de_cuenta(empresa):
    with company_context(empresa), connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO {Cuenta._meta.db_table} (company_id, codigo, codigo_norm, nombre, tipo, activa, version, '
                       "creada_en, actualizada_en) VALUES (%s, 'V1', 'v1', 'De la versión anterior', 'movimiento', %s, 1, "
                       '%s, %s)', [empresa.pk, True, date(2026, 1, 1), date(2026, 1, 1)])
        assert Cuenta.objects.filter(codigo='V1').values_list('clase', 'auxiliar').get() == ('', '')


def test_ninguna_clave_foranea_fuera_de_contabilidad_salvo_la_empresa():
    fuera = []
    with connection.cursor() as cursor:
        for modelo in ac.MODELOS_DEL_BLOQUE:
            tabla = modelo._meta.db_table
            for nombre, restriccion in connection.introspection.get_constraints(cursor, tabla).items():
                if restriccion['foreign_key']:
                    destino = restriccion['foreign_key'][0]
                    if not (destino.startswith('contabilidad_') or destino == 'pos_company'):
                        fuera.append(f'{tabla}.{restriccion["columns"]} → {destino}')
    assert not fuera, fuera


def borrar(modelo, **filtro):
    """DELETE por SQL directo, sin el colector de Django ni los modelos nuevos."""
    columna, valor = next(iter(filtro.items()))
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {modelo._meta.db_table} WHERE {columna} = %s', [valor])
        return cursor.rowcount


def test_borrar_por_sql_lo_operativo_referido_no_falla(empresa, admin):
    filas = ac.filas_de_cada_tabla(empresa)
    cuentas, apertura = filas['cuentas'], filas['apertura']
    cliente = helpers.crear_cliente('cliente.convivencia', empresa, dni='0912345670', movil='0990000123')
    producto_venta, producto = helpers.crear_producto(empresa, codigo='CONV-V'), helpers.crear_producto(empresa, codigo='CONV-P')
    venta = ayudas_ventas.factura_autorizada(empresa, cliente, admin, producto_venta, credito=True)
    cxc = ayudas_ventas.cxc_de(venta)
    proveedor = ayuda_compras.crear_proveedor(empresa)
    compra = ayuda_compras.compra_antigua(empresa, proveedor, '40.00', credito=True, producto=producto_venta)
    autor = User.objects.create(username='autor.convivencia', names='Autor', email='autor.conv@example.com')
    escrito_por = dict(creado_por_id=autor.pk, creado_por_nombre=autor.username)
    with company_context(empresa):
        cxp = DebtsPay.objects.get(purchase=compra)
        referidas = [
            AuxiliarApertura.objects.create(
                apertura=apertura, linea=filas['linea_apertura'], cuenta=cuentas['clientes'], naturaleza='cliente',
                saldo_inicial=Decimal('23.00'), tercero_identificacion=cliente.dni, tercero_nombre='CLIENTE FICTICIO',
                cliente_id=cliente.pk, cxc_id=cxc.pk, documento_tipo='01', documento_numero=venta.voucher_number_full,
                **escrito_por),
            AuxiliarApertura.objects.create(
                apertura=apertura, linea=filas['auxiliar_proveedor'].linea, cuenta=cuentas['proveedores'],
                naturaleza='proveedor', saldo_inicial=Decimal('40.00'), tercero_identificacion=proveedor.ruc,
                tercero_nombre='PROVEEDOR FICTICIO', proveedor_id=proveedor.pk, cxp_id=cxp.pk, documento_tipo='01',
                documento_numero=compra.number, **escrito_por),
            AuxiliarApertura.objects.create(
                apertura=apertura, linea=filas['linea_apertura'], cuenta=cuentas['clientes'], naturaleza='inventario',
                saldo_inicial=Decimal('5.00'), producto_id=producto.pk, producto_codigo=producto.code,
                producto_nombre=producto.name, cantidad=1, costo_unitario=Decimal('5.000000'), **escrito_por),
            Contabilizacion.objects.create(origen_tipo='compra', origen_id=compra.pk, evento='registro', **escrito_por),
            VinculoHistorico.objects.create(documento_importado_id=venta.pk, destino='consulta', clave=ac.clave(),
                                            decidido_por_id=autor.pk, decidido_por_nombre=autor.username),
            EventoApertura.objects.create(apertura=apertura, accion='prueba', usuario_id=autor.pk, usuario_nombre=autor.username),
        ]
    tercero = dict(tercero_tipo='cliente', tercero_id=cliente.pk, tercero_identificacion=cliente.dni,
                   tercero_nombre='CLIENTE FICTICIO', documento_tipo='venta', documento_id=venta.pk,
                   documento_numero=venta.voucher_number_full)
    referidas.append(ac.asiento_directo(empresa, [(cuentas['clientes'], '23.00', 0, tercero), (cuentas['ventas'], 0, '23.00')],
                                        tipo='origen', origen=('venta', venta.pk, 'emision'), autor=ac.autor(autor)))

    def como_estan():
        filas_ahora = [type(r).objects.filter(pk=r.pk).values().get() for r in referidas]
        return filas_ahora, list(LineaAsiento.objects.filter(asiento=referidas[-1]).order_by('orden').values())
    with company_context(empresa):
        antes = como_estan()
        assert antes[1][0]['tercero_id'] == cliente.pk and antes[1][0]['documento_id'] == venta.pk
        # Lo operativo, en el orden de sus propias dependencias (las de la operación sí existen y se respetan).
        assert borrar(CtasCollect, id=cxc.pk) == 1
        assert borrar(DebtsPay, id=cxp.pk) == 1
        borrar(SaleDetail, sale_id=venta.pk)
        assert borrar(Sale, id=venta.pk) == 1
        borrar(PurchaseDetail, purchase_id=compra.pk)
        assert borrar(Purchase, id=compra.pk) == 1
        assert borrar(Product, id=producto.pk) == 1
    assert borrar(User, id=autor.pk) == 1
    connection.check_constraints()   # las claves foráneas diferidas tampoco ven nada roto
    with company_context(empresa):
        assert como_estan() == antes
        assert not Sale.objects.filter(pk=venta.pk).exists() and not Product.objects.filter(pk=producto.pk).exists()
