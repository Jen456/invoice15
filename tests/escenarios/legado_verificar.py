"""Comprueba el resultado de migrar una base del código original."""
import json

from core.pos.models import Category, Client, Company, Product
from core.tenancy.context import platform_scope
from core.tenancy.models import Membership

with platform_scope():
    empresa = Company.objects.get()
    resultado = {
        'empresas': Company.objects.count(),
        'uuid': bool(empresa.uuid),
        'productos_en_empresa': Product.all_companies.filter(company=empresa).count(),
        'categorias_en_empresa': Category.all_companies.filter(company=empresa).count(),
        'clientes_en_empresa': Client.all_companies.filter(company=empresa).count(),
        'roles': sorted(f'{m.user.username}:{m.group.name}' for m in Membership.objects.filter(company=empresa)),
    }
print('RESULTADO=' + json.dumps(resultado, ensure_ascii=False))
