/* Prototipo aislado: estado solo en memoria, sin API, almacenamiento, emisión ni reservas de números. */
(function () {
'use strict';
const $ = id => document.getElementById(id);
const locales = [
 {code:'001', name:'Local Centro', address:'Av. de Ejemplo 100 · Ciudad de muestra', matriz:true, points:[
  {code:'001', name:'Caja principal', ready:true, factura:125, nc:9},
  {code:'002', name:'Ventas web', ready:true, factura:37, nc:2}]},
 {code:'002', name:'Local Norte', address:'Calle de Demostración 200 · Ciudad de muestra', matriz:false, points:[
  {code:'001', name:'Caja principal', ready:false}]}
];
let preferido='001-001', documento=null, paso=1, localDelPunto=null, modoSelector='preference';
function el(tag, cls, text) {const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function punto(id) {for(const local of locales)for(const p of local.points)if(`${local.code}-${p.code}`===id)return {local,p};return null;}
function announce(text) {$('estado').textContent=text;$('estado').hidden=false;}
function open(id) {$(id).showModal();}
function close(dialog) {dialog.close();}
function action(label, type, id, cls) {const b=el('button',cls||'fp-btn fp-secondary',label);b.type='button';b.dataset.action=type;if(id)b.dataset.id=id;return b;}
function renderCards() {
 const filter=$('buscar-local').value.trim().toLocaleLowerCase();const root=$('locales');root.replaceChildren();let shown=0;
 for(const local of locales) {
  const texto=[local.code,local.name,local.address,...local.points.map(p=>`${p.name} ${local.code}-${p.code}`)].join(' ').toLocaleLowerCase();
  if(filter&&!texto.includes(filter))continue;
  shown++;
  const card=el('article','fp-local-card');const head=el('div','fp-local-header');const title=el('div','fp-local-title');const labels=el('div');
  labels.append(el('span','fp-code',`ESTABLECIMIENTO ${local.code}`));const h=el('h2','',local.name);h.id=`titulo-${local.code}`;h.tabIndex=-1;labels.append(h);card.setAttribute('aria-labelledby',h.id);
  if(local.matriz)labels.append(el('span','fp-badge','Matriz · ejemplo'));
  const icon=el('span','fp-building','⌂');icon.setAttribute('aria-hidden','true');title.append(labels,icon);head.append(title,el('p','',local.address));
  const list=el('ul','fp-points');
  for(const p of local.points) {
   const id=`${local.code}-${p.code}`,li=el('li','fp-point'),row=el('div','fp-point-row');row.append(el('span','fp-point-name',p.name),el('span','fp-badge '+(p.ready?'fp-ready':'fp-pending'),p.ready?'Listo para emitir':'Falta numeración'));
   li.append(row,el('span','fp-code',id),el('small','',preferido===id?'Tu punto de trabajo en esta maqueta':p.ready?'Numeración de ejemplo configurada':'Configura los documentos antes de emitir'));
   li.append(action(p.ready?'Ver numeración →':'Revisar qué falta →','numbers',id,'fp-point-action'));list.append(li);
  }
  const footer=el('div','fp-local-footer');footer.append(action('＋ Agregar punto de emisión','add-point',local.code));card.append(head,list,footer);root.append(card);
 }
 $('cuenta-locales').textContent=String(locales.length);$('cuenta-puntos').textContent=String(locales.reduce((n,l)=>n+l.points.length,0));$('resultados').textContent=`${shown} de ${locales.length} locales`;$('sin-resultados').hidden=shown!==0;
 const current=punto(preferido);$('punto-actual').replaceChildren(document.createTextNode(`${current.local.name} · ${current.p.name} · `),el('span','fp-code-unbroken',preferido));
}
function renderDocument() {
 if(!documento)return;
 const {local,p}=punto(documento);$('documento-punto').textContent=`${local.name} · ${p.name}`;$('documento-direccion').textContent=local.address;$('documento-codigo').textContent=documento;
 $('numero-preview').textContent=`${documento}-${String(p.factura).padStart(9,'0')}`;
 $('preferencia-distinta').hidden=preferido===documento;
}
function navigate() {const invoice=location.hash==='#facturacion';$('vista-locales').hidden=invoice;$('vista-facturacion').hidden=!invoice;if(invoice&&!documento)documento=preferido;renderDocument();document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===(invoice?'facturacion':'locales'))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});}
function clearErrors(form) {form.querySelectorAll('.fp-error').forEach(e=>{e.textContent='';});form.querySelectorAll('[aria-invalid]').forEach(e=>e.removeAttribute('aria-invalid'));}
function invalid(inputId, errorId, text) {$(inputId).setAttribute('aria-invalid','true');$(errorId).textContent=text;}
function validCode(s) {return /^(?!000)\d{3}$/.test(s);}
function validateLocal() {
 clearErrors($('form-local'));
 if(paso===1) {
  const code=$('local-code').value.trim();
  if(!validCode(code))invalid('local-code','error-code','Escribe tres dígitos, del 001 al 999.');
  else if(locales.some(l=>l.code===code))invalid('local-code','error-code','Ese establecimiento ya está registrado. Puedes agregarle otro punto.');
  if(!$('local-name').value.trim())invalid('local-name','error-name','Pon un nombre que tu equipo pueda reconocer.');
  if(!$('local-address').value.trim())invalid('local-address','error-address','Escribe la dirección de este local.');
 } else if(paso===2) {
  if(!validCode($('local-point-code').value.trim()))invalid('local-point-code','error-point_code','Escribe tres dígitos, del 001 al 999.');
  if(!$('local-point-description').value.trim())invalid('local-point-description','error-point_description','Escribe un nombre para este punto.');
 } else if(!$('confirmar-local').checked)invalid('confirmar-local','error-confirmar','Confirma que revisaste los datos.');
 const first=$('form-local').querySelector('[aria-invalid=true]');if(first){first.focus();return false;}return true;
}
function summary() {
 const root=$('resumen-local');root.replaceChildren();const values=[['Local',$('local-name').value.trim()],['Establecimiento',$('local-code').value.trim()],['Dirección',$('local-address').value.trim()],['Punto',$('local-point-description').value.trim()],['Código completo',`${$('local-code').value.trim()}-${$('local-point-code').value.trim()}`]];
 for(const [k,v] of values)root.append(el('dt','',k),el('dd','',v));
}
function setStep(n) {paso=n;document.querySelectorAll('[data-step]').forEach(e=>e.hidden=Number(e.dataset.step)!==n);document.querySelectorAll('[data-step-label]').forEach(e=>{if(Number(e.dataset.stepLabel)===n)e.setAttribute('aria-current','step');else e.removeAttribute('aria-current');});$('local-atras').textContent=n===1?'Cancelar':'← Atrás';$('local-siguiente').textContent=n===1?'Continuar al punto →':n===2?'Revisar datos →':'Crear en esta maqueta';if(n===3)summary();if($('dialogo-local').open)(n===1?$('local-code'):n===2?$('local-point-code'):$('confirmar-local')).focus();}
function combined() {$('codigo-combinado').textContent=`${$('local-code').value.trim()||'___'}-${$('local-point-code').value.trim()||'___'}`;}
$('agregar-local').addEventListener('click',()=>{$('form-local').reset();clearErrors($('form-local'));setStep(1);combined();open('dialogo-local');});
$('local-code').addEventListener('input',combined);$('local-point-code').addEventListener('input',combined);
$('local-atras').addEventListener('click',()=>paso===1?close($('dialogo-local')):setStep(paso-1));
$('form-local').addEventListener('submit',e=>{e.preventDefault();if(!validateLocal())return;if(paso<3){setStep(paso+1);return;}
 const local={code:$('local-code').value.trim(),name:$('local-name').value.trim(),address:$('local-address').value.trim(),matriz:false,points:[{code:$('local-point-code').value.trim(),name:$('local-point-description').value.trim(),ready:false}]};locales.push(local);close($('dialogo-local'));$('buscar-local').value='';renderCards();announce(`${local.name} agregado al ejemplo. Su punto está pendiente de numeración. No se guardó en el sistema.`);$(`titulo-${local.code}`).focus();});
