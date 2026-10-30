"""Códigos de AuditLog (tenancy 0007): todo código que el código fuente registra está en AuditLog.ACTIONS con su etiqueta,
y AuditLog.detail guarda Decimal y fechas (DjangoJSONEncoder).

El recorrido lee core/ con ast y toma el código de cada llamada que crea un registro: audit(request, código, …),
AuditLog.objects.create(action=…), AuditLog(action=…) y los _auditar(…) de cada módulo (la posición del código sale de
la firma del _auditar de ese mismo módulo). Resuelve literales, `a if c else b` y variables asignadas con un literal en la
misma función; los envoltorios que reenvían su parámetro no cuentan (cuenta quien los llama). Un sitio que no se pueda
resolver hace fallar la prueba salvo que esté en SIN_LITERAL con la lista de códigos que puede recibir.
"""
import ast
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.utils import timezone

from core.proformas.servicios import TRANSICIONES
from core.tenancy.models import AuditLog, audit

BASE = Path(settings.BASE_DIR)
FUENTES = BASE / 'core'
# (archivo, función) cuyo código llega en una variable que el recorrido no resuelve → códigos que puede recibir.
SIN_LITERAL = {
    ('core/proformas/servicios.py', 'cambiar_estado'): {transicion[4] for transicion in TRANSICIONES.values()},
}
FASE_CONTABLE = (
    # Proformas
    'proforma_enviada', 'proforma_marcada_enviada', 'proforma_aceptada', 'proforma_rechazada', 'proforma_anulada',
    'proforma_eliminada', 'proforma_facturada', 'proforma_venta_eliminada',
    # Compras
    'purchase_complete', 'purchase_debt_adjust', 'purchase_delete', 'debt_payment_delete', 'debt_delete',
    'provider_type_fill',
    # Ventas
    'comprobante_anulado_sri', 'retencion_recibida_registro', 'retencion_recibida_anulacion', 'cxc_cobro_eliminado',
    'regularizacion_datos_origen',
    # D0
    'catalogo_vigencia_nueva',
)


def _posicion_en_auditar(arbol):
    """(índice, nombre) del parámetro del código en el _auditar del módulo; None si no tiene (lo fija dentro)."""
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == '_auditar':
            nombres = [a.arg for a in nodo.args.args]
            for nombre in ('accion', 'codigo', 'action'):
                if nombre in nombres:
                    return nombres.index(nombre), nombre
            return None
    return None


class _Recorrido(ast.NodeVisitor):
    def __init__(self, ruta, posicion_auditar):
        self.ruta, self.posicion = ruta, posicion_auditar
        self.funciones = []
        self.codigos = {}            # código → ['archivo:línea', …]
        self.sin_resolver = set()    # {(archivo, función)}
        self.llamadas = 0

    def visit_FunctionDef(self, nodo):
        self.funciones.append(nodo)
        self.generic_visit(nodo)
        self.funciones.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, nodo):
        encontrado, argumento = self._argumento(nodo)
        if encontrado:
            self.llamadas += 1
            self._resolver(argumento, nodo)
        self.generic_visit(nodo)

    def _argumento(self, nodo):
        funcion = nodo.func
        nombre = funcion.id if isinstance(funcion, ast.Name) else getattr(funcion, 'attr', None)
        claves = {k.arg: k.value for k in nodo.keywords if k.arg}
        texto = ast.unparse(funcion)
        if nombre == 'audit':
            return True, nodo.args[1] if len(nodo.args) > 1 else claves.get('action')
        if nombre == '_auditar' and isinstance(funcion, ast.Name):
            if self.posicion is None:
                return False, None
            indice, clave = self.posicion
            return True, nodo.args[indice] if len(nodo.args) > indice else claves.get(clave)
        if texto in ('AuditLog', 'AuditLog.objects.create', 'AuditLog.all_objects.create'):
            return True, claves.get('action')
        return False, None

    def _anotar(self, codigo, llamada):
        self.codigos.setdefault(codigo, []).append(f'{self.ruta}:{llamada.lineno}')

    def _resolver(self, argumento, llamada):
        funcion = self.funciones[-1] if self.funciones else None
        if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
            self._anotar(argumento.value, llamada)
            return
        if isinstance(argumento, ast.IfExp):
            self._resolver(argumento.body, llamada)
            self._resolver(argumento.orelse, llamada)
            return
        if isinstance(argumento, ast.Name) and funcion is not None:
            parametros = {a.arg for a in funcion.args.args + funcion.args.kwonlyargs}
            if argumento.id in parametros and funcion.name in ('_auditar', 'audit'):
                return   # el envoltorio reenvía el código que recibe
            valores = [n.value.value for n in ast.walk(funcion) if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == argumento.id for t in n.targets)
                       and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
            if valores:
                for valor in valores:
                    self._anotar(valor, llamada)
                return
        self.sin_resolver.add((self.ruta, funcion.name if funcion is not None else None))


