#!/bin/bash
# =============================================================================
# FacturaPorAquí — landing estática en https://facturaporaqui.com (VM101, root).
#
#   bash publicar-landing.sh --ensayo            solo comprueba (por defecto)
#   bash publicar-landing.sh --dominio           dominio web en Hestia (alias www,
#                                                sin correo ni zona DNS) + plantilla
#   bash publicar-landing.sh --certificado       Let's Encrypt para raíz y www
#   bash publicar-landing.sh --https             plantilla fpa-landing, HTTPS forzado, HSTS
#   bash publicar-landing.sh --publicar <ref>    copia landing/index.html y landing/assets/ de <ref>
#
# No toca la aplicación (app.facturaporaqui.com), el DNS ni otros dominios.
# Recarga (no reinicia) nginx y Apache tras comprobar su configuración.
# =============================================================================
set -euo pipefail
umask 022

MODO="${1:---ensayo}"
USUARIO=facturaporaqui
DOMINIO=facturaporaqui.com
ALIAS=www.facturaporaqui.com
TPL=fpa-landing
HESTIA=/usr/local/hestia
REPO="${FPA_REPO:-/root/invoice15/src}"
DEPLOY="$(cd "$(dirname "$0")/.." && pwd)"
DOCROOT=/home/$USUARIO/web/$DOMINIO/public_html
IPWEB=$($HESTIA/bin/v-list-sys-ips plain | head -1 | cut -f1)
FALLAS=0
ok()  { echo "  [OK]  $*"; }
mal() { echo "  [FALLA] $*"; FALLAS=$((FALLAS+1)); }
recargar() {
  nginx -t >/dev/null 2>&1 || { mal "nginx -t falla"; return 1; }
  apache2ctl configtest >/dev/null 2>&1 || { mal "apache2ctl configtest falla"; return 1; }
  systemctl reload nginx apache2 && ok "nginx y Apache recargados"
}
existe() { grep -qs "DOMAIN='$DOMINIO'" $HESTIA/data/users/$USUARIO/web.conf; }
instalar_plantilla() {
  for ext in tpl stpl; do
    install -m 644 "$DEPLOY/hestia/nginx/$TPL.$ext" "$HESTIA/data/templates/web/nginx/$TPL.$ext"
  done
  ok "plantilla $TPL instalada en Hestia"
}
controles() {
  for d in app.facturaporaqui.com muebleselroi.com suprohosting.com unireefer.com; do
    echo "  control $d: $(curl -s -o /dev/null -w '%{http_code}' --resolve "$d:443:$IPWEB" "https://$d/" || true)"
  done
}

