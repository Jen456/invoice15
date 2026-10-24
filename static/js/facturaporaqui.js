// Presentation defaults; chart data and application flows stay on the backend.
(function () {
    if (!window.Chart) return;
    Chart.defaults.font.family = 'system-ui, sans-serif';
    Chart.defaults.font.size = 15;
    Chart.defaults.color = '#526B7A';
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) Chart.defaults.animation = false;
})();
(function () {
    // Script runs before jQuery ready callbacks initialize each DataTable.
    if (window.jQuery && jQuery.fn.dataTable) {
        jQuery.extend(true, jQuery.fn.dataTable.defaults, {
            language: {search: 'Buscar:', lengthMenu: 'Mostrar _MENU_ registros', info: '_START_–_END_ de _TOTAL_ registros', infoEmpty: 'Sin registros', infoFiltered: '(de _MAX_ registros)', zeroRecords: 'No se encontraron resultados', emptyTable: 'Todavía no hay registros', loadingRecords: 'Cargando…', processing: 'Procesando…', paginate: {first: 'Primero', last: 'Último', next: 'Siguiente', previous: 'Anterior'}, aria: {sortAscending: ': ordenar ascendente', sortDescending: ': ordenar descendente'}}
        });
    }
    document.addEventListener('click', function (event) {
        var button = event.target.closest('.fp-toggle-secret');
        if (!button) return;
        var input = document.getElementById(button.getAttribute('aria-controls'));
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        button.setAttribute('aria-pressed', String(show));
        button.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && document.body.classList.contains('sidebar-open') && window.jQuery) {
            jQuery('[data-widget="pushmenu"]').PushMenu('collapse');
            var trigger = document.getElementById('collapsedMenu');
            if (trigger) trigger.focus();
        }
    });
})();