def codigos_en_fuente():
    codigos, sin_resolver, llamadas = {}, set(), 0
    for ruta in sorted(FUENTES.rglob('*.py')):
        if 'migrations' in ruta.parts:
            continue
        arbol = ast.parse(ruta.read_text(encoding='utf-8'), filename=str(ruta))
        recorrido = _Recorrido(ruta.relative_to(BASE).as_posix(), _posicion_en_auditar(arbol))
        recorrido.visit(arbol)
        for codigo, sitios in recorrido.codigos.items():
            codigos.setdefault(codigo, []).extend(sitios)
        sin_resolver |= recorrido.sin_resolver
        llamadas += recorrido.llamadas
    return codigos, sin_resolver, llamadas


def test_todo_codigo_registrado_esta_en_actions():
    codigos, sin_resolver, llamadas = codigos_en_fuente()
    assert llamadas > 50, 'el recorrido no encontró las llamadas de auditoría'
    assert sin_resolver == set(SIN_LITERAL), f'sitios sin código literal: {sorted(sin_resolver - set(SIN_LITERAL))}'
    for sitio, posibles in SIN_LITERAL.items():
        for codigo in posibles:
            codigos.setdefault(codigo, []).append(f'{sitio[0]} ({sitio[1]})')
    acciones = dict(AuditLog.ACTIONS)
    faltan = {c: s for c, s in codigos.items() if c not in acciones}
    assert not faltan, f'códigos usados que no están en AuditLog.ACTIONS: {faltan}'
    # los de la fase se usan de verdad
    assert not set(FASE_CONTABLE) - set(codigos), sorted(set(FASE_CONTABLE) - set(codigos))
    assert 'ride_regenerado' in codigos


def test_actions_unicas_con_etiqueta_y_longitud():
    claves = [c for c, _ in AuditLog.ACTIONS]
    assert len(claves) == len(set(claves))
    maximo = AuditLog._meta.get_field('action').max_length
    assert maximo == 40
    for codigo, etiqueta in AuditLog.ACTIONS:
        assert len(codigo) <= maximo, codigo
        assert etiqueta and etiqueta != codigo, codigo
    assert set(FASE_CONTABLE) <= set(claves)


@pytest.mark.django_db
def test_detalle_con_decimal_y_fecha_se_guarda_y_se_lee(empresa):
    momento = timezone.make_aware(datetime(2026, 10, 29, 9, 30))
    audit(None, 'purchase_complete', company=empresa, total=Decimal('12.50'), fecha=date(2026, 10, 29),
          momento=momento, cambios=[{'campo': 'fecha', 'antes': date(2026, 10, 1), 'despues': Decimal('0.10')}])
    registro = AuditLog.objects.get(action='purchase_complete', company=empresa)
    registro.refresh_from_db()
    assert registro.detail['total'] == '12.50' and Decimal(registro.detail['total']) == Decimal('12.50')
    assert registro.detail['fecha'] == '2026-10-29' and date.fromisoformat(registro.detail['fecha']) == date(2026, 10, 29)
    assert datetime.fromisoformat(registro.detail['momento']) == momento
    assert registro.detail['cambios'] == [{'campo': 'fecha', 'antes': '2026-10-01', 'despues': '0.10'}]
    assert registro.get_action_display() == 'Compra: datos del comprobante completados'