echo "FacturaPorAquí — landing $DOMINIO — modo $MODO — $(date -Is)"
case "$MODO" in
--ensayo)
  existe && echo "  [AVISO] $DOMINIO ya existe en Hestia" || ok "$DOMINIO libre en Hestia"
  grep -rqsE "DOMAIN='(www\.)?$DOMINIO'" $HESTIA/data/users/*/{dns,mail}.conf && mal "hay zona DNS o correo de $DOMINIO en Hestia" || ok "sin zona DNS ni correo de $DOMINIO en Hestia (se conservan los de Cloudflare)"
  [ -f "$DEPLOY/hestia/nginx/$TPL.tpl" ] && [ -f "$DEPLOY/hestia/nginx/$TPL.stpl" ] && ok "fuentes de la plantilla" || mal "faltan las fuentes de la plantilla"
  for h in $DOMINIO $ALIAS; do echo "  DNS $h: $(dig +short $h A @1.1.1.1 | tr '\n' ' ')"; done
  nginx -t >/dev/null 2>&1 && ok "nginx -t correcto" || mal "nginx -t falla"
  echo "RESULTADO DEL ENSAYO: $FALLAS falla(s). No se ha cambiado nada."
  ;;
--dominio)
  if existe; then ok "$DOMINIO ya existe"; else
    $HESTIA/bin/v-add-web-domain "$USUARIO" "$DOMINIO" "" no "$ALIAS"
    ok "dominio web $DOMINIO (alias $ALIAS) creado bajo $USUARIO"
  fi
  instalar_plantilla
  recargar
  controles
  ;;
--certificado)
  if grep "DOMAIN='$DOMINIO'" $HESTIA/data/users/$USUARIO/web.conf | grep -q "LETSENCRYPT='yes'"; then
    ok "ya tiene certificado LE"
  else
    $HESTIA/bin/v-add-letsencrypt-domain "$USUARIO" "$DOMINIO" "$ALIAS" no
  fi
  recargar
  echo "  servido: $(echo | openssl s_client -connect "$IPWEB:443" -servername "$DOMINIO" 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName -enddate 2>/dev/null | tr '\n' ' ')"
  ;;
--https)
  LOC=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 15 "https://$DOMINIO/" || true)
  case "$LOC" in http://*) mal "Cloudflare (u origen) devuelve HTTPS → HTTP: no se fuerza HTTPS"; exit 1;; esac
  instalar_plantilla
  $HESTIA/bin/v-change-web-domain-proxy-tpl "$USUARIO" "$DOMINIO" "$TPL" "" no
  $HESTIA/bin/v-add-web-domain-ssl-force "$USUARIO" "$DOMINIO" no 2>/dev/null || true
  $HESTIA/bin/v-add-web-domain-ssl-hsts "$USUARIO" "$DOMINIO" no 2>/dev/null || true
  recargar
  sleep 2
  echo "  https://$DOMINIO/ → $(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$DOMINIO/")"
  echo "  https://$ALIAS/ → $(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 20 "https://$ALIAS/")"
  echo "  http://$DOMINIO/ → $(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 20 "http://$DOMINIO/")"
  controles
  ;;
--publicar)
  # Publica landing/index.html y landing/assets/ de <ref>. Los .md de landing/
  # (notas de marca) no se publican. Copia de seguridad previa en private/.
  REF="${2:?Falta la referencia git}"
  COMMIT=$(git -C "$REPO" rev-parse --verify "$REF^{commit}")
  TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
  PRIV=/home/$USUARIO/web/$DOMINIO/private
  RESPALDO="$PRIV/landing-antes-$(date +%Y%m%d%H%M%S).tar.gz"
  tar -czf "$RESPALDO" -C "$DOCROOT" . && chown "$USUARIO:$USUARIO" "$RESPALDO" && ok "copia previa: $RESPALDO"
  RUTAS=(landing/index.html)
  git -C "$REPO" ls-tree -d --name-only "$COMMIT" landing/assets | grep -q . && RUTAS+=(landing/assets)
  git -C "$REPO" archive "$COMMIT" "${RUTAS[@]}" | tar -x -C "$TMPD"
  if [ -d "$TMPD/landing/assets" ]; then
    find "$TMPD/landing/assets" -type f ! -iregex '.*\.\(png\|jpe?g\|webp\|svg\|ico\|css\|js\|woff2?\)$' -print -delete | sed 's/^/  [AVISO] no se publica: /'
    rsync -r --delete --chmod=D755,F644 --chown="$USUARIO:$USUARIO" "$TMPD/landing/assets/" "$DOCROOT/assets/"
    ok "assets/ publicado ($(find "$DOCROOT/assets" -type f | wc -l) archivos)"
  fi
  install -m 644 -o "$USUARIO" -g "$USUARIO" "$TMPD/landing/index.html" "$DOCROOT/.index.html.nuevo"
  mv -f "$DOCROOT/.index.html.nuevo" "$DOCROOT/index.html"
  echo "${COMMIT}" > "$TMPD/REVISION" && install -m 644 -o "$USUARIO" -g "$USUARIO" "$TMPD/REVISION" "$PRIV/landing-REVISION"
  LOCAL=$(sha256sum "$DOCROOT/index.html" | cut -d' ' -f1)
  SERVIDO=$(curl -s --resolve "$DOMINIO:443:$IPWEB" "https://$DOMINIO/" | sha256sum | cut -d' ' -f1)
  [ "$LOCAL" = "$SERVIDO" ] && ok "index.html publicado (${COMMIT:0:8}) y servido idéntico (sha256 ${LOCAL:0:12})" || mal "lo servido no coincide con lo publicado"
  # Cada recurso local citado por index.html debe responder 200 en el origen.
  for r in $(grep -oE '(src|href)="[^"#:]+\.(png|jpe?g|webp|svg|ico|css|js)"' "$DOCROOT/index.html" | cut -d'"' -f2 | sort -u); do
    c=$(curl -s -o /dev/null -w '%{http_code}' --resolve "$DOMINIO:443:$IPWEB" "https://$DOMINIO/${r#/}")
    [ "$c" = 200 ] && ok "recurso $r → 200" || mal "recurso $r → $c"
  done
  echo "  revertir: tar -xzf $RESPALDO -C $DOCROOT (como $USUARIO)"
  ;;
*) echo "Modo no válido: $MODO"; exit 2;;
esac
[ "$FALLAS" -eq 0 ] || exit 1
