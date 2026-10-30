/* Crear compra desde el XML: «Usar sugerencia» solo cambia el campo en el navegador (DC12); nada se guarda solo. */
document.addEventListener('click', function (evento) {
    var boton = evento.target.closest('[data-fp-sugerencia]');
    if (!boton) {
        return;
    }
    var campo = document.getElementById(boton.getAttribute('data-fp-sugerencia'));
    if (campo) {
        campo.value = boton.getAttribute('data-valor');
        campo.dispatchEvent(new Event('change', {bubbles: true}));
        campo.focus();
    }
});

/* Búsqueda local a la empresa; el servidor conserva la validación del id elegido. */
$(function () {
    var contenedor = document.querySelector('.fp-importacion-compra');
    if (!contenedor || !$.fn.select2) return;
    $('.fp-producto-xml').each(function () {
        var select = $(this);
        // Conservar selección y campo originales, sin clonar el formset.
        select.find('option').filter(function () { return this.value && !this.selected; }).remove();
        select.select2({theme: 'bootstrap4', width: '100%', language: 'es', minimumInputLength: 2,
            placeholder: 'Busca por nombre o código', allowClear: true,
            ajax: {url: contenedor.getAttribute('data-productos-url'), type: 'POST', dataType: 'json', delay: 250,
                headers: {'X-CSRFToken': csrftoken},
                data: function (p) { return {action: 'search_product', term: p.term, ids: '[]'}; },
                processResults: function (filas) { return {results: Array.isArray(filas) ? filas.map(function (p) { return {id: p.id, text: p.code + ' · ' + p.name}; }) : []}; }
            }
        });
    });
    var aviso = contenedor.querySelector('[data-advertencia="posible_duplicado"]');
    var confirmar = contenedor.querySelector('.fp-stage-duplicate');
    if (aviso && confirmar) { aviso.classList.remove('alert-info'); aviso.classList.add('alert-warning'); confirmar.prepend(aviso); }
});
