/* Animaciones de presentación; no modificar importes, planes ni formularios de pago. */
(function () {
    'use strict';
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    var cards = document.querySelectorAll('.pricing .plan,.fp-plan-options .fpa-plan-tarjeta');
    if ('IntersectionObserver' in window && !reduced.matches) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) { return; }
                observer.unobserve(entry.target);
                if (reduced.matches || !entry.target.animate) { return; }
                var animation = entry.target.animate([
                    {transform: 'translateY(16px)', opacity: .8},
                    {transform: 'translateY(0)', opacity: 1}
                ], {duration: 420, easing: 'ease-out'});
                var stop = function () { if (reduced.matches) { animation.cancel(); } };
                reduced.addEventListener('change', stop, {once: true});
            });
        }, {threshold: .12});
        cards.forEach(function (card) { observer.observe(card); });
    }
    document.querySelectorAll('.pricing [data-plan]').forEach(function (link) {
        link.addEventListener('click', function () {
            document.querySelectorAll('.pricing .plan').forEach(function (card) { card.classList.remove('fp-price-selected'); });
            link.closest('.plan').classList.add('fp-price-selected');
        });
    });
})();
