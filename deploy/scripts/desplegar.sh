#!/bin/bash
# =============================================================================
# FacturaPorAquí — publica una versión en VM101 (root).
#
#   bash desplegar.sh <entorno> <ref-git> [--primera-instalacion <correo-admin>]
#   bash desplegar.sh <entorno> --revertir           vuelve a la versión anterior
#
# Pasos: git archive de <ref> → venv con hashes → volcado previo de la base →
# migraciones → caché → estáticos → check --deploy → cambio atómico de `current`
# → reinicio del servicio → comprobación de salud (si falla, vuelve a la anterior).
# Las órdenes de Django corren como el usuario facturaporaqui (los archivos que
# crean quedan con su dueño). Conserva las 5 últimas versiones.
# Variables opcionales: FPA_REPO (por defecto /root/invoice15/src) y
# FPA_STATIC_LIB (librerías de static/lib que aún no están en el repositorio).
# =============================================================================
set -euo pipefail
umask 027

ENTORNO="${1:?Uso: $0 <pruebas|produccion> <ref-git>|--revertir [--primera-instalacion correo]}"
REF="${2:?Falta la referencia git o --revertir}"
case "$ENTORNO" in pruebas|produccion) ;; *) echo "Entorno no válido"; exit 2;; esac

USUARIO=facturaporaqui
BASE=/opt/facturaporaqui/$ENTORNO
ENVF=/etc/facturaporaqui/$ENTORNO.env
REPO="${FPA_REPO:-/root/invoice15/src}"
STATIC_LIB="${FPA_STATIC_LIB:-/root/invoice15/static-lib}"
RESPALDOS=/home/$USUARIO/datos/$ENTORNO/respaldos
CRED_DIR=/root/invoice15/credenciales
UV=/root/.local/bin/uv
SERVICIO="facturaporaqui@$ENTORNO.service"
TS=$(date +%Y%m%d-%H%M%S)

PUERTO=$(sed -n 's/^FPA_PUERTO=//p' "$ENVF")
DOMINIO=$(sed -n 's/^ALLOWED_HOSTS=\([^,]*\).*/\1/p' "$ENVF")

django() {  # orden de manage.py como facturaporaqui, con las variables del entorno
  local dir="$1"; shift
  runuser -u "$USUARIO" -- env -C "$dir" PGOPTIONS="${PGOPTIONS:-}" bash -c 'set -a; . "$0"; set +a; exec .venv/bin/python manage.py "$@"' "$ENVF" "$@"
}

salud() {
  local codigo
  for _ in $(seq 1 20); do
    codigo=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMINIO" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:$PUERTO/login/" || true)
    [ "$codigo" = "200" ] && { echo "  salud: /login/ → 200"; return 0; }
    sleep 1
  done
  echo "  salud: /login/ → ${codigo:-sin respuesta}"; return 1
}

activar() {  # cambio atómico del enlace current
  ln -sfn "$1" "$BASE/current.nuevo" && mv -Tf "$BASE/current.nuevo" "$BASE/current"
}

