"""Local-only rendering of real templates; isolated in-memory test settings."""
import os
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('/tmp/facturacion15-preview')
RUNTIME.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_workflow_test'
import django
django.setup()
from django.conf import settings
settings.TEMPLATES[0]['DIRS'].insert(0, REPO / 'frontend_tests/templates')
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory
from core.pos.forms import SaleForm, ClientUserForm, ClientForm, SaleQuickProductForm
from core.pos.models import Category

call_command('migrate', run_syncdb=True, verbosity=0)
Category.objects.create(name='Productos de ejemplo')
request = RequestFactory().get('/sale/add/')
form = SaleForm(initial={'payment_type': 'efectivo', 'date_joined': '2026-11-03', 'end_credit': '2026-11-18', 'receipt': '01', 'payment_method': '20', 'time_limit': 0})
output = render_to_string('sale/admin/create.html', {
    'menu': 'preview-shell.html', 'request': request, 'form': form,
    'frmUser': ClientUserForm(), 'frmClient': ClientForm(), 'frmQuickProduct': SaleQuickProductForm(),
    'company': {'iva': 15}, 'dashboard': {'card': 'card-default', 'author': 'Vista de prueba', 'get_image': '/static/img/brand/isotipo-pie.png'},
    'can_create_product': True, 'action': 'add', 'title': 'Nueva factura', 'list_url': '/sale/',
    'final_consumer': json.dumps({'id': 999, 'text': 'Cliente ficticio — prueba de interfaz', 'identification_type': {'id': '04'}})
}, request=request)
(RUNTIME / 'site').mkdir(exist_ok=True)
(RUNTIME / 'site' / 'factura.html').write_text(output)
print('Rendered real invoice template with fictitious data.')
