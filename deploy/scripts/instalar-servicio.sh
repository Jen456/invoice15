#!/bin/bash
# =============================================================================
# FacturaPorAquí — instala las piezas de servidor de un entorno en VM101 (root).
#
#   bash instalar-servicio.sh <entorno> --ensayo      solo comprueba (por defecto)
#   bash instalar-servicio.sh <entorno> --aplicar     plantilla nginx, unidad systemd,
#                                                     logrotate, variables no secretas
#   bash instalar-servicio.sh <entorno> --certificado certificado Let's Encrypt (DNS en gris
#                                                     o detrás de Cloudflare)
#   bash instalar-servicio.sh <entorno> --https       plantilla + HTTPS forzado (exige que
#                                                     Cloudflare no esté en modo SSL 'Off';
#                                                     revierte solo si queda en bucle)
#
# entorno: pruebas | produccion. El dominio y el puerto salen de /etc/facturaporaqui/<entorno>.env.
# No toca otros dominios: recarga (no reinicia) nginx tras `nginx -t`.
# =============================================================================
set -euo pipefail
umask 022

ENTORNO="${1:?Uso: $0 <pruebas|produccion> [--ensayo|--aplicar|--certificado|--https]}"
MODO="${2:---ensayo}"
case "$ENTORNO" in pruebas|produccion) ;; *) echo "Entorno no válido: $ENTORNO"; exit 2;; esac

USUARIO=facturaporaqui
ENVF=/etc/facturaporaqui/$ENTORNO.env
REPO_DEPLOY="$(cd "$(dirname "$0")/.." && pwd)"
HESTIA=/usr/local/hestia
TPL_DIR=$HESTIA/data/templates/web/nginx
TPL="fpa-$ENTORNO"
FALLAS=0
ok()  { echo "  [OK]  $*"; }
mal() { echo "  [FALLA] $*"; FALLAS=$((FALLAS+1)); }

[ -f "$ENVF" ] || { echo "No existe $ENVF"; exit 1; }
DOMINIO=$(sed -n 's/^ALLOWED_HOSTS=\([^,]*\).*/\1/p' "$ENVF")
PUERTO=$(sed -n 's/^FPA_PUERTO=//p' "$ENVF")
echo "FacturaPorAquí — servicio $ENTORNO ($DOMINIO, puerto $PUERTO) — modo $MODO — $(date -Is)"

echo "== Comprobaciones"
[ -n "$DOMINIO" ] && [ -n "$PUERTO" ] && ok "dominio y puerto en $ENVF" || mal "faltan ALLOWED_HOSTS o FPA_PUERTO en $ENVF"
grep -rqs "DOMAIN='$DOMINIO'" $HESTIA/data/users/$USUARIO/web.conf && ok "$DOMINIO existe en Hestia ($USUARIO)" || mal "$DOMINIO no está en Hestia bajo $USUARIO"
for f in hestia/nginx/fpa.tpl.in hestia/nginx/fpa.stpl.in systemd/facturaporaqui@.service logrotate/facturaporaqui; do
  [ -f "$REPO_DEPLOY/$f" ] && ok "fuente $f" || mal "falta $REPO_DEPLOY/$f"
done
if ss -ltn | grep -q "127.0.0.1:$PUERTO "; then echo "  [AVISO] el puerto $PUERTO ya escucha (¿servicio en marcha?)"; else ok "puerto $PUERTO libre"; fi
nginx -t >/dev/null 2>&1 && ok "nginx -t correcto" || mal "nginx -t falla antes de empezar"
dpkg -s libharfbuzz-subset0 >/dev/null 2>&1 && ok "libharfbuzz-subset0 instalado" || echo "  [AVISO] se instalará libharfbuzz-subset0 (subconjunto de fuentes para WeasyPrint)"
[ "$FALLAS" -eq 0 ] || { echo "RESULTADO: $FALLAS falla(s). No se aplica nada."; exit 1; }

render() {  # $1 = fuente .in, $2 = destino
  sed -e "s/@ENTORNO@/$ENTORNO/g" -e "s/@PUERTO@/$PUERTO/g" "$1" > "$2.nuevo"
  if [ -f "$2" ] && cmp -s "$2" "$2.nuevo"; then rm "$2.nuevo"; echo "  sin cambios: $2"; else mv "$2.nuevo" "$2"; echo "  escrito: $2"; fi
}

add_var() {  # añade VAR=valor al .env solo si la variable no existe
  grep -q "^$1=" "$ENVF" && { echo "  ya existe: $1"; return; }
  printf '%s=%s\n' "$1" "$2" >> "$ENVF"; echo "  añadida: $1"
}

case "$MODO" in
--ensayo)
  echo "RESULTADO DEL ENSAYO: correcto. Se escribirían $TPL_DIR/$TPL.{tpl,stpl},"
  echo "/etc/systemd/system/facturaporaqui@.service y /etc/logrotate.d/facturaporaqui."
  ;;
