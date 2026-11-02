/* La preferencia de cabecera y el punto de un formulario abierto son independientes. */
(function () {
    'use strict';
    if (window.FPAPuntos) return;
    window.FPAPuntos = true;
    var selector = document.querySelector('.fp-selector-punto');
    function aviso(texto, error) {
        var n = selector.querySelector('.fp-selector-estado'); n.textContent = texto; n.classList.toggle('text-danger', Boolean(error));
    }
    if (selector) {
        var cargando = false, guardando = false;
        jQuery(selector).on('show.bs.dropdown', async function () {
            if (cargando || guardando) return;
            cargando = true;
            try {
                var r = await fetch(selector.dataset.seleccionUrl, {credentials:'same-origin'});
                if (!r.ok) throw new Error('No se pudo actualizar el estado de los puntos.');
                var d = await r.json();
                d.elegibles.forEach(function (p) { var n=selector.querySelector('[data-punto-estado="'+p.id+'"]'); if(n)n.textContent=p.listo?'Numeración de facturas confirmada':p.bloqueo || 'Numeración pendiente'; });
                selector.querySelector('.fp-selector-administrar').hidden=!d.puede_administrar;
            } catch(e) { aviso(e.message, true); } finally { cargando=false; }
        });
        selector.addEventListener('submit', async function (e) {
            var form=e.target; if(!form.matches('form'))return; e.preventDefault(); if(guardando)return;
            guardando=true; selector.querySelectorAll('button[type=submit]').forEach(function(n){n.disabled=true;});
            try {
                var r=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{Accept:'application/json'},body:new FormData(form)}), d=await r.json();
                if(!r.ok || !d.ok)throw new Error(d.error || d.mensaje || 'No se pudo cambiar el punto.');
                var p=d.seleccion.seleccionado;
                selector.querySelector('.fp-selector-codigo').textContent=p.codigo_completo;
                selector.querySelectorAll('form').forEach(function(f){var b=f.querySelector('button'), elegido=String(p.id)===f.elements.punto.value;b.classList.toggle('active',elegido);if(elegido)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');});
                aviso('Preferencia guardada: '+p.etiqueta+'.'+(document.querySelector('.fp-punto-emision')?' Este formulario conserva su punto de emisión.':''));
            } catch(e) {aviso(e.message, true);} finally {guardando=false;selector.querySelectorAll('button[type=submit]').forEach(function(n){n.disabled=false;});}
        });
        jQuery(selector).on('click', '.dropdown-menu', function (e) { e.stopPropagation(); });
    }
    document.querySelectorAll('.fp-punto-select').forEach(function(select){
        select.addEventListener('change',function(){var panel=this.closest('.fp-punto-emision');panel.dataset.punto=this.value;panel.querySelector('.fp-punto-etiqueta').textContent=this.selectedOptions[0].textContent;panel.querySelector('.fp-punto-proximo').textContent='Por confirmar';var n=panel.querySelector('.fp-punto-aviso');n.textContent='Cambiaste el punto. El servidor comprobará su numeración al revisar o emitir.';n.hidden=false;});
    });
    document.querySelectorAll('.fp-elegir-numeracion').forEach(function(b){b.addEventListener('click',function(){var form=document.querySelector('.fp-numeracion-form'),select=form.querySelector('[name="n-point"]');select.value=b.dataset.point;form.scrollIntoView({block:'center'});select.focus();});});
}());
