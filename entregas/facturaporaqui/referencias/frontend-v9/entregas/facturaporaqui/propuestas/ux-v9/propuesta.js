/* Explicitly simulated design data. No API requests, persistence or financial posting. */
(function () {
  'use strict';
  const titles = {inicio: 'Inicio contable', cuentas: 'Plan de cuentas', asientos: 'Asientos por comprobante', cierre: 'Revisión del mes', reportes: 'Reportes', puntos: 'Puntos de emisión'};
  const accounts = [
    {code: '1', name: 'Activo', group: true, children: [
      {code: '1.1', name: 'Activo corriente', group: true, children: [
        {code: '1.1.01', name: 'Caja', group: false},
        {code: '1.1.02', name: 'Bancos', group: false},
        {code: '1.1.03', name: 'Cuentas por cobrar', group: false}
      ]}
    ]},
    {code: '2', name: 'Pasivo', group: true, children: [
      {code: '2.1.01', name: 'Cuentas por pagar', group: false},
      {code: '2.1.02', name: 'IVA en ventas', group: false}
    ]},
    {code: '4', name: 'Ingresos', group: true, children: [
      {code: '4.1.01', name: 'Ventas de productos', group: false}
    ]}
  ];
  const entries = [
    {id: 'DEMO-001', date: '03/11/2026', document: 'Factura DEMO-001', origin: 'Venta a crédito', state: 'Borrador', amount: '115,00', lines: [
      ['1.1.03', 'Cuentas por cobrar', '115,00', '—'],
      ['4.1.01', 'Ventas de productos', '—', '100,00'],
      ['2.1.02', 'IVA en ventas', '—', '15,00']
    ]},
    {id: 'DEMO-002', date: '03/11/2026', document: 'Compra DEMO-002', origin: 'Compra recibida', state: 'Con excepción', amount: '46,00', lines: [
      ['—', 'Cuenta de gasto por asignar', '40,00', '—'],
      ['—', 'Tratamiento de IVA por revisar', '6,00', '—'],
      ['2.1.01', 'Cuentas por pagar', '—', '46,00']
    ]}
  ];
  const main = document.getElementById('contenido');
  const dialog = document.getElementById('fp-dialog');
  let lastFocus;
  let selectedEntry = null;
  function escape(value) { return String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char])); }
  function chip(text, kind) { return `<span class="fp-chip ${kind ? 'fp-chip-' + kind : ''}">${escape(text)}</span>`; }
  function page() { return Object.prototype.hasOwnProperty.call(titles, location.hash.slice(1)) ? location.hash.slice(1) : 'inicio'; }
  function pilot() { return document.getElementById('fp-company').value === 'piloto'; }
  function heading(title, description, actions = '') {
    return `<div class="fp-page-heading"><div><span class="fp-eyebrow">Contabilidad · ${pilot() ? 'Propuesta de piloto' : 'Empresa de demostración'}</span><h1>${title}</h1><p>${description}</p></div><div class="fp-page-actions">${actions}</div></div>`;
  }
  function unavailable(text) { return `<button type="button" class="fp-btn-secondary" disabled aria-describedby="fp-unavailable-help">${text}</button>`; }
  function sampleNotice() { return '<div class="fp-callout"><strong>Ejemplo de diseño, sin registros reales.</strong><p>Las cuentas, cifras y estados de esta vista son simulados. No corresponden al piloto NEXALLTI.</p></div>'; }
  function pendingPilot() {
    return `<div class="fp-alert fp-alert-warning"><strong>NEXALLTI · Importación del Excel pendiente</strong><p>Según lo reportado, la empresa se creó en localhost. No hay evidencia del backend que confirme la importación, los saldos o la verificación de sus puntos.</p></div>
      <div class="fp-section"><h2>Empezar con un plan de cuentas reducido</h2><p>Primero se revisarán códigos, nombres, jerarquía y cuentas de movimiento. Las cifras seguirán pendientes hasta confirmar la importación y los saldos de apertura.</p><dl class="fp-dl"><div><dt>Configuración del piloto</dt><dd>Por revisar</dd></div><div><dt>Excel</dt><dd>Pendiente de importar</dd></div><div><dt>Saldos de apertura</dt><dd>Sin confirmar</dd></div><div><dt>Conciliación inicial</dt><dd>Sin confirmar</dd></div></dl><p class="fp-small">«Plan reducido» se refiere al plan de cuentas del piloto; no confirma un precio ni una suscripción comercial.</p></div>`;
  }
  function overview() {
    return heading('Cada mes, con todo a la vista.', 'Un recorrido claro para organizar tus cuentas, revisar documentos y preparar los reportes.') +
      `<div class="fp-hero"><div><span class="fp-eyebrow">Tu siguiente paso</span><h2>Empieza por tu plan de cuentas</h2><p>Define una estructura sencilla para tu negocio. Separa los grupos de las cuentas en las que registrarás movimientos.</p><a class="fp-btn-primary" href="#cuentas">Revisar plan de cuentas <span aria-hidden="true">→</span></a></div><img src="../../../../static/img/brand/isotipo-pie.png" alt="" width="104" height="104"></div>
      <div class="fp-metrics"><div class="fp-metric"><span>Plan de cuentas</span><strong>Por configurar</strong><small>Importación sin confirmar</small></div><div class="fp-metric"><span>Saldos de apertura</span><strong>Pendientes</strong><small>No se muestran como cero</small></div><div class="fp-metric"><span>Reportes del mes</span><strong>Provisionales</strong><small>Requieren apertura y conciliación</small></div></div>
      <div class="fp-two-columns"><section class="fp-section"><h2>Una cosa a la vez</h2><ol class="fp-stage-list"><li><span>1</span><div><strong>Configura tus cuentas</strong><p>Revisa el archivo y resuelve las filas con errores antes de importar.</p></div></li><li><span>2</span><div><strong>Confirma el punto de partida</strong><p>Comprueba los saldos anteriores con tu contador.</p></div></li><li><span>3</span><div><strong>Revisa el mes</strong><p>Documentos, excepciones y respaldos, con acceso a su origen.</p></div></li></ol></section><section class="fp-section"><span class="fp-eyebrow">Piloto propuesto</span><h2>NEXALLTI</h2>${chip('Excel pendiente de importar', 'warning')}<p class="fp-small" style="margin-top:14px">La creación de la empresa en localhost fue reportada. La importación del Excel y los saldos no están confirmados.</p><button type="button" class="fp-btn-secondary" data-action="pilot">Ver pendientes del piloto</button></section></div>`;
  }
  function nodeMatches(node, query) { return (node.code + ' ' + node.name).toLocaleLowerCase('es').includes(query) || (node.children || []).some(child => nodeMatches(child, query)); }
  function accountTree(nodes, query = '', parentMatched = false) {
    return '<ul class="fp-tree">' + nodes.filter(node => parentMatched || nodeMatches(node, query)).map(node => {
      if (node.group) {
        const ownMatch = (node.code + ' ' + node.name).toLocaleLowerCase('es').includes(query);
        return `<li><details open><summary><code>${node.code}</code>${node.name} ${chip('Grupo', 'muted')}</summary>${accountTree(node.children, query, parentMatched || ownMatch)}</details></li>`;
      }
      return `<li><button type="button" class="fp-account" data-account="${node.code}"><code>${node.code}</code><span>${node.name}</span>${chip('Movimiento')}</button></li>`;
    }).join('') + '</ul>';
  }
  function accountPage() {
    return heading('Un lugar para cada movimiento.', 'Explora la estructura antes de importar. Los grupos organizan; las cuentas de movimiento reciben los asientos.', '<button type="button" class="fp-btn-primary" data-action="import">Ver diseño de importación</button>') + sampleNotice() +
      `<section class="fp-section"><div class="fp-section-heading"><div><span class="fp-eyebrow">Estructura de ejemplo</span><h2>Plan de cuentas reducido</h2></div>${chip('No importado', 'warning')}</div><div class="fp-toolbar"><div><label for="fp-account-search">Buscar cuenta por código o nombre</label><input id="fp-account-search" class="form-control" type="search" placeholder="Ej.: bancos o 1.1" autocomplete="off"></div></div><p class="fp-small">Códigos ilustrativos. No se presentan como catálogo oficial de la Supercias.</p><div id="fp-account-tree">${accountTree(accounts)}</div><p id="fp-account-empty" class="fp-empty" hidden>No hay cuentas de ejemplo que coincidan con esa búsqueda.</p><div id="fp-account-detail" class="fp-selected-account" role="status">Selecciona una cuenta de movimiento para ver su detalle. Los grupos se despliegan con Enter o Espacio.</div></section>`;
  }
  function entryPage() {
    return heading('Del comprobante a sus cuentas.', 'Consulta el origen, los débitos y créditos. Las excepciones se resuelven antes de confirmar el asiento.') + sampleNotice() +
      `<section class="fp-section"><div class="fp-section-heading"><h2>Asientos de ejemplo</h2>${chip('2 borradores', 'warning')}</div><div class="fp-table-region" role="region" aria-label="Asientos por comprobante" tabindex="0"><table><thead><tr><th scope="col">Fecha</th><th scope="col">Comprobante de origen</th><th scope="col">Estado</th><th scope="col" class="fp-numeric">Importe USD</th><th scope="col">Detalle</th></tr></thead><tbody>${entries.map(entry => `<tr><td>${entry.date}</td><td><button type="button" class="fp-row-button" data-document="${entry.id}">${entry.document}</button><span class="fp-source">${entry.origin} · ficticio</span></td><td>${chip(entry.state, 'warning')}</td><td class="fp-numeric">${entry.amount}</td><td><button type="button" class="fp-row-button" data-entry="${entry.id}">Ver asiento</button></td></tr>`).join('')}</tbody></table></div><p class="fp-help">Un asiento balanceado puede seguir pendiente de revisión. Cuadrar no confirma que las cuentas elegidas sean correctas.</p></section>`;
  }
  function monthlyPage() {
    return heading('Revisa el mes, sin perder el hilo.', 'Documentos, conciliaciones y pendientes de una sola empresa. Cada observación debe llevar a su origen.', '<button type="button" class="fp-btn-secondary" data-action="export-checks">Exportar ejemplo CSV</button>') +
      `<div class="fp-toolbar"><div><label for="fp-period">Mes de revisión del ejemplo</label><input id="fp-period" class="form-control" type="month" value="2026-11"></div><span class="fp-chip fp-chip-warning">Período de demostración · no cerrado</span></div><div class="fp-callout"><strong>Revisión pendiente</strong><p>Falta confirmar apertura y conciliación. Los controles de esta propuesta no cierran el período ni presentan declaraciones.</p></div>
      <nav class="fp-progress-track" aria-label="Revisión mensual"><a href="#fp-documents" data-anchor>1. Documentos<span>2 por revisar</span></a><a href="#fp-tax-review" data-anchor>2. IVA y ATS<span>Sin conciliar</span></a><a href="#fp-opening" data-anchor>3. Apertura<span>Sin confirmar</span></a><a href="#fp-evidence" data-anchor>4. Respaldos<span>Pendientes</span></a></nav>
      <section class="fp-section" id="fp-documents"><h2>Documentos y excepciones</h2><ul class="fp-checks"><li><div><strong>Compra con cuenta por asignar</strong><small>Compra DEMO-002 · no está lista para contabilizar</small></div><button type="button" class="fp-row-button" data-entry="DEMO-002">Revisar origen</button></li><li><div><strong>Factura con promesa de pago</strong><small>Factura DEMO-001 · la nota no confirma un cobro</small></div><button type="button" class="fp-row-button" data-document="DEMO-001">Ver comprobante</button></li></ul></section>
      <div class="fp-two-columns"><section class="fp-section" id="fp-tax-review"><h2>Conciliación IVA / ATS</h2><ul class="fp-checks"><li><div><strong>Libros frente a documentos</strong><small>Revisión del contador pendiente</small></div>${chip('Por revisar', 'warning')}</li><li><div><strong>IVA frente al ATS</strong><small>No hay conciliación confirmada</small></div>${chip('Pendiente', 'warning')}</li></ul><p class="fp-small">Validar un XML contra el XSD no confirma la conciliación ni la presentación ante el SRI.</p></section><section class="fp-section" id="fp-opening"><h2>Saldos anteriores</h2><ul class="fp-checks"><li><div><strong>Apertura del período</strong><small>No se sustituye un saldo desconocido por cero.</small></div>${chip('Sin confirmar', 'warning')}</li><li><div><strong>Responsable de revisión</strong><small>Debe registrarse con usuario y fecha del servidor.</small></div>${chip('Pendiente', 'muted')}</li></ul></section></div>
      <section class="fp-section" id="fp-evidence"><h2>Respaldos de presentación</h2><div class="fp-empty"><strong>Todavía no hay evidencia confirmada.</strong><p>El archivo adjunto, la fecha y la referencia deben vincularse al período. Subir un archivo por sí solo no confirma una presentación.</p>${unavailable('Adjuntar respaldo')}</div><p id="fp-unavailable-help" class="fp-help">La carga de respaldos y el cierre requieren el contrato del backend. No se ejecutan desde esta propuesta.</p></section>`;
  }
  function reportRows(detailed) {
    return detailed ? '<tr><td>Factura DEMO-001</td><td>Venta a crédito</td><td class="fp-numeric">100,00</td><td class="fp-numeric">15,00</td><td class="fp-numeric">115,00</td></tr><tr><td>Compra DEMO-002</td><td>Compra pendiente</td><td class="fp-numeric">40,00</td><td class="fp-numeric">6,00</td><td class="fp-numeric">46,00</td></tr>' : '<tr><td>Ventas</td><td>1 documento ficticio</td><td class="fp-numeric">100,00</td><td class="fp-numeric">15,00</td><td class="fp-numeric">115,00</td></tr><tr><td>Compras</td><td>1 documento ficticio</td><td class="fp-numeric">40,00</td><td class="fp-numeric">6,00</td><td class="fp-numeric">46,00</td></tr>';
  }
  function reportPage() {
    return heading('Entiende el mes de un vistazo.', 'Pasa del resumen al documento. Cuando falte apertura o conciliación, el reporte seguirá siendo provisional.', '<button type="button" class="fp-btn-secondary" data-action="export-report">Exportar ejemplo CSV</button>') +
      `<div class="fp-alert fp-alert-warning"><strong>PROVISIONAL · Ejemplo con datos simulados</strong><p>Sin apertura ni conciliación confirmadas. Este reporte no es un balance, una declaración ni un documento para presentar.</p></div><section class="fp-section"><div class="fp-toolbar"><div><label for="fp-report-mode">Nivel de detalle</label><select id="fp-report-mode"><option value="summary">Resumen por operación</option><option value="detail">Detalle por comprobante</option></select></div><div><label for="fp-report-period">Período del ejemplo</label><input class="form-control" id="fp-report-period" type="text" value="Noviembre de 2026 · demostración" readonly></div></div><div class="fp-table-region" tabindex="0" role="region" aria-label="Reporte provisional de ejemplo"><table><caption>USD · Comercio Demo · provisional · datos simulados</caption><thead><tr><th scope="col" id="fp-report-first-column">Operación</th><th scope="col">Origen</th><th scope="col" class="fp-numeric">Base</th><th scope="col" class="fp-numeric">IVA</th><th scope="col" class="fp-numeric">Total</th></tr></thead><tbody id="fp-report-rows">${reportRows(false)}</tbody></table></div><p class="fp-help">El detalle conserva el mismo alcance del resumen. No calcula casilleros del 101, 104 o 103.</p></section><section class="fp-section"><h2>Antes de un reporte definitivo</h2><ul class="fp-checks"><li><div><strong>Confirmar saldos de apertura</strong><small>Necesarios para los saldos acumulados.</small></div>${chip('Pendiente', 'warning')}</li><li><div><strong>Resolver las excepciones</strong><small>Asientos y cuentas validados por el responsable.</small></div><a class="fp-link" href="#asientos">Ver asientos</a></li><li><div><strong>Completar la conciliación</strong><small>Documentos, libros y datos tributarios.</small></div><a class="fp-link" href="#cierre">Revisar el mes</a></li></ul></section>`;
  }
  function pointsPage() {
    const points = [['001', '001', 'Caja principal'], ['001', '002', 'Ventas móviles'], ['002', '001', 'Atención comercial']];
    return heading('Sabe desde dónde emites.', 'Un establecimiento puede tener varios puntos de emisión. Un punto no equivale necesariamente a una sucursal.', unavailable('Agregar punto')) +
      `<div class="fp-callout"><strong>3 de 3 puntos en este ejemplo</strong><p>El límite interno es de tres puntos. El servidor debe comprobar el cupo y devolver la evidencia de verificación.</p></div><div class="fp-point-grid">${points.map(([establishment, point, name]) => `<article class="fp-point-card"><span class="fp-eyebrow">Punto de emisión</span><h2>${establishment}–${point}</h2><p>${name} · ficticio</p><dl class="fp-dl"><div><dt>Establecimiento</dt><dd>${establishment}</dd></div><div><dt>Punto</dt><dd>${point}</dd></div></dl>${chip('Sin verificación confirmada', 'warning')}<small>Evidencia, responsable y fecha pendientes del backend.</small></article>`).join('')}</div><p class="fp-help" id="fp-unavailable-help">Ejemplo visual del límite alcanzado. No se registraron puntos ni se modificaron numeraciones.</p>`;
  }
  function showState(state) {
    const states = {
      loading: ['Cargando información…', 'Ejemplo visual del estado de carga. No se está consultando una API.'],
      empty: ['Todavía no hay registros.', 'Este es el estado vacío de ejemplo. Aquí aparecerá la información cuando exista en la empresa seleccionada.'],
      error: ['No se pudo cargar la información.', 'Ejemplo de error. Conserva tus datos y vuelve a intentar cuando la conexión esté disponible.'],
      forbidden: ['No tienes permiso para esta sección.', 'Solicita acceso al administrador. No se muestra ni se descarga información restringida.'],
      pending: ['Los datos siguen pendientes.', 'No hay confirmación de apertura, importación o conciliación. No se muestran como completadas.']
    };
    const value = states[state];
    return heading(titles[page()], 'Estado de interfaz simulado.') + `<div class="fp-state-block" ${state === 'error' ? 'role="alert"' : 'role="status"'}><h2>${value[0]}</h2><p>${value[1]}</p>${state === 'loading' ? '<div class="fp-skeleton"></div><div class="fp-skeleton"></div><div class="fp-skeleton"></div>' : ''}<button type="button" class="fp-btn-secondary" data-action="reset-state">Volver al ejemplo</button></div>`;
  }
  function render(focus = false) {
    const current = page();
    const state = document.getElementById('fp-demo-state').value;
    document.title = titles[current] + ' · Propuesta de FacturaPorAquí';
    document.querySelectorAll('[data-page]').forEach(link => {
      if (link.dataset.page === current) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    if (state !== 'ready') main.innerHTML = showState(state);
    else if (pilot()) main.innerHTML = heading(titles[current], 'Piloto propuesto. Se muestran pendientes, sin cifras reales ni importaciones confirmadas.') + pendingPilot();
    else main.innerHTML = ({inicio: overview, cuentas: accountPage, asientos: entryPage, cierre: monthlyPage, reportes: reportPage, puntos: pointsPage})[current]();
    document.getElementById('fp-announcement').textContent = titles[current] + '. Propuesta con datos simulados.';
    if (focus) main.focus();
  }
  function openDialog(title, content) {
    if (!dialog.open) lastFocus = document.activeElement;
    document.getElementById('fp-dialog-title').textContent = title;
    document.getElementById('fp-dialog-content').innerHTML = content;
    if (!dialog.open) dialog.showModal();
    document.getElementById('fp-close-dialog').focus();
  }
  function entryDetail(id) {
    const entry = entries.find(item => item.id === id);
    if (!entry) return;
    selectedEntry = entry;
    openDialog('Asiento de ' + entry.document, `${sampleNotice()}<dl class="fp-dl"><div><dt>Origen</dt><dd>${entry.origin}</dd></div><div><dt>Estado</dt><dd>${entry.state} · no confirmado</dd></div></dl><div class="fp-table-region" tabindex="0" role="region" aria-label="Débitos y créditos del ejemplo"><table><thead><tr><th scope="col">Cuenta</th><th scope="col">Nombre</th><th scope="col">Debe USD</th><th scope="col">Haber USD</th></tr></thead><tbody>${entry.lines.map(line => '<tr>' + line.map((cell, index) => `<td class="${index > 1 ? 'fp-numeric' : ''}">${cell}</td>`).join('') + '</tr>').join('')}</tbody><tfoot><tr><td colspan="2">Totales del ejemplo</td><td class="fp-numeric">${entry.amount}</td><td class="fp-numeric">${entry.amount}</td></tr></tfoot></table></div>${entry.state === 'Con excepción' ? '<div class="fp-alert fp-alert-warning"><strong>Faltan cuentas y criterio tributario.</strong><p>El asiento no puede confirmarse aunque debe y haber coincidan.</p></div>' : '<div class="fp-callout">Debe y haber coinciden en este ejemplo. El asiento continúa como borrador.</div>'}<div class="fp-dialog-actions"><button type="button" class="fp-btn-secondary" data-document="${entry.id}">Ver comprobante</button>${entry.state === 'Con excepción' ? '<button type="button" class="fp-btn-primary" data-action="exception">Ver cómo resolver</button>' : ''}${unavailable('Confirmar asiento')}</div><p id="fp-unavailable-help" class="fp-help">La confirmación requiere API, permisos y revisión del servidor.</p>`);
  }
  function documentDetail(id) {
    const entry = entries.find(item => item.id === id);
    if (!entry) return;
    openDialog(entry.document, `${sampleNotice()}<dl class="fp-dl"><div><dt>Documento</dt><dd>${entry.document}</dd></div><div><dt>Importe de ejemplo</dt><dd>USD ${entry.amount}</dd></div><div><dt>Estado del cobro</dt><dd>Sin confirmación</dd></div><div><dt>Origen</dt><dd>${entry.origin}</dd></div></dl><div class="fp-callout"><strong>Una promesa no es un cobro.</strong><p>La nota «El cliente pagará el 18 de noviembre» no cambia el estado a pagado.</p></div><button type="button" class="fp-btn-primary" data-entry="${entry.id}">Consultar asiento asociado</button>`);
  }
  function importDialog() {
    openDialog('Importar el plan de cuentas', `<div class="fp-callout"><strong>Propuesta del proceso de importación</strong><p>Seleccionar un archivo no lo envía ni lo importa. La vista de filas reconocidas necesita el servicio de Claude.</p></div><label for="fp-account-file">Archivo del plan de cuentas</label><input id="fp-account-file" type="file" accept=".xlsx,.xls,.csv" aria-describedby="fp-file-selected"><p id="fp-file-selected" class="fp-small" role="status">Ningún archivo seleccionado.</p><div class="fp-form-grid"><div><label for="fp-map-code">Columna del código</label><select id="fp-map-code"><option>Código (ejemplo)</option></select></div><div><label for="fp-map-name">Columna del nombre</label><select id="fp-map-name"><option>Nombre (ejemplo)</option></select></div><div><label for="fp-map-parent">Columna del padre</label><select id="fp-map-parent"><option>Cuenta padre (ejemplo)</option></select></div><div><label for="fp-map-kind">Tipo de cuenta</label><select id="fp-map-kind"><option>Grupo / Movimiento (ejemplo)</option></select></div></div><div class="fp-dialog-actions"><button type="button" class="fp-btn-secondary" data-action="sample-import">Ver filas de ejemplo</button>${unavailable('Confirmar importación')}</div><p id="fp-unavailable-help" class="fp-help">Confirmación deshabilitada hasta conectar el backend y resolver los errores por fila.</p><div id="fp-import-preview"></div>`);
  }
  function exportCSV(name, rows) {
    const content = [['DEMO — DATOS SIMULADOS — PROVISIONAL — NO VÁLIDO PARA PRESENTACIÓN'], ...rows]
      .map(row => row.map(cell => '"' + String(cell).replace(/"/g, '""') + '"').join(';')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\ufeff' + content], {type: 'text/csv;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'DEMO-provisional-' + name + '.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    document.getElementById('fp-announcement').textContent = 'Se descargó un ejemplo CSV con datos simulados, identificado como provisional.';
  }
  document.addEventListener('click', event => {
    const anchor = event.target.closest('[data-anchor]');
    if (anchor) { event.preventDefault(); document.querySelector(anchor.getAttribute('href')).scrollIntoView({behavior: 'auto'}); return; }
    const account = event.target.closest('[data-account]');
    if (account) { document.getElementById('fp-account-detail').innerHTML = `<strong>${escape(account.dataset.account)} · Cuenta de movimiento</strong><p>Permite registrar débitos y créditos cuando el backend confirme su disponibilidad. No se ha asignado a ningún comprobante.</p>`; return; }
    const entry = event.target.closest('[data-entry]'); if (entry) { entryDetail(entry.dataset.entry); return; }
    const doc = event.target.closest('[data-document]'); if (doc) { documentDetail(doc.dataset.document); return; }
    const button = event.target.closest('[data-action]'); if (!button) return;
    switch (button.dataset.action) {
      case 'pilot': document.getElementById('fp-company').value = 'piloto'; render(true); break;
      case 'reset-state': document.getElementById('fp-demo-state').value = 'ready'; render(true); break;
      case 'import': importDialog(); break;
      case 'sample-import':
        document.getElementById('fp-import-preview').innerHTML = `<h3>Filas simuladas · no extraídas del archivo</h3><div class="fp-table-region" tabindex="0" role="region" aria-label="Errores de importación de ejemplo"><table><thead><tr><th scope="col">Fila</th><th scope="col">Código</th><th scope="col">Nombre</th><th scope="col">Revisión</th></tr></thead><tbody><tr><td>2</td><td>1.1.01</td><td>Caja</td><td>Sin observaciones en este ejemplo</td></tr><tr><td>3</td><td>1.1.01</td><td>Bancos</td><td>Código repetido: cambia el código.</td></tr><tr><td>4</td><td>2.2.01</td><td>Obligación de ejemplo</td><td>La cuenta padre no aparece en el archivo.</td></tr></tbody></table></div>`;
        break;
      case 'exception':
        openDialog('Resolver la excepción', `<div class="fp-callout"><strong>${selectedEntry.document} · ejemplo simulado</strong><p>Revisa la cuenta de gasto y el tratamiento del IVA con el contador. No se guarda ninguna asignación desde esta propuesta.</p></div><ol><li>Abre el comprobante y verifica su concepto.</li><li>Selecciona una cuenta de movimiento aprobada.</li><li>Revisa el tratamiento tributario y el cuadre.</li><li>Confirma cuando el servidor valide permisos y reglas.</li></ol><p class="fp-help" id="fp-unavailable-help">Pendiente: contrato de excepciones y matriz de asientos.</p>${unavailable('Guardar asignación')}`);
        break;
      case 'export-checks': exportCSV('revision-mes', [['Control', 'Estado'], ['Apertura', 'Sin confirmar'], ['IVA / ATS', 'Pendiente'], ['Compra DEMO-002', 'Cuenta por asignar']]); break;
      case 'export-report': exportCSV('reporte', [['Operación', 'Base USD', 'IVA USD', 'Total USD'], ['Venta DEMO-001', '100,00', '15,00', '115,00'], ['Compra DEMO-002', '40,00', '6,00', '46,00']]); break;
    }
  });
  document.addEventListener('input', event => {
    if (event.target.id === 'fp-account-search') {
      const query = event.target.value.trim().toLocaleLowerCase('es');
      document.getElementById('fp-account-tree').innerHTML = accountTree(accounts, query);
      document.getElementById('fp-account-empty').hidden = accounts.some(node => nodeMatches(node, query));
    }
  });
  document.addEventListener('change', event => {
    if (['fp-company', 'fp-demo-state'].includes(event.target.id)) {
      if (dialog.open) dialog.close(); selectedEntry = null; render();
    }
    if (event.target.id === 'fp-account-file') document.getElementById('fp-file-selected').textContent = event.target.files[0] ? event.target.files[0].name + ' · seleccionado, no enviado. Las filas de ejemplo no se extraen de este archivo.' : 'Ningún archivo seleccionado.';
    if (event.target.id === 'fp-report-mode') {
      document.getElementById('fp-report-rows').innerHTML = reportRows(event.target.value === 'detail');
      document.getElementById('fp-report-first-column').textContent = event.target.value === 'detail' ? 'Comprobante' : 'Operación';
    }
    if (event.target.id === 'fp-period') {
      event.target.value = '2026-11';
      document.getElementById('fp-announcement').textContent = 'La propuesta solo contiene el ejemplo ficticio de noviembre de 2026.';
    }
  });
  document.getElementById('fp-close-dialog').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (lastFocus && lastFocus.isConnected) lastFocus.focus(); });
  document.getElementById('fp-menu-toggle').addEventListener('click', function () {
    const opened = document.querySelector('.fp-sidebar').classList.toggle('fp-open');
    this.setAttribute('aria-expanded', String(opened));
    if (opened) document.querySelector('#fp-navigation a').focus();
  });
  window.addEventListener('hashchange', () => {
    document.querySelector('.fp-sidebar').classList.remove('fp-open');
    document.getElementById('fp-menu-toggle').setAttribute('aria-expanded', 'false');
    render(true);
  });
  render();
}());
