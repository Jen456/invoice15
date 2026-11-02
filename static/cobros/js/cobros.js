/* Ficha compartida: registra un abono solo en registrar/, conserva la clave en reintentos. */
(function () {
 'use strict';
 if (window.FPACobros) return;
 window.FPACobros = true;
 var el = function(id) { return document.getElementById(id); }, modal = el('fpConsultaCobro');
 if (!modal || !window.jQuery) return;
 var form = el('fpCobroFormulario'), contenido = el('fpConsultaCobroContenido'), aviso = el('fpConsultaCobroEstado');
 var s = {url: '', datos: null, modo: '', respaldo: null, version: 0, busy: false, cambios: false, disparador: null};
 var pendientes = new Map(), consulta;
 function nodo(tag, texto, clase) { var n = document.createElement(tag); if (texto != null) n.textContent = String(texto); if (clase) n.className = clase; return n; }
 function mensaje(texto, error) { aviso.textContent = texto; aviso.className = texto ? 'alert ' + (error ? 'alert-danger' : 'alert-success') : ''; }
 function fecha(v) { var d = new Date(v); return v && !isNaN(d.getTime()) ? d.toLocaleString('es-EC') : '—'; }
 function dato(dl, k, v) { var d = nodo('div'); d.append(nodo('dt', k), nodo('dd', v || '—')); dl.append(d); }
 function boton(texto, fn) { var b = nodo('button', texto, 'btn btn-outline-secondary'); b.type = 'button'; b.disabled = s.busy; b.addEventListener('click', fn); return b; }
 function control(grupo, visible) { el(grupo).hidden = !visible; el(grupo).querySelectorAll('input,select,textarea').forEach(function (n) { n.disabled = !visible; }); }
 function ocupado(v) { s.busy = v; modal.querySelectorAll('[data-dismiss], #fpCobroConfirmar, #fpCobroReenviar, #fpCobroNuevo, #fpCobroCancelar, #fpCobroVolver, #fpConsultaCobroReintentar, #fpConsultaCobroContenido button').forEach(function(n){n.disabled=v;}); }
 async function leer(r) {
   var j;
   try { j = await r.json(); } catch (_) { var e = new Error('No se pudo confirmar la respuesta. Comprueba tu sesión y consulta el resultado.'); e.status = r.status; throw e; }
   if (!r.ok || j.error) { var e = new Error(j.error || 'No se pudo completar la operación.'); e.status = r.status; throw e; }
   return j;
 }
 function cerrarEditor() { form.hidden = true; el('fpCobroConfirmacion').hidden = true; el('fpCobroCampos').disabled = false; el('fpCobroPreparar').hidden = false; s.modo = ''; }
 function editor(modo, r) {
   if (s.busy || pendientes.has(s.url)) return;
   form.reset(); s.modo = modo; s.respaldo = r || null;
   control('fpCobroRegistro', modo === 'registro');
   control('fpCobroRespaldoCampos', modo !== 'revision');
   control('fpCobroRevision', modo === 'revision');
   var credito = Boolean(s.datos.cuenta_por_cobrar);
   el('fpCobroFormularioTitulo').textContent = modo === 'revision' ? 'Revisar respaldo' : modo === 'editar' ? 'Corregir respaldo' : credito ? 'Registrar cobro' : 'Añadir respaldo del contado';
   el('fpCobroFormularioAyuda').textContent = modo === 'revision' ? 'El estado de revisión no modifica el abono ni el saldo.' : modo === 'editar' ? 'Se conserva el historial. Un respaldo revisado vuelve a pendiente al corregirlo.' : credito ? 'Al confirmar se registra un abono y disminuye el saldo pendiente.' : 'Este respaldo documenta el cobro al contado. No crea otro abono.';
   form.elements.clave.value = s.datos.clave_sugerida;
   if (modo === 'registro') {
     var select = el('fpCobroMedio'); select.replaceChildren(new Option('Elige el medio de cobro', ''));
     s.datos.medios.forEach(function(m){select.add(new Option(m.nombre,m.id));});
     if(s.datos.factura.medio_cobro) select.value=s.datos.factura.medio_cobro.id;
     el('fpCobroImporte').value = credito ? '' : s.datos.factura.total;
     el('fpCobroImporte').readOnly = !credito;
     if (credito) el('fpCobroImporte').max = s.datos.cuenta_por_cobrar.saldo; else el('fpCobroImporte').removeAttribute('max');
     control('fpCobroFechaGrupo', credito); el('fpCobroFecha').required = credito;
   }
   el('fpCobroNota').setCustomValidity(''); el('fpCobroArchivo').setCustomValidity('');
   if (r) { el('fpCobroNota').value = r.nota || ''; el('fpCobroReferencia').value = r.referencia || ''; el('fpCobroEstado').value = r.estado.id; el('fpCobroMotivo').value = r.motivo_revision || ''; }
   el('fpCobroArchivoAyuda').textContent = r && r.archivo ? 'Archivo actual: ' + r.archivo.nombre + '. Si no eliges otro, se conserva. El archivo sustituido queda en el historial.' : 'Escribe una nota, adjunta un comprobante o conserva ambos.';
   el('fpCobroMotivo').required = el('fpCobroEstado').value === 'rechazado';
   el('fpCobroCampos').disabled = false; el('fpCobroConfirmacion').hidden = true; el('fpCobroPreparar').hidden = false;
   form.hidden = false; form.scrollIntoView({block:'nearest'});
   form.querySelector('select:not(:disabled),textarea:not(:disabled)').focus();
 }
 async function historial(r, lugar, b) {
   b.disabled = true;
   try {
     var datos = await fetch('/cobros/respaldo/' + r.id + '/', {credentials:'same-origin'}).then(leer);
     lugar.replaceChildren();
     datos.historial.forEach(function(h) {
       var item = nodo('li'); item.append(nodo('strong', h.accion_nombre), nodo('small', fecha(h.fecha) + ' · ' + (h.usuario ? h.usuario.nombre || h.usuario.username : '—')));
       var d=h.detalle || {};
       // Nunca imprimir el objeto crudo: cambios de archivo incluyen rutas internas.
       if (h.accion === 'archivo') item.append(nodo('p', (d.antes_nombre || 'Sin archivo') + ' → ' + (d.despues_nombre || 'Archivo actualizado')));
       else if (['nota','referencia','revision'].includes(h.accion)) { if (d.antes != null) item.append(nodo('p','Antes: ' + d.antes)); if(d.despues != null) item.append(nodo('p','Después: ' + d.despues)); if(d.motivo) item.append(nodo('p','Motivo: ' + d.motivo)); }
       lugar.append(item);
     });
     lugar.hidden = false;
   } catch(e) { lugar.replaceChildren(nodo('li', e.message)); lugar.hidden=false; } finally {b.disabled=false;}
 }
 function pintar(datos) {
   if (!datos.factura || !Array.isArray(datos.respaldos)) throw new Error('No se pudo leer la ficha de cobros.');
   s.datos=datos; contenido.replaceChildren();
   var caja=nodo('div',null,'fp-adjuntos-documento'); caja.append(nodo('strong','Factura '+datos.factura.numero));
   var dl=nodo('dl',null,'fp-consulta-cobro-datos'); dato(dl,'Total','$'+datos.factura.total); dato(dl,'Condición',datos.factura.condicion.nombre); dato(dl,'Medio de cobro',datos.factura.medio_cobro && datos.factura.medio_cobro.nombre);
   if(datos.cuenta_por_cobrar) dato(dl,'Saldo por cobrar','$'+datos.cuenta_por_cobrar.saldo);
   caja.append(dl); if(datos.factura.anulada_sri)caja.append(nodo('p','Factura anulada en el SRI.','alert alert-warning')); contenido.append(caja);
   contenido.append(nodo('h3','Respaldos registrados','fp-consulta-cobro-subtitulo'));
   if(!datos.respaldos.length) contenido.append(nodo('p','Todavía no hay un archivo o una nota de cobro registrados.','fp-adjuntos-empty'));
   datos.respaldos.forEach(function(r) {
     var card=nodo('article',null,'fp-consulta-cobro-tarjeta'); card.dataset.respaldo=r.id;
     card.append(nodo('h4','$'+r.importe+' · '+r.medio.nombre)); var badge=nodo('span',r.estado.nombre,'fp-respaldos-estado'); badge.dataset.revisionEstado=r.estado.id; card.append(badge);
     if(r.origen==='abono' && !r.abono_id)card.append(nodo('p','El cobro asociado fue eliminado. Se conserva su respaldo e historial.','alert alert-warning'));
     if(r.nota)card.append(nodo('p',r.nota,'fp-consulta-cobro-nota'));
     if(r.archivo && /^\/cobros\/respaldo\/\d+\/archivo\/$/.test(r.archivo.url)) { var a=nodo('a','Abrir '+r.archivo.nombre,'btn btn-outline-secondary');a.href=r.archivo.url;a.target='_blank';a.rel='noopener';card.append(a); }
     var meta=nodo('dl',null,'fp-consulta-cobro-datos');dato(meta,'Referencia',r.referencia);dato(meta,'Registrado por',r.registrado_por && (r.registrado_por.nombre || r.registrado_por.username));dato(meta,'Fecha',fecha(r.registrado_en));
     if(r.revisado_por) {dato(meta,'Revisado por',r.revisado_por.nombre || r.revisado_por.username);dato(meta,'Fecha de revisión',fecha(r.revisado_en));} if(r.motivo_revision)dato(meta,'Motivo',r.motivo_revision);card.append(meta);
     var acciones=nodo('div',null,'fp-cobros-acciones');
     if(r.puede_editar)acciones.append(boton('Corregir respaldo',function(){editor('editar',r);}));
     if(datos.capacidades.puede_revisar)acciones.append(boton('Revisar',function(){editor('revision',r);}));
     var lista=nodo('ol',null,'fp-cobros-historial');lista.hidden=true;var btn=boton('Ver historial',function(){historial(r,lista,btn);});acciones.append(btn);card.append(acciones,lista);contenido.append(card);
   });
   el('fpCobroNuevo').textContent=datos.cuenta_por_cobrar ? 'Registrar cobro' : 'Añadir respaldo';
   el('fpCobroNuevo').hidden=!datos.capacidades.puede_registrar || datos.factura.anulada_sri || Boolean(datos.cuenta_por_cobrar && Number(datos.cuenta_por_cobrar.saldo)<=0) || pendientes.has(s.url);
 }
 async function cargar(conservar) {
   if(consulta)consulta.abort();consulta=new AbortController();var version=++s.version;
   if(document.activeElement===el('fpConsultaCobroReintentar'))modal.querySelector('.close').focus();
   el('fpConsultaCobroReintentar').hidden=true; contenido.setAttribute('aria-busy','true');
   if(!conservar){mensaje('');contenido.replaceChildren(nodo('p','Consultando cobros…'));}
   try {
     var d=await fetch(s.url,{credentials:'same-origin',signal:consulta.signal}).then(leer);
     if(version!==s.version)return;
     pintar(d);
     if(pendientes.has(s.url)){mensaje('Hay un envío cuyo resultado no se pudo confirmar. Puedes consultar los respaldos y reintentar el mismo envío sin registrar otro abono.',true);el('fpCobroReenviar').hidden=false;}
     return true;
   }catch(e){if(e.name!=='AbortError' && version===s.version){mensaje(e.message,true);el('fpConsultaCobroReintentar').hidden=false;}}
   finally{if(version===s.version)contenido.setAttribute('aria-busy','false');}
 }
 async function enviar(p) {
   if(s.busy)return;ocupado(true);mensaje('');
   if(p.modo==='registro')pendientes.set(s.url,p);
   try {
     var d=await fetch(p.url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:p.datos}).then(leer);
     pendientes.delete(s.url);s.cambios=true;el('fpCobroReenviar').hidden=true;cerrarEditor();
     if(p.modo==='registro')pintar(d);else if(!await cargar(true)){ aviso.focus(); return; }
     mensaje(p.modo==='registro' ? (d.repetido ? 'Este envío ya estaba registrado. No se creó otro cobro.' : 'Registro guardado. El respaldo queda pendiente de revisión.') : p.modo==='revision' ? 'Revisión guardada. El saldo no cambia.' : 'Corrección guardada. Consulta el historial del respaldo.');
     aviso.focus();
   }catch(e){
     var incierto=!e.status || e.status>=500 || e.status<400;
     if(p.modo==='registro' && incierto){el('fpCobroReenviar').hidden=false;el('fpConsultaCobroReintentar').hidden=false;form.hidden=true;el('fpCobroNuevo').hidden=true;mensaje('No se pudo confirmar el resultado. Mantén esta página abierta: puedes consultar la ficha o reintentar el mismo envío con su clave, sin duplicarlo. Si recargas, comprueba primero los cobros registrados.',true);}
     else {pendientes.delete(s.url);el('fpCobroCampos').disabled=false;el('fpCobroPreparar').hidden=false;el('fpCobroConfirmacion').hidden=true;mensaje(e.message,true);if(incierto)el('fpConsultaCobroReintentar').hidden=false;}
     aviso.focus();
   }finally{ocupado(false);}
 }
 form.addEventListener('submit',function(e){
   e.preventDefault();if(s.busy)return;
   var archivo=el('fpCobroArchivo'),nota=el('fpCobroNota');
   archivo.setCustomValidity(archivo.files[0] && archivo.files[0].size>5*1048576 ? 'El archivo supera los 5 MB.' : '');
   nota.setCustomValidity(s.modo!=='revision' && !nota.value.trim() && !archivo.files.length && !(s.respaldo && s.respaldo.archivo) ? 'Adjunta un comprobante o escribe una nota interna.' : '');
   if(!form.reportValidity())return;
   var datos=new FormData(form); if(!archivo.files.length)datos.delete('archivo');
   var url=s.modo==='registro' ? s.url+'registrar/' : '/cobros/respaldo/'+s.respaldo.id+'/'+(s.modo==='editar'?'editar/':'revisar/');
   s.preparado={url:url,datos:datos,modo:s.modo};
   el('fpCobroConfirmacionTexto').textContent=s.modo==='registro' ? 'Importe: $'+datos.get('importe')+'. '+(s.datos.cuenta_por_cobrar ? 'Se registrará un abono y se actualizará el saldo.' : 'Se añadirá un respaldo a la factura al contado.') : s.modo==='revision' ? 'Estado: '+el('fpCobroEstado').selectedOptions[0].textContent+'. Esta acción no cambia el saldo.' : 'Se guardarán la nota, referencia y el archivo que hayas elegido. El historial conserva los cambios.';
   el('fpCobroCampos').disabled=true;el('fpCobroPreparar').hidden=true;el('fpCobroConfirmacion').hidden=false;el('fpCobroConfirmar').focus();
 });
 ['fpCobroNota','fpCobroArchivo'].forEach(function(id){el(id).addEventListener('input',function(){el('fpCobroNota').setCustomValidity('');el('fpCobroArchivo').setCustomValidity('');});});
 el('fpCobroEstado').addEventListener('change',function(){el('fpCobroMotivo').required=this.value==='rechazado';});
 el('fpCobroConfirmar').addEventListener('click',function(){if(s.preparado)enviar(s.preparado);});
 el('fpCobroVolver').addEventListener('click',function(){el('fpCobroCampos').disabled=false;el('fpCobroPreparar').hidden=false;el('fpCobroConfirmacion').hidden=true;el('fpCobroPreparar').focus();});
 el('fpCobroCancelar').addEventListener('click',function(){cerrarEditor();el('fpCobroNuevo').focus();});
 el('fpCobroNuevo').addEventListener('click',function(){editor('registro');});
 el('fpCobroReenviar').addEventListener('click',function(){var p=pendientes.get(s.url);if(p)enviar(p);});
 el('fpConsultaCobroReintentar').addEventListener('click',function(){cargar(false);});
 document.addEventListener('click',function(e){var b=e.target.closest('[data-cobros-url]');if(!b || !/^\/cobros\/factura\/\d+\/$/.test(b.dataset.cobrosUrl))return;e.preventDefault();s.url=b.dataset.cobrosUrl;s.disparador=b;s.datos=null;s.cambios=false;cerrarEditor();el('fpCobroNuevo').hidden=true;el('fpCobroReenviar').hidden=true;jQuery(modal).modal('show');cargar(false);});
 jQuery(modal).on('show.bs.modal',function(){var z=1050+20*jQuery('.modal.show').length;modal.style.zIndex=z;setTimeout(function(){jQuery('.modal-backdrop').last().addClass('fp-cobros-backdrop').css('z-index',z-5);},0);}).on('shown.bs.modal',function(){modal.querySelector('.close').focus();}).on('hide.bs.modal',function(e){if(s.busy){e.preventDefault();return;}s.version++;if(consulta)consulta.abort();if(modal.contains(document.activeElement))document.activeElement.blur();}).on('hidden.bs.modal',function(){jQuery('.fp-cobros-backdrop').remove();var padre=jQuery('.modal.show').last();if(padre.length){jQuery('body').addClass('modal-open');var bs=padre.data('bs.modal');if(bs && bs._enforceFocus)bs._enforceFocus();}if(s.disparador && s.disparador.isConnected){var destino=s.disparador;if(!destino.getClientRects().length){var grupo=destino.closest('.btn-group');destino=grupo && grupo.querySelector('[data-toggle=dropdown]');}if(destino)destino.focus();}document.dispatchEvent(new CustomEvent('fp-cobros:cerrado',{detail:{cambios:s.cambios}}));});
}());
