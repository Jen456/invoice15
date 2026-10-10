# formvalidation-1.9.0 (compatibilidad propia)

FormValidation es una librería comercial que **nunca estuvo en el repositorio**.
Esta carpeta conserva sus rutas para no modificar las 28 plantillas que la usan,
pero contiene una **implementación propia** del subconjunto de API que usa
FacturaPorAquí (núcleo, plugins Trigger, SubmitButton, Bootstrap, Icon, Excluded,
PasswordStrength y 10 validadores). `es6-shim.min.js` y `zxcvbn.js` son las
librerías oficiales (MIT) descargadas por `deploy/scripts/recuperar_static_lib.py`.

En el rediseño del frontend se sustituirá por validación nativa y del servidor.