--aplicar)
  echo "== Paquete de fuentes para WeasyPrint"
  dpkg -s libharfbuzz-subset0 >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends libharfbuzz-subset0 >/dev/null
  echo "== Plantilla nginx de Hestia"
  render "$REPO_DEPLOY/hestia/nginx/fpa.tpl.in" "$TPL_DIR/$TPL.tpl"
  render "$REPO_DEPLOY/hestia/nginx/fpa.stpl.in" "$TPL_DIR/$TPL.stpl"
  chmod 644 "$TPL_DIR/$TPL.tpl" "$TPL_DIR/$TPL.stpl"
  echo "== systemd y logrotate"
  install -m 644 "$REPO_DEPLOY/systemd/facturaporaqui@.service" /etc/systemd/system/facturaporaqui@.service
  install -m 644 "$REPO_DEPLOY/logrotate/facturaporaqui" /etc/logrotate.d/facturaporaqui
  systemctl daemon-reload
  systemctl enable "facturaporaqui@$ENTORNO.service" >/dev/null 2>&1 && ok "facturaporaqui@$ENTORNO habilitado al arranque (se inicia con el primer despliegue)"
  echo "== Variables no secretas en $ENVF"
  add_var FPA_WORKERS "$([ "$ENTORNO" = produccion ] && echo 3 || echo 2)"
  add_var SECURE_HSTS_SECONDS "$([ "$ENTORNO" = produccion ] && echo 31536000 || echo 3600)"
  logrotate -d /etc/logrotate.d/facturaporaqui >/dev/null 2>&1 && ok "logrotate válido" || mal "logrotate -d falla"
  echo "RESULTADO: piezas instaladas con $FALLAS falla(s)."
  ;;
--certificado)
  echo "== DNS de $DOMINIO"
  IP_DNS=$(dig +short "$DOMINIO" A @1.1.1.1 | tail -1)
  case "$IP_DNS" in
    108.181.186.144) ok "$DOMINIO → 108.181.186.144 (nube gris)";;
    104.*|172.6[4-9].*|172.7[01].*|162.15[89].*|188.114.*|190.93.*|197.234.*|198.41.*|141.101.*|108.162.*|173.245.*|103.2[12].*|103.31.*)
      ok "$DOMINIO detrás de Cloudflare ($IP_DNS); el reto http-01 pasa por el proxy";;
    *) mal "$DOMINIO resuelve a '${IP_DNS:-nada}': crea el registro A"; exit 1;;
  esac
  echo "== Certificado Let's Encrypt (antes de la plantilla, como en el resto del servidor)"
  if grep "DOMAIN='$DOMINIO'" $HESTIA/data/users/$USUARIO/web.conf | grep -q "LETSENCRYPT='yes'"; then
    ok "ya tiene certificado LE"
  else
    $HESTIA/bin/v-add-letsencrypt-domain "$USUARIO" "$DOMINIO" "" no
  fi
  # v-add-letsencrypt-domain no siempre recarga nginx: se hace aquí tras comprobar.
  nginx -t >/dev/null 2>&1 && systemctl reload nginx && ok "nginx recargado" || mal "nginx -t falla"
  echo "  servido: $(echo | openssl s_client -connect 10.10.10.10:443 -servername "$DOMINIO" 2>/dev/null | openssl x509 -noout -subject -enddate | tr '\n' ' ')"
  echo "RESULTADO: certificado de $DOMINIO con $FALLAS falla(s)."
  ;;
--https)
  echo "== Modo SSL de Cloudflare"
  LOC=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 15 "https://$DOMINIO/login/" || true)
  case "$LOC" in
    http://*) mal "Cloudflare redirige HTTPS a HTTP (modo SSL 'Off'): pon Full (strict) antes de forzar HTTPS"; exit 1;;
  esac
  ok "Cloudflare no degrada HTTPS a HTTP"
  echo "== Plantilla $TPL y HTTPS forzado"
  $HESTIA/bin/v-change-web-domain-proxy-tpl "$USUARIO" "$DOMINIO" "$TPL" "" no
  $HESTIA/bin/v-add-web-domain-ssl-force "$USUARIO" "$DOMINIO" no 2>/dev/null || true
  nginx -t >/dev/null 2>&1 && systemctl reload nginx && ok "nginx recargado" || { mal "nginx -t falla tras la plantilla"; exit 1; }
  sleep 2
  CODIGO=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$DOMINIO/login/" || true)
  LOC=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 20 "https://$DOMINIO/login/" || true)
  if [ "$CODIGO" != "200" ]; then
    # 301 hacia sí mismo = modo Flexible (bucle); 525/526 = certificado no aceptado.
    mal "https://$DOMINIO/login/ → $CODIGO ${LOC:+(→ $LOC)}: se revierte la plantilla y el HTTPS forzado"
    $HESTIA/bin/v-delete-web-domain-ssl-force "$USUARIO" "$DOMINIO" no 2>/dev/null || true
    $HESTIA/bin/v-change-web-domain-proxy-tpl "$USUARIO" "$DOMINIO" default "" no
    nginx -t >/dev/null 2>&1 && systemctl reload nginx
    exit 1
  fi
  ok "https://$DOMINIO/login/ → 200 a través de Cloudflare"
  echo "  http → $(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 15 "http://$DOMINIO/login/" || true)"
  echo "RESULTADO: HTTPS de $DOMINIO con $FALLAS falla(s)."
  ;;
*) echo "Modo no válido: $MODO"; exit 2;;
esac
