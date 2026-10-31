/* Maqueta aislada: no sube archivos, no guarda notas y no confirma pagos. */
(function(){'use strict';const $=id=>document.getElementById(id),file=$('fp-archivo');
function error(text){$('fp-error').textContent=text;$('fp-error').hidden=false;$('fp-error').focus();}
file.addEventListener('change',()=>{const f=file.files[0];$('fp-archivo-info').textContent=f?`Seleccionado: ${f.name} · ${(f.size/1024).toFixed(0)} KB · no enviado`:'';$('fp-quitar').hidden=!f;});
$('fp-quitar').addEventListener('click',()=>{file.value='';file.dispatchEvent(new Event('change'));file.focus();});
$('fp-medio').addEventListener('change',()=>{$('fp-efectivo').hidden=$('fp-medio').value!=='efectivo';});
$('fp-respaldo').addEventListener('submit',e=>{e.preventDefault();$('fp-error').hidden=true;$('fp-preview').hidden=true;const f=file.files[0],note=$('fp-nota').value.trim(),amount=$('fp-importe').value.trim().replace(',','.');
if(!/^\d+(\.\d{1,2})?$/.test(amount)||Number(amount)<=0)return error('Escribe un importe mayor que cero, con hasta dos decimales.');
if(!f&&!note)return error('Adjunta un comprobante o escribe una nota del cobro.');
if(f&&(f.size>5*1024*1024||!['application/pdf','image/jpeg','image/png'].includes(f.type)))return error('Selecciona PDF, JPG o PNG de hasta 5 MB para esta propuesta.');
const pairs=[['Medio de cobro',$('fp-medio').selectedOptions[0].textContent],['Importe registrado',`USD ${Number(amount).toFixed(2)}`],['Referencia',$('fp-referencia').value.trim()||'Sin referencia'],['Comprobante',f?`${f.name} (seleccionado, no enviado)`:'Sin archivo'],['Nota interna',note||'Sin nota'],['Autor','Vendedor de ejemplo']];const root=$('fp-detalle');root.replaceChildren();pairs.forEach(([name,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;root.append(dt,dd);});$('fp-preview').hidden=false;$('fp-preview-title').focus();});})();
