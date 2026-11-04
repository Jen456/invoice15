"""Real DOM and JS, fake API responses. Does not emit, save, email or call SRI."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8766')
parser.add_argument('--chromium', default='/usr/bin/chromium')
parser.add_argument('--output', type=Path, default=Path('entregas/facturaporaqui/capturas/ux-v9'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
checks, errors, failed_requests = [], [], []
submitted = []
product = {'id': 1, 'code': 'DEMO-01', 'name': 'Servicio de instalación y configuración con descripción extensa — ejemplo ficticio',
           'stock': 0, 'inventoried': False, 'cant': 1, 'price_current': 25, 'dscto': 0, 'with_tax': True}
behavior = {'product': 'error', 'client': 'error'}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append({'check': name, 'passed': True})


def mock_api(route):
    request = route.request
    if request.method != 'POST':
        route.continue_()
        return
    data = request.post_data or ''
    match = re.search(r'name="action"\r\n\r\n([^\r]+)', data)
    action = match.group(1) if match else parse_qs(data).get('action', [''])[0]
    submitted.append(action)
    if action == 'search_voucher_number': payload = {'voucher_number': '000000001'}
    elif action == 'validate_client': payload = {'valid': True}
    elif action == 'create_product':
        payload = {'error': {'code': ['Este código ya existe en el ejemplo.']}} if behavior['product'] == 'error' else dict(product, id=2, code='DEMO-02', name='Producto creado en la simulación')
    elif action == 'create_client': payload = {'error': {'email': ['Revisa el correo de ejemplo.']}}
    elif action in ['search_product', 'search_products', 'search_client']: payload = [dict(product, value=product['name'], text=product['name'])]
    else: payload = {'error': {'payment_note': ['Respuesta simulada: revisa la nota antes de continuar.']}}
    route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))


def screenshot(page, name):
    if page.evaluate('document.activeElement.id') == 'contenido':
        page.evaluate('document.activeElement.blur()')
    target = args.output / (name + '.jpg')
    page.screenshot(path=str(target), full_page=True, type='jpeg', quality=62)
    if target.stat().st_size > 150 * 1024:
        page.screenshot(path=str(target), full_page=True, type='jpeg', quality=48)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.chromium, args=['--no-sandbox'])
    context = browser.new_context(locale='es-EC', viewport={'width': 1360, 'height': 950}, accept_downloads=True)
    def local_only(route):
        if urlsplit(route.request.url).hostname not in ['127.0.0.1', 'localhost']:
            route.abort()
        else:
            route.continue_()
    context.route('**/*', local_only)
    context.route('**/sale/add/', mock_api)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: failed_requests.append(response.url) if response.status >= 400 else None)
    page.goto(args.url + '/sale/add/')
    page.wait_for_function('typeof sale !== "undefined" && typeof FPSaleUX !== "undefined" && typeof tblProducts !== "undefined"')
    page.evaluate('item => sale.addProduct(item)', product)
    page.locator('[name=payment_note]').fill('Promesa ficticia: pagar el 18 de noviembre.')
    for width in [360, 390, 768, 1024, 1360, 1440]:
        page.set_viewport_size({'width': width, 'height': 950})
        check('factura sin desborde ' + str(width), page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'))
        if width in [360, 768, 1360]: screenshot(page, 'factura-' + str(width))
    check('efectivo y cambio fuera del formulario', page.locator('[name=cash],[name=change]').count() == 0)
    page.set_viewport_size({'width': 1360, 'height': 950})
    page.locator('[name=price_current]').fill('19.50')
    page.locator('[name=price_current]').press('Tab')
    check('precio editado actualiza detalle', page.evaluate('sale.detail.products[0].price_current') == 19.5)
    check('precio editado conserva la nota', page.locator('[name=payment_note]').input_value().startswith('Promesa ficticia'))
    page.locator('[name=payment_type]').select_option('credito')
    page.locator('[name=end_credit]').fill('')
    page.locator('[name=end_credit]').press('Tab')
    check('crédito exige vencimiento junto al campo', page.locator('[name=end_credit]').get_attribute('aria-invalid') == 'true')
    check('el error conserva las líneas', page.evaluate('sale.detail.products.length') == 1)
    page.locator('[name=end_credit]').fill('2026-11-18')
    page.locator('[name=end_credit]').press('Tab')
    check('corregir vencimiento retira el error', page.evaluate('FPSaleUX.validateCredit(document.getElementById("frmForm"))'))
    page.locator('[name=payment_attachment]').set_input_files({'name': 'recibo-demo.txt', 'mimeType': 'text/plain', 'buffer': b'fake'})
    check('formato inválido junto al archivo', page.locator('[name=payment_attachment]').get_attribute('aria-invalid') == 'true')
    page.locator('#fp-remove-attachment').click()
    check('quitar archivo mantiene la nota', page.locator('[name=payment_note]').input_value().startswith('Promesa ficticia'))
    page.locator('.btnAddProduct').click()
    expect(page.locator('#myModalProduct')).to_be_visible()
    page.locator('#quick_product_name').fill('Producto ficticio')
    page.locator('#quick_product_code').fill('DEMO-01')
    page.locator('#quick_product_category').select_option(index=1)
    page.locator('#quick_product_pvp').fill('25')
    page.locator('#quick_product_price').fill('10')
    page.locator('#quick_product_stock').fill('0')
    page.locator('#quick_product_inventoried').uncheck()
    page.locator('#frmQuickProduct button[type=submit]').click()
    expect(page.locator('#quick_product_code')).to_have_attribute('aria-invalid', 'true')
    check('error de producto conserva factura y nombre', page.locator('#quick_product_name').input_value() == 'Producto ficticio' and page.evaluate('sale.detail.products.length') == 1)
    screenshot(page, 'producto-error-1360')
    behavior['product'] = 'ok'
    page.locator('#quick_product_code').fill('DEMO-02')
    page.locator('#frmQuickProduct button[type=submit]').click()
    expect(page.locator('#myModalProduct')).to_be_hidden()
    check('respuesta simulada de alta agrega la línea sin perder la anterior', page.evaluate('sale.detail.products.length') == 2)
    check('alta no pierde cliente', page.locator('[name=client]').input_value() == '999')
    page.evaluate("FPSaleUX.errors(document.getElementById('frmForm'), 'La empresa activa cambió. Revisa antes de enviar.', 409)")
    check('409 ofrece recargar sin borrar automáticamente', page.get_by_role('button', name='Recargar la página').is_visible() and page.evaluate('sale.detail.products.length') == 2)
    screenshot(page, 'conflicto-empresa-1360')
    page.evaluate("FPSaleUX.clearErrors(document.getElementById('frmForm'))")
    page.locator('.btnAddClient').click()
    expect(page.locator('#myModalClient')).to_be_visible()
    page.locator('#frmClient [name=names]').fill('Cliente de demostración')
    page.evaluate("FPSaleUX.errors(document.getElementById('frmClient'), {email:['Corrige el correo del ejemplo.']})")
    check('errores del cliente junto al campo y sin pérdida', page.locator('#frmClient [name=email]').get_attribute('aria-invalid') == 'true' and page.locator('#frmClient [name=names]').input_value() == 'Cliente de demostración')
    page.locator('#myModalClient .close').click()
    expect(page.locator('#myModalClient')).to_be_hidden()
    page.locator('.btnAddClient').click()
    check('cerrar y reabrir cliente conserva borrador', page.locator('#frmClient [name=names]').input_value() == 'Cliente de demostración')
    page.locator('#myModalClient .close').click()
    expect(page.locator('#myModalClient')).to_be_hidden()
    page.locator('.btnAddProduct').focus()
    page.keyboard.press('Tab')
    page.keyboard.press('Shift+Tab')
    check('foco visible del botón de alta', page.locator('.btnAddProduct').evaluate("el => getComputedStyle(el).outlineStyle !== 'none'"))
    page.evaluate("FPSaleUX.clearErrors(document.getElementById('frmForm'))")
    page.evaluate("FPSaleUX.submit({params:new FormData(document.getElementById('frmForm'))}, document.getElementById('frmForm'))")
    expect(page.locator('.jconfirm')).to_be_visible()
    before = len(submitted)
    page.locator('.jconfirm-buttons button').filter(has_text=re.compile('^No$')).click()
    expect(page.locator('.jconfirm')).to_have_count(0)
    check('cancelar confirmación no envía y libera el formulario', len(submitted) == before and not page.locator('#frmForm').get_attribute('data-fp-busy'))
    page.evaluate("FPSaleUX.submit({params:new FormData(document.getElementById('frmForm'))}, document.getElementById('frmForm'))")
    page.evaluate("FPSaleUX.submit({params:new FormData(document.getElementById('frmForm'))}, document.getElementById('frmForm'))")
    check('doble acción no duplica la confirmación', page.locator('.jconfirm').count() == 1)
    page.locator('.jconfirm-buttons button').filter(has_text=re.compile('^Si$')).click()
    expect(page.locator('[name=payment_note]')).to_have_attribute('aria-invalid', 'true')
    check('respuesta de validación conserva nota y productos', page.evaluate('sale.detail.products.length') == 2 and page.locator('[name=payment_note]').input_value().startswith('Promesa ficticia'))
    check('validación del servidor libera el envío sin reintento', len(submitted) == before + 1 and not page.locator('#frmForm').get_attribute('data-fp-busy'))
    for width in [360, 390, 768, 1024, 1360, 1440]:
        page.set_viewport_size({'width': width, 'height': 950})
        for section in ['inicio', 'cuentas', 'asientos', 'cierre', 'reportes', 'puntos']:
            page.goto(args.url + '/propuesta/index.html#' + section)
            check(section + ' sin desborde ' + str(width), page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'))
            if width in [360, 768, 1360]: screenshot(page, section + '-' + str(width))
    page.goto(args.url + '/propuesta/index.html#cuentas')
    page.locator('#fp-account-search').fill('Bancos')
    check('buscar cuenta conserva la jerarquía', page.locator('#fp-account-tree details').count() == 2 and page.locator('[data-account]').count() == 1)
    page.locator('[data-account]').click()
    check('grupo y movimiento diferenciados', 'Cuenta de movimiento' in page.locator('#fp-account-detail').inner_text())
    page.get_by_role('button', name='Ver diseño de importación').click()
    expect(page.locator('#fp-dialog')).to_be_visible()
    page.locator('#fp-account-file').set_input_files({'name': 'PLAN-DEMO.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': b'not a workbook - never parsed or sent'})
    check('seleccionar Excel no afirma importación', 'no enviado' in page.locator('#fp-file-selected').inner_text())
    page.get_by_role('button', name='Ver filas de ejemplo').click()
    check('filas de importación identificadas como simuladas', 'no extraídas del archivo' in page.locator('#fp-import-preview').inner_text())
    check('confirmar importación deshabilitado', page.get_by_role('button', name='Confirmar importación').is_disabled())
    screenshot(page, 'importacion-ejemplo-1440')
    page.keyboard.press('Escape')
    page.goto(args.url + '/propuesta/index.html#asientos')
    page.locator('[data-document="DEMO-001"]').click()
    page.get_by_role('button', name='Consultar asiento asociado').click()
    check('comprobante enlaza a asiento con débitos y créditos', 'Debe USD' in page.locator('#fp-dialog-content').inner_text() and 'Haber USD' in page.locator('#fp-dialog-content').inner_text())
    check('cuadre no confirma asiento', page.get_by_role('button', name='Confirmar asiento').is_disabled())
    screenshot(page, 'asiento-detalle-1440')
    page.keyboard.press('Escape')
    page.locator('[data-entry="DEMO-002"]').click()
    page.get_by_role('button', name='Ver cómo resolver').click()
    check('excepción muestra causa y acción pendiente', 'tratamiento del IVA' in page.locator('#fp-dialog-content').inner_text() and page.get_by_role('button', name='Guardar asignación').is_disabled())
    page.keyboard.press('Escape')
    page.goto(args.url + '/propuesta/index.html#reportes')
    page.locator('#fp-report-mode').select_option('detail')
    check('reporte detallado mantiene etiqueta provisional', 'PROVISIONAL' in page.locator('#contenido').inner_text() and 'Factura DEMO-001' in page.locator('#fp-report-rows').inner_text())
    with page.expect_download() as info:
        page.get_by_role('button', name='Exportar ejemplo CSV').click()
    download = info.value
    check('exportación identificada DEMO y provisional', download.suggested_filename.startswith('DEMO-provisional-') and b'DATOS SIMULADOS' in Path(download.path()).read_bytes())
    for state in ['loading', 'empty', 'error', 'forbidden', 'pending']:
        page.locator('#fp-demo-state').select_option(state)
        check('estado visual ' + state, page.locator('.fp-state-block').is_visible() and page.locator('[data-action=export-report]').count() == 0)
        screenshot(page, 'estado-' + state)
    page.locator('#fp-demo-state').select_option('ready')
    page.locator('#fp-company').select_option('piloto')
    for section in ['inicio', 'cuentas', 'asientos', 'cierre', 'reportes', 'puntos']:
        page.evaluate('section => location.hash = section', section)
        page.wait_for_timeout(50)
        text = page.locator('#contenido').inner_text()
        check('piloto sin cifras ni confirmación en ' + section, 'Importación del Excel pendiente' in text and '115,00' not in text and page.locator('[data-action=export-report]').count() == 0)
    screenshot(page, 'piloto-pendiente-1440')
    page.locator('#fp-company').select_option('demo')
    page.goto(args.url + '/propuesta/index.html#puntos')
    check('máximo de tres puntos y sin verificación inventada', page.locator('.fp-point-card').count() == 3 and page.get_by_role('button', name='Agregar punto').is_disabled() and page.locator('.fp-point-card .fp-chip-success').count() == 0)
    page.set_viewport_size({'width': 360, 'height': 950})
    page.locator('#fp-menu-toggle').click()
    check('menú móvil accesible por teclado', page.locator('#fp-menu-toggle').get_attribute('aria-expanded') == 'true' and page.evaluate('document.activeElement.closest("#fp-navigation") !== null'))
    page.emulate_media(reduced_motion='reduce')
    check('movimiento reducido respetado', page.evaluate("getComputedStyle(document.querySelector('.fp-point-card')).animationName === 'none'"))
    check('sin errores de JavaScript', not errors)
    check('sin respuestas fallidas de recursos', not failed_requests)
    (args.output / 'verificacion.json').write_text(json.dumps({'scope': 'Plantillas reales y componentes; respuestas API simuladas. No demuestra persistencia real ni autorización SRI.', 'checks': checks, 'js_errors': errors, 'failed_requests': failed_requests}, indent=2, ensure_ascii=False))
    print(json.dumps({'checks': len(checks), 'passed': len(checks), 'js_errors': errors, 'failed_requests': failed_requests}, ensure_ascii=False))
    browser.close()