/* Mobile document lines: retain original cells, inputs and event handlers. */
(function () {
    function enhanceForms() {
        document.querySelectorAll('#frmForm table').forEach(function (table) {
            if (!table.querySelector('thead')) { table.classList.add('fp-form-totals'); return; }
            table.classList.add('fp-mobile-lines');
            var titles = Array.from(table.querySelectorAll('thead th')).map(function (th) { return th.textContent.trim(); });
            table.querySelectorAll('tbody tr').forEach(function (row) {
                if (row.children.length !== titles.length) { return; }
                Array.from(row.children).forEach(function (cell, i) { cell.dataset.label = titles[i];
                    cell.querySelectorAll('input,select').forEach(function (input) {
                        if (!input.hasAttribute('aria-label')) { input.setAttribute('aria-label', titles[i]); }
                    });
                    cell.querySelectorAll('a[rel="remove"]').forEach(function (button) {
                        button.setAttribute('role', 'button'); button.tabIndex = 0;
                        button.setAttribute('aria-label', 'Eliminar producto');
                    }); });
            });
        });
        document.querySelectorAll('#frmForm label:not([for])').forEach(function (label) {
            var group = label.closest('.form-group');
            var input = group && group.querySelector('input[id],select[id],textarea[id]');
            if (input) { label.htmlFor = input.id; }
        });
    }
    function start() {
        enhanceForms();
        var form = document.getElementById('frmForm');
        if (!form) { return; }
        form.addEventListener('keydown', function (event) {
            if (event.target.matches('a[rel="remove"]') && (event.key === 'Enter' || event.key === ' ')) {
                event.preventDefault(); event.target.click();
            }
        });
        var scheduled = false;
        new MutationObserver(function () {
            if (scheduled) { return; }
            scheduled = true;
            requestAnimationFrame(function () { scheduled = false; enhanceForms(); });
        }).observe(form, {childList: true, subtree: true});
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();

/* Menú por procesos: estado visible por URL y grupos operables con teclado. */
(function () {
    function initMenu() {
        var menu = document.querySelector('.fp-menu-procesos');
        if (!menu) return;
        var path = location.pathname;
        if (path.indexOf('/importacion/documentos/') === 0) path = '/importacion/pendientes/';
        var links = Array.from(menu.querySelectorAll('a[data-name=submodule],a[data-name=single_module]'));
        var current = links.filter(function (link) { return path.indexOf(link.getAttribute('href')) === 0; })
            .sort(function (a, b) { return b.getAttribute('href').length - a.getAttribute('href').length; })[0];
        links.forEach(function (link) { link.classList.remove('active'); link.removeAttribute('aria-current'); });
        if (current) {
            current.classList.add('active'); current.setAttribute('aria-current', 'page');
            var group = current.closest('.has-treeview');
            if (group) { group.classList.add('menu-open'); group.querySelector('.nav-treeview').style.display = 'block'; }
        }
        menu.querySelectorAll('.has-treeview').forEach(function (group) {
            var trigger = group.querySelector('[data-name=module_header]');
            trigger.classList.toggle('active', Boolean(current && group.contains(current)));
            function sync() { trigger.setAttribute('aria-expanded', String(group.classList.contains('menu-open'))); }
            sync();
            new MutationObserver(sync).observe(group, {attributes: true, attributeFilter: ['class']});
            trigger.addEventListener('click', function (event) { event.preventDefault(); });
            trigger.addEventListener('keydown', function (event) { if (event.key === ' ') {event.preventDefault(); trigger.click();} });
        });
    }
    if (window.jQuery) jQuery(function () { setTimeout(initMenu, 0); });
    else document.addEventListener('DOMContentLoaded', initMenu);
}());

/* Menús «Opciones» dentro de tablas: los contenedores con desplazamiento horizontal (DataTables, .table-responsive) los
   recortaban y no se podían ver ni usar. Se colocan aquí en posición fija junto al botón (Popper 1 los ubica mal en
   posición fija), sin sacarlos de la fila, donde los listados escuchan sus clics; las opciones sin enlace se pueden
   recorrer con las flechas y activar con Enter o espacio. */
(function () {
    var CONTENEDORES = '.dataTables_wrapper, .dataTables_scroll, .table-responsive';
    var MARGEN = 8;
    var abierto = null;
    function preparar(event) {
        var toggle = event.target.closest && event.target.closest('[data-toggle="dropdown"]');
        // Antes de que Bootstrap cree el menú (lee los atributos en el primer clic o tecla): sin estilos de Popper.
        if (toggle && !toggle.hasAttribute('data-display') && toggle.closest(CONTENEDORES)) toggle.setAttribute('data-display', 'static');
    }
    ['pointerdown', 'mousedown', 'focusin', 'keydown'].forEach(function (tipo) {
        document.addEventListener(tipo, preparar, true);
    });
    function colocar(menu, toggle) {
        var r = toggle.getBoundingClientRect();
        // Se mide en el origen de la ventana: junto al borde el texto se partiría y el menú parecería más alto.
        Object.assign(menu.style, {position: 'fixed', transform: 'none', top: '0px', left: '0px', right: 'auto', bottom: 'auto',
                                   maxHeight: '', overflowY: '', maxWidth: (window.innerWidth - 2 * MARGEN) + 'px'});
        var ancho = menu.offsetWidth, alto = menu.offsetHeight;
        var abajo = window.innerHeight - r.bottom - MARGEN, arriba = r.top - MARGEN, top;
        if (alto <= abajo || abajo >= arriba) {
            top = r.bottom + 2;
            if (alto > abajo) Object.assign(menu.style, {maxHeight: abajo + 'px', overflowY: 'auto'});
        } else {
            top = r.top - 2 - Math.min(alto, arriba);
            if (alto > arriba) Object.assign(menu.style, {maxHeight: arriba + 'px', overflowY: 'auto'});
        }
        var left = Math.min(r.right - ancho, window.innerWidth - ancho - MARGEN);
        menu.style.top = Math.max(MARGEN, top) + 'px';
        menu.style.left = Math.max(MARGEN, left) + 'px';
    }
    function recolocar() { if (abierto) colocar(abierto.menu, abierto.toggle); }
    function enfocables(menu) {
        menu.querySelectorAll('.dropdown-item:not([href]):not(.disabled)').forEach(function (item) {
            if (!item.hasAttribute('tabindex')) item.tabIndex = 0;
            if (!item.hasAttribute('role')) item.setAttribute('role', 'button');
        });
    }
    if (window.jQuery) {
        jQuery(document).on('show.bs.dropdown', function (event) {
            event.target.querySelectorAll('.dropdown-menu').forEach(enfocables);
        }).on('shown.bs.dropdown', function (event) {
            var toggle = event.relatedTarget, menu = event.target.querySelector('.dropdown-menu');
            if (!toggle || !menu || toggle.getAttribute('data-display') !== 'static' || !toggle.closest(CONTENEDORES)) return;
            abierto = {menu: menu, toggle: toggle};
            colocar(menu, toggle);
        }).on('hidden.bs.dropdown', function () {
            abierto = null;
        });
    }
    window.addEventListener('scroll', recolocar, true);
    window.addEventListener('resize', recolocar);
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        var item = event.target.closest && event.target.closest('.dropdown-menu .dropdown-item[role="button"]:not([href])');
        if (!item) return;
        event.preventDefault();
        item.click();   // también activa los manejadores de jQuery de los listados
    });
}());
