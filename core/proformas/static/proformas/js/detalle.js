/* Ficha de una proforma: botones según `acciones[]` (json_script fp-proforma). Tras cada acción se recarga la ficha. */
$(function () {
    var nodo = document.getElementById('fp-proforma');
    if (!nodo) {
        return;
    }
    var proforma = JSON.parse(nodo.textContent);
    $('.fp-estado-proforma').addClass(fpAcciones.claseEstado(proforma.estado.id));
    $('#fp-botones').html(fpAcciones.botones(proforma, true));
    fpAcciones.despues = function () { location.reload(); };
    fpAcciones.iniciar(function (id) { return String(id) === String(proforma.id) ? proforma : null; });
});
