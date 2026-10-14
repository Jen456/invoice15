"""Presentation contracts that must survive frontend/backend integration."""
from html.parser import HTMLParser

import pytest

from tests import helpers

pytestmark = pytest.mark.django_db


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def by_id(self, ident):
        return next(attrs for _, attrs in self.tags if attrs.get('id') == ident)


@pytest.mark.parametrize('paid', [False, True])
def test_company_sections_preserve_signature_entitlement(client, paid):
    company = helpers.crear_empresa('FRONTEND', plan='plan-1000' if paid else None)
    owner = helpers.crear_usuario('frontend.owner', company)
    helpers.iniciar_sesion(client, owner, empresa=company)
    response = client.get('/pos/company/update/')
    assert response.status_code == 200
    html = response.content.decode()
    elements = Elements(html)
    assert sum(tag == 'fieldset' for tag, _ in elements.tags) == 5
    assert ('disabled' not in elements.by_id('id_electronic_signature')) == paid
    assert elements.by_id('id_email_host_password')['type'] == 'password'
    assert not any(attrs.get('name') == 'is_active' for _, attrs in elements.tags)
    if not paid:
        assert 'Podrás subir tu firma electrónica cuando actives un plan' in html


def test_login_keeps_registration_and_confirmation_recovery(client):
    html = client.get('/login/').content.decode()
    assert 'img/brand/isotipo.png' in html
    assert 'Crea tu cuenta' in html
    assert 'name="next"' in html and 'csrfmiddlewaretoken' in html


def test_plan_keeps_prices_disabled_checkout_and_post_contract(client, settings):
    settings.PAYPHONE_TOKEN = ''
    company = helpers.crear_empresa('FRONTEND', plan=None)
    owner = helpers.crear_usuario('frontend.plans', company)
    helpers.iniciar_sesion(client, owner, empresa=company)
    html = client.get('/suscripcion/').content.decode()
    elements = Elements(html)
    assert '$50.00' in html and '$85.00' in html and 'al año, IVA incluido' in html
    assert 'fpa-aviso-plan' in html
    assert all('disabled' in attrs for tag, attrs in elements.tags if tag == 'button' and attrs.get('type') == 'submit')
    names = {attrs.get('name') for tag, attrs in elements.tags if tag == 'input'}
    assert {'plan', 'modo', 'csrfmiddlewaretoken'} <= names


@pytest.mark.parametrize('path', ['/suscripcion/pago/retorno/', '/suscripcion/pago/cancelado/'])
def test_payment_result_has_brand_without_session(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'img/brand/isotipo.png' in response.content.decode()

@pytest.mark.parametrize('available', [False, True])
def test_upgrade_requires_server_quote_and_preserves_expiry(client, settings, available):
    from django.template.loader import render_to_string
    settings.PAYPHONE_TOKEN = 'local-test-double'
    settings.PAYPHONE_STORE_ID = 'local-test-double'
    company = helpers.crear_empresa('MEJORA', plan='plan-1000')
    owner = helpers.crear_usuario('frontend.upgrade', company)
    helpers.iniciar_sesion(client, owner, empresa=company)
    response = client.get('/suscripcion/')
    context = response.context[0].flatten()
    option = next(o for o in context['opciones'] if o['plan'].unlimited)
    end = context['estado'].periodo.ends_at
    option['mejora'] = {'disponible': available, 'amount_cents': 3500, 'ends_at': end}
    html = render_to_string('suscripciones/plan.html', context, request=response.wsgi_request)
    elements = Elements(html)
    upgrade = next(attrs for tag, attrs in elements.tags if tag == 'button' and 'fpa-btn-pagar' in attrs.get('class', '') and ('disabled' in attrs or available)) if not available else None
    if available:
        assert 'Mejorar por $35.00' in html
        assert 'Esta mejora no renueva tu suscripción por otro año' in html
        # Solo en la tarjeta del ilimitado: la del multiempresa sí empieza un año nuevo (sin prorrateo).
        tarjeta = next(a for a in html.split('<article')[1:] if 'Plan ilimitado' in a)
        assert 'Tu plan actual termina hoy, sin prorrateo' not in tarjeta
    else:
        assert 'Mejora pendiente de habilitar' in html
        assert 'disabled' in upgrade
