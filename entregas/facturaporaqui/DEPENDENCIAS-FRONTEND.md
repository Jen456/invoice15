# Frontend de FacturaPorAquí

Tema compartido: `static/css/facturaporaqui.css`, cargado después de los estilos de cada pantalla. Conserva Bootstrap 4/AdminLTE 3, permisos y formularios existentes. Los valores de color se definen como variables CSS. Los gráficos usan la misma paleta y respetan movimiento reducido.

## Dependencias
El checkout original no incluye `static/lib`. Para recuperar 37 archivos públicos en las rutas existentes:

```bash
python deploy/python/install_frontend.py
```

Los archivos se descargan desde jsDelivr mediante HTTPS y permanecen en el directorio ignorado `static/lib`. El instalador no reemplaza archivos existentes. Debe ejecutarse también en el servidor antes de `collectstatic`, o transferirse la carpeta de dependencias completa desde una instalación verificada.

Sigue pendiente recuperar los archivos originales de FormValidation 1.9.0 y su licencia, además de las bibliotecas específicas de otras pantallas (exportaciones, calendarios, etc.). No se han sustituido ni desactivado validaciones. Los formularios que dependen de estos archivos muestran errores JavaScript y no están completamente verificados.

## Validación local
Django check, autenticación, renderizado de dos gráficos, listado de categorías y presentación de formulario. Dashboard móvil de 390px sin desbordamiento horizontal. Los datos locales están vacíos. No se modificaron datos de producción ni se desplegó al dominio. Revisar formularios y pantallas específicas con todas las bibliotecas presentes antes de publicar.
