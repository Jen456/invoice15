import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'capturas'
OUT.mkdir(exist_ok=True)
URL = 'http://127.0.0.1:8095/entregas/facturaporaqui/propuestas/apertura-contable/'
steps = ['elegir', 'saldos', 'historial', 'validacion']
errors, responses, checks = [], [], []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1360, 'height': 1000}, device_scale_factor=1, locale='es-EC')
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.on('response', lambda r: responses.append({'status': r.status, 'url': r.url}) if r.status >= 400 else None)
    for width in [360, 390, 768, 1024, 1360, 1440]:
        page.set_viewport_size({'width': width, 'height': 1000 if width > 768 else 900})
        for step in steps:
            page.goto(URL + '?paso=' + step, wait_until='networkidle')
            result = page.evaluate('''() => ({
              width: innerWidth, scroll: document.documentElement.scrollWidth,
              panels: Array.from(document.querySelectorAll('[data-panel]')).filter(e => !e.hidden).map(e => e.dataset.panel),
              current: document.querySelector('[aria-current=step]').dataset.step,
              labelledInputs: Array.from(document.querySelectorAll('input')).every(e => e.labels.length > 0)
            })''')
            assert result['scroll'] <= width, result
            assert result['panels'] == [step], result
            assert result['current'] == step and result['labelledInputs'], result
            checks.append({'paso': step, 'ancho': width, 'sin_desborde': True, 'campos_etiquetados': True})
            if width in [360, 768, 1360]:
                page.screenshot(path=str(OUT / f'{step}-{width}.webp.png'), full_page=True)
                if width == 1360:
                    page.locator(f'[data-panel={step}]').screenshot(path=str(OUT / f'panel-{step}-1360.webp.png'))
    page.goto(URL, wait_until='networkidle')
    page.locator('input[value=historial]').check()
    page.locator('#continuar').click()
    assert 'paso=historial' in page.url
    page.goto(URL, wait_until='networkidle')
    page.keyboard.press('Tab')
    assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != 'none'
    page.locator('#continuar').click()
    assert 'paso=saldos' in page.url
    page.locator('[data-demo]:visible').click()
    assert 'diferencia de 50' in page.locator('#mensaje').inner_text()
    page.goto(URL + '?paso=validacion', wait_until='networkidle')
    page.locator('[data-demo]:visible').click()
    assert 'no se envió, importó ni confirmó' in page.locator('#mensaje').inner_text()
    assert page.get_by_role('button', name='Confirmar apertura · pendiente').is_disabled()
    page.emulate_media(reduced_motion='reduce')
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    page.set_viewport_size({'width': 360, 'height': 900})
    page.goto(URL, wait_until='networkidle')
    page.locator('.choices').screenshot(path=str(OUT / 'opciones-movil-360.webp.png'))
    browser.close()

# Optimize screenshots losslessly as WebP, retaining source dimensions and text.
from PIL import Image
for png in OUT.glob('*.webp.png'):
    with Image.open(png) as image:
        image.save(png.with_suffix(''), 'WEBP', lossless=True, method=6)
    png.unlink()
sizes = {f.name: f.stat().st_size for f in OUT.glob('*.webp')}
assert max(sizes.values()) < 150_000, sizes
assert not errors and not responses, {'js': errors, 'http': responses}
report = {
    'tipo': 'Propuesta estática, sin backend ni persistencia',
    'fecha_ecuador': '2026-11-13',
    'vistas': checks,
    'interacciones': ['Elegir historial', 'Elegir saldos', 'Foco visible por teclado',
        'Aviso de diferencia ficticia', 'Envío identificado como simulación',
        'Confirmación deshabilitada', 'Preferencia de movimiento reducido'],
    'errores_js': errors, 'respuestas_http_fallidas': responses,
    'capturas_bytes': sizes,
    'limite': 'No prueba guardado, cálculos contables, permisos, API ni presentación al SRI.'
}
(ROOT / 'VALIDACION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({'vistas': len(checks), 'errores_js': len(errors), 'respuestas_fallidas': len(responses),
    'interacciones': len(report['interacciones']), 'max_captura_bytes': max(sizes.values())}))
