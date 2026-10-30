"""Códigos de AuditLog (tenancy 0007): todo código que el código fuente registra está en AuditLog.ACTIONS con su etiqueta,
y AuditLog.detail guarda Decimal y fechas (DjangoJSONEncoder).

El recorrido lee core/ con ast y toma el código de cada llamada que crea un registro: audit(request, código, …),
AuditLog(action=…), AuditLog.<gestor>.create / get_or_create / update_or_create(action=…), también con los alias de
importación (`audit as …`, `AuditLog as …`), y el _auditar(…) que cada módulo define en su nivel superior (la posición del
código sale de su firma: accion, codigo o action). Resuelve literales, `a if c else b` y variables asignadas con un literal
en la misma función. Solo dos envoltorios pueden reenviar el código que reciben (cuenta quien los llama): ese _auditar, con
el parámetro de su firma, y audit() de core/tenancy/models.py, con `action`. Todo lo demás que no resuelva hace fallar la
prueba salvo que esté en SIN_LITERAL con la lista de códigos que puede recibir: un _auditar llamado como atributo
(self._auditar, otro_modulo._auditar) o importado de otro módulo, un _auditar sin parámetro de código reconocible que
reenvía uno, un envoltorio que reenvía otro parámetro, argumentos con * o ** y bulk_create. TestRecorrido lo comprueba sobre
fuentes de ejemplo.
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
RUTA_AUDIT = 'core/tenancy/models.py'          # donde vive audit(), que reenvía su parámetro `action`
NOMBRES_CODIGO = ('accion', 'codigo', 'action')
CREAR = ('create', 'get_or_create', 'update_or_create')
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


def _envoltorio_del_modulo(arbol):
    """(función, (índice, nombre) del parámetro del código) del _auditar del nivel superior del módulo; la posición es None
    si su firma no tiene accion, codigo ni action (fija el código dentro), y (None, None) si el módulo no define uno."""
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == '_auditar':
            nombres = [a.arg for a in nodo.args.args]
            for nombre in NOMBRES_CODIGO:
                if nombre in nombres:
                    return nodo, (nombres.index(nombre), nombre)
            return nodo, None
    return None, None


def _alias(arbol, nombre):
    """Nombres con que el módulo usa `nombre`: el propio y los de cada `from … import nombre as otro`."""
    nombres = {nombre}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            nombres |= {a.asname for a in nodo.names if a.name == nombre and a.asname}
    return nombres


class _Recorrido(ast.NodeVisitor):
    def __init__(self, ruta, arbol):
        self.ruta = ruta
        self.envoltorio, self.posicion = _envoltorio_del_modulo(arbol)
        self.audit_base = next((n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == 'audit'),
                               None) if ruta == RUTA_AUDIT else None
        self.nombres_audit, self.nombres_modelo = _alias(arbol, 'audit'), _alias(arbol, 'AuditLog')
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
        """(¿crea un registro?, nodo del código o None si no se sabe dónde va)."""
        funcion = nodo.func
        nombre = funcion.id if isinstance(funcion, ast.Name) else getattr(funcion, 'attr', None)
        claves = {k.arg: k.value for k in nodo.keywords if k.arg}
        partes = ast.unparse(funcion).split('.')
        if nombre in self.nombres_audit:
            return True, nodo.args[1] if len(nodo.args) > 1 else claves.get('action')
        if nombre == '_auditar':
            if not isinstance(funcion, ast.Name) or self.envoltorio is None:
                return True, None    # método, otro módulo o importado: el recorrido no conoce esa firma
            if self.posicion is None:
                return False, None   # el _auditar del módulo fija el código dentro (su cuerpo también se recorre)
            indice, clave = self.posicion
            return True, nodo.args[indice] if len(nodo.args) > indice else claves.get(clave)
        if partes[0] in self.nombres_modelo and (len(partes) == 1 or partes[-1] in CREAR):
            return True, claves.get('action')
        if partes[0] in self.nombres_modelo and partes[-1] == 'bulk_create':
            return True, None
        return False, None

    def _anotar(self, codigo, llamada):
        self.codigos.setdefault(codigo, []).append(f'{self.ruta}:{llamada.lineno}')

    def _reenvia(self, funcion, parametro):
        """True solo si `funcion` es uno de los dos envoltorios y `parametro` es el del código en su firma."""
        if funcion is self.envoltorio and self.posicion is not None:
            return parametro == self.posicion[1]
        return funcion is self.audit_base and parametro == 'action'

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
            if argumento.id in parametros and self._reenvia(funcion, argumento.id):
                return   # el envoltorio reenvía el código que recibe
            valores = [n.value.value for n in ast.walk(funcion) if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == argumento.id for t in n.targets)
                       and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
            if valores:
                for valor in valores:
                    self._anotar(valor, llamada)
                return
        self.sin_resolver.add((self.ruta, funcion.name if funcion is not None else None))


def recorrer(texto, ruta):
    arbol = ast.parse(texto, filename=ruta)
    recorrido = _Recorrido(ruta, arbol)
    recorrido.visit(arbol)
    return recorrido


def codigos_en_fuente():
    codigos, sin_resolver, llamadas = {}, set(), 0
    for ruta in sorted(FUENTES.rglob('*.py')):
        if 'migrations' in ruta.parts:
            continue
        recorrido = recorrer(ruta.read_text(encoding='utf-8'), ruta.relative_to(BASE).as_posix())
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


# ------------------------------------------------------------------ el propio recorrido, sobre fuentes de ejemplo

PUNTOS_CIEGOS = {
    'metodo_auditar': '''
from core.tenancy.models import audit
class Revision:
    def _auditar(self, request, accion):
        audit(request, accion)
    def cerrar(self, request):
        self._auditar(request, 'codigo_fantasma_metodo')
''',
    'parametro_con_otro_nombre': '''
from core.tenancy.models import audit
def _auditar(request, evento):
    audit(request, evento)
def cerrar(request):
    _auditar(request, 'codigo_fantasma_evento')
''',
    'reenvia_otro_parametro': '''
from core.tenancy.models import audit
def _auditar(request, accion, company, otro=''):
    audit(request, otro, company)
def cerrar(request, company):
    _auditar(request, 'codigo_fantasma_registrado', company, otro='codigo_fantasma_otro')
''',
    'auditar_de_otro_modulo': '''
from core.pos import compras
def cerrar(request, company):
    compras._auditar(request, 'codigo_fantasma_ajeno', company)
''',
    'auditar_importado': '''
from core.pos.compras import _auditar
def cerrar(request, company):
    _auditar(request, 'codigo_fantasma_importado', company)
''',
    'audit_con_kwargs': '''
from core.tenancy.models import audit
def cerrar(request, datos):
    audit(request, **datos)
''',
    'bulk_create': '''
from core.tenancy.models import AuditLog
def cerrar(registros):
    AuditLog.objects.bulk_create(registros)
''',
}


class TestRecorrido:
    """El recorrido no deja pasar en silencio un sitio que no entiende (X-R3): o lo resuelve o lo anota sin resolver."""

    @pytest.mark.parametrize('fuente', PUNTOS_CIEGOS.values(), ids=list(PUNTOS_CIEGOS))
    def test_un_sitio_que_no_entiende_queda_sin_resolver(self, fuente):
        recorrido = recorrer(fuente, 'core/sonda.py')
        assert recorrido.sin_resolver, f'pasó en silencio; códigos leídos: {sorted(recorrido.codigos)}'

    def test_sigue_los_alias_de_audit_y_de_auditlog(self):
        recorrido = recorrer('''
from core.tenancy.models import AuditLog as Registro, audit as registrar
def cerrar(request):
    registrar(request, 'codigo_alias_audit')
    Registro.objects.create(action='codigo_alias_modelo')
    Registro(action='codigo_alias_constructor').save()
''', 'core/sonda.py')
        assert set(recorrido.codigos) == {'codigo_alias_audit', 'codigo_alias_modelo', 'codigo_alias_constructor'}
        assert not recorrido.sin_resolver

    def test_resuelve_el_envoltorio_del_modulo_y_sus_llamadas(self):
        recorrido = recorrer('''
from core.tenancy.models import AuditLog, audit
def _auditar(request, usuario, company, accion, **detalle):
    if request is not None:
        audit(request, accion, company=company, **detalle)
    else:
        AuditLog.objects.create(user=usuario, company=company, action=accion, detail=detalle)
def cerrar(request, usuario, company, total):
    _auditar(request, usuario, company, 'codigo_literal')
    _auditar(request, usuario, company, 'codigo_a' if total else 'codigo_b')
    codigo = 'codigo_variable'
    _auditar(request, usuario, company, accion=codigo)
''', 'core/sonda.py')
        assert set(recorrido.codigos) == {'codigo_literal', 'codigo_a', 'codigo_b', 'codigo_variable'}
        assert not recorrido.sin_resolver and recorrido.llamadas == 5

    def test_un_envoltorio_que_fija_el_codigo_dentro(self):
        recorrido = recorrer('''
from core.tenancy.models import audit
def _auditar(request, company, **detalle):
    audit(request, 'codigo_fijo', company=company, **detalle)
def cerrar(request, company):
    _auditar(request, company, motivo='x')
''', 'core/sonda.py')
        assert set(recorrido.codigos) == {'codigo_fijo'} and not recorrido.sin_resolver