$('form-punto').addEventListener('submit',e=>{e.preventDefault();clearErrors(e.currentTarget);const code=$('punto-code').value.trim(),name=$('punto-description').value.trim();
 if(!validCode(code))invalid('punto-code','error-punto-code','Escribe tres dígitos, del 001 al 999.');else if(localDelPunto.points.some(p=>p.code===code))invalid('punto-code','error-punto-code','Este código ya existe dentro de este local.');
 if(!name)invalid('punto-description','error-punto-description','Escribe el nombre del punto.');const first=e.currentTarget.querySelector('[aria-invalid=true]');if(first){first.focus();return;}
 localDelPunto.points.push({code,name,ready:false});close($('dialogo-punto'));renderCards();announce(`Punto ${localDelPunto.code}-${code} agregado a ${localDelPunto.name} en la maqueta. Falta configurar su numeración.`);$(`titulo-${localDelPunto.code}`).focus();});
function selectPoint(mode) {
 modoSelector=mode;const actual=mode==='document'?documento:preferido;$('selector-titulo').textContent=mode==='document'?'Cambiar el punto de este borrador':'¿Desde dónde vas a trabajar?';$('selector-ayuda').textContent=mode==='document'?'Revisa el local antes de cambiar este borrador. Tu punto preferido no cambiará.':'Esta preferencia se usará para nuevos borradores. Los que ya abriste conservarán su punto.';const root=$('opciones-puntos');root.replaceChildren();
 for(const local of locales) {const group=el('fieldset','fp-select-group');group.append(el('legend','',`${local.code} · ${local.name}`));for(const p of local.points){const id=`${local.code}-${p.code}`,label=el('label','fp-point-option'),radio=el('input');radio.type='radio';radio.name='demo_point';radio.value=id;radio.checked=id===actual;radio.disabled=!p.ready;const content=el('span');content.append(el('strong','',p.name),el('small','',`${id} · ${p.ready?'Listo para emitir':'Falta configurar la numeración'}`));label.append(radio,content);group.append(label);}root.append(group);}open('dialogo-selector');
}
$('form-selector').addEventListener('submit',e=>{e.preventDefault();const option=e.currentTarget.querySelector('input:checked:not(:disabled)');if(!option)return;if(modoSelector==='document')documento=option.value;else preferido=option.value;close($('dialogo-selector'));renderCards();renderDocument();announce(modoSelector==='document'?'Punto del borrador actualizado en el ejemplo.':'Punto preferido actualizado en el ejemplo. Los borradores abiertos conservan su punto.');});
function showNumbers(id) {const {local,p}=punto(id);$('numeracion-local').textContent=`${local.name} · ${p.name} · ${id}`;const root=$('numeraciones');root.replaceChildren();
 for(const [name,next] of [['Facturas',p.factura],['Notas de crédito',p.nc]]) {const article=el('article');article.append(el('h3','',name));if(p.ready){const dl=el('dl');dl.append(el('dt','','Último utilizado'),el('dd','',`${id}-${String(next-1).padStart(9,'0')}`),el('dt','','Próximo de referencia'),el('dd','',`${id}-${String(next).padStart(9,'0')}`));article.append(dl);}else article.append(el('span','fp-badge fp-pending','Pendiente de confirmar'),el('p','fp-muted','Indica si comienzas a emitir o si continúas la numeración de otro sistema.'));root.append(article);}open('dialogo-numeracion');
}
document.addEventListener('click',e=>{const closeButton=e.target.closest('[data-close]');if(closeButton){close(closeButton.closest('dialog'));return;}const b=e.target.closest('[data-action]');if(!b)return;if(b.dataset.action==='select-preference')selectPoint('preference');if(b.dataset.action==='select-document')selectPoint('document');if(b.dataset.action==='numbers')showNumbers(b.dataset.id);if(b.dataset.action==='add-point'){localDelPunto=locales.find(l=>l.code===b.dataset.id);$('form-punto').reset();clearErrors($('form-punto'));$('punto-local').textContent=`${localDelPunto.code} · ${localDelPunto.name} · ${localDelPunto.address}`;open('dialogo-punto');}});
$('buscar-local').addEventListener('input',renderCards);
$('nuevo-borrador').addEventListener('click',()=>{documento=preferido;renderDocument();announce('Nuevo borrador ilustrativo preparado con tu punto de trabajo. No se creó ninguna factura.');});
window.addEventListener('hashchange',navigate);renderCards();navigate();
})();
