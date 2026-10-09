// Registro: mostrar u ocultar la contraseña. La validación la hace el servidor.
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.btnShowPassword').forEach(function (boton) {
        boton.addEventListener('click', function () {
            var input = boton.closest('.input-group').querySelector('input');
            var icono = boton.querySelector('i');
            var visible = input.type === 'text';
            input.type = visible ? 'password' : 'text';
            icono.className = visible ? 'fas fa-eye' : 'fas fa-eye-slash';
            boton.setAttribute('aria-pressed', String(!visible));
        });
    });
});