if [ "$REF" = "--revertir" ]; then
  ACTUAL=$(readlink -f "$BASE/current")
  ANTERIOR=$(ls -1dt "$BASE"/releases/*/ | sed 's:/$::' | grep -vx "$ACTUAL" | head -1)
  [ -n "$ANTERIOR" ] || { echo "No hay versión anterior"; exit 1; }
  echo "Revirtiendo $ENTORNO: $(basename "$ACTUAL") → $(basename "$ANTERIOR")"
  echo "AVISO: el código vuelve atrás; la base NO (si hubo migraciones, restaurar el volcado previo de $RESPALDOS)."
  activar "$ANTERIOR"; systemctl restart "$SERVICIO"; salud; exit $?
fi

PRIMERA=""; CORREO_ADMIN=""
if [ "${3:-}" = "--primera-instalacion" ]; then PRIMERA=1; CORREO_ADMIN="${4:?Falta el correo del administrador}"; fi

COMMIT=$(git -C "$REPO" rev-parse --verify "$REF^{commit}")
CORTO=${COMMIT:0:8}
REL="$BASE/releases/$TS-$CORTO"
echo "FacturaPorAquí — despliegue $ENTORNO — $CORTO ($(git -C "$REPO" log -1 --format=%s "$COMMIT")) — $(date -Is)"

echo "== 1. Código"
install -d -m 750 -o root -g "$USUARIO" "$REL"
git -C "$REPO" archive --format=tar "$COMMIT" | tar -x -C "$REL"
echo "$COMMIT" > "$REL/REVISION"
if [ -d "$STATIC_LIB" ] && [ ! -d "$REL/static/lib" ]; then
  cp -a "$STATIC_LIB" "$REL/static/lib"; echo "  static/lib copiado desde $STATIC_LIB (fuera del repositorio)"
elif [ ! -d "$REL/static/lib" ]; then
  echo "  AVISO: no hay static/lib: las pantallas se verán sin estilos ni JavaScript"
fi

echo "== 2. Entorno virtual (dependencias con hashes)"
"$UV" venv -q --python /usr/bin/python3.12 "$REL/.venv"
VIRTUAL_ENV="$REL/.venv" "$UV" pip sync -q --require-hashes "$REL/requirements/base.txt"
chown -R root:"$USUARIO" "$REL"; chmod -R g+rX,o-rwx "$REL"

echo "== 3. Volcado previo de la base"
set -a; . "$ENVF"; set +a
install -d -m 700 "$RESPALDOS"
DUMP="$RESPALDOS/pre-$TS-$CORTO.dump"
# Con RLS forzada, pg_dump exige --enable-row-security y app.platform=on para ver todas las filas.
PGOPTIONS="-c app.platform=on" pg_dump --enable-row-security --format=custom --no-owner --file="$DUMP" "$DATABASE_URL"
chmod 600 "$DUMP"; echo "  $DUMP ($(du -h "$DUMP" | cut -f1))"
ls -1t "$RESPALDOS"/pre-*.dump 2>/dev/null | tail -n +31 | xargs -r rm -f   # conserva 30

echo "== 4. Migraciones, caché, estáticos y comprobación"
PGOPTIONS="-c app.platform=on" django "$REL" migrate --noinput   # migraciones de datos sobre todas las empresas
django "$REL" createcachetable
django "$REL" collectstatic --noinput --clear -v 0
chmod -R a+rX "$STATIC_ROOT"   # nginx (www-data) lee los estáticos
django "$REL" check --deploy --fail-level ERROR

if [ -n "$PRIMERA" ]; then
  echo "== 4b. Instalación base (primera vez)"
  TMPD=$(mktemp -d); chown "$USUARIO" "$TMPD"; chmod 700 "$TMPD"
  django "$REL" start_installation --admin-correo "$CORREO_ADMIN" --archivo-credenciales "$TMPD/admin.txt"
  install -d -m 700 "$CRED_DIR"
  install -m 600 -o root -g root "$TMPD/admin.txt" "$CRED_DIR/admin-$ENTORNO-$TS.txt"; rm -rf "$TMPD"
  echo "  credenciales del administrador: $CRED_DIR/admin-$ENTORNO-$TS.txt (0600)"
fi

echo "== 5. Activación"
ANTES=$(readlink -f "$BASE/current" 2>/dev/null || true)
activar "$REL"
systemctl restart "$SERVICIO"
if ! salud; then
  echo "FALLO de salud: se restaura la versión anterior"
  journalctl -u "$SERVICIO" -n 30 --no-pager || true
  if [ -n "$ANTES" ] && [ -d "$ANTES" ]; then activar "$ANTES"; systemctl restart "$SERVICIO"; salud || true; fi
  exit 1
fi

echo "== 6. Limpieza de versiones antiguas (se conservan 5)"
ls -1dt "$BASE"/releases/*/ | tail -n +6 | xargs -r rm -rf
echo "RESULTADO: $ENTORNO en $CORTO. Revertir: bash $0 $ENTORNO --revertir"
