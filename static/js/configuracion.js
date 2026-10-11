/* Vista previa orientativa: el servidor conserva la validación y reserva del número. */
(function () {
    'use strict';
    document.querySelectorAll('.fp-config-documento').forEach(function (section) {
        var output = section.querySelector('.fp-config-preview');
        var last = section.querySelector('input[name$="-last_number"]');
        function update() {
            var mode = section.querySelector('input[name$="-mode"]:checked');
            var next = '';
            if (mode && mode.value === 'nuevo') {
                next = section.dataset.punto + '-000000001';
            } else if (mode && mode.value === 'mantener') {
                next = section.dataset.proximo;
            } else if (mode && last) {
                var value = last.value.trim();
                var match = /^(?:(\d{3}-\d{3})-)?(\d{1,9})$/.exec(value);
                if (match && (!match[1] || match[1] === section.dataset.punto)) {
                    var number = Number(match[2]);
                    if (number >= 1 && number <= 999999998) {
                        next = section.dataset.punto + '-' + String(number + 1).padStart(9, '0');
                    }
                }
            }
            output.hidden = !next;
            output.querySelector('strong').textContent = next;
        }
        section.addEventListener('input', update);
        section.addEventListener('change', update);
        update();
    });
})();
