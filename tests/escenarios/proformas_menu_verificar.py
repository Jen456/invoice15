"""Estado del menú de Proformas (módulo, grupo «Cotizaciones», permisos por rol y resto del menú) para
tests/test_migracion_proformas.py. Se ejecuta con `manage.py shell` e imprime RESULTADO=<json>."""
import json

from django.contrib.auth.models import Group

from core.security.models import Module, ModuleType

ROLES = ('Propietario', 'Administrador', 'Contador', 'Vendedor', 'Consulta', 'Cliente')
URL = '/proformas/'

modulo = Module.objects.filter(url=URL).select_related('module_type').first()
grupos = {rol: Group.objects.get(name=rol) for rol in ROLES}
resultado = {
    'modulo': None if modulo is None else {
        'nombre': modulo.name, 'icono': modulo.icon, 'orden': modulo.orden,
        'grupo': modulo.module_type.name if modulo.module_type_id else '',
        'orden_grupo': modulo.module_type.orden if modulo.module_type_id else None,
        'permisos': sorted(modulo.permissions.values_list('codename', flat=True))},
    'grupo': ModuleType.objects.filter(name='Cotizaciones').exists(),
    'permisos': {rol: sorted(g.permissions.filter(content_type__app_label='proformas').values_list('codename', flat=True))
                 for rol, g in grupos.items()},
    'en_menu': {rol: g.groupmodule_set.filter(module__url=URL).exists() for rol, g in grupos.items()},
    'resto': {
        'modulos': sorted([m.url, m.name, m.orden, m.module_type.name if m.module_type_id else '']
                          for m in Module.objects.exclude(url=URL).select_related('module_type')),
        'grupos': sorted([t.name, t.icon, t.orden] for t in ModuleType.objects.exclude(name='Cotizaciones')),
        'roles': {rol: [sorted(g.groupmodule_set.exclude(module__url=URL).values_list('module__url', flat=True)),
                        sorted(g.permissions.exclude(content_type__app_label='proformas').values_list('codename', flat=True))]
                  for rol, g in grupos.items()},
    },
}
print('RESULTADO=' + json.dumps(resultado, ensure_ascii=False))
