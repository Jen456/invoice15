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
