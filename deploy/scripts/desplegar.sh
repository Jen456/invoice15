#!/bin/bash
# =============================================================================
# FacturaPorAquí — publica una versión en VM101 (root).
#
#   bash desplegar.sh <entorno> <ref-git> [--primera-instalacion <correo-admin>]
#   bash desplegar.sh <entorno> --revertir           vuelve a la versión anterior
#
# Pasos: git archive de <ref> → venv con hashes → volcado previo de la base →
# migraciones (con lock_timeout; si no consiguen un bloqueo, hasta 3 intentos) → caché
# → estáticos → check --deploy → cambio atómico de `current`
# → reinicio del servicio → comprobación de salud (si falla, vuelve a la anterior).
# Las órdenes de Django corren como el usuario facturaporaqui (los archivos que
# crean quedan con su dueño). Conserva las 5 últimas versiones; la de un despliegue que
# no queda activo (falla antes de activarse o no pasa la salud) se borra al salir. La salida
# de migrate queda en $BASE/registros/migrate-<versión>.log (se conservan 30), también si falla.
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
REGISTROS=$BASE/registros   # salida de migrate de cada despliegue: queda aunque se borre la carpeta de la versión
# migrate: lo que espera cada bloqueo, cuántas veces se intenta si no lo consigue y la pausa entre intentos (s)
LOCK_TIMEOUT_MIGRATE=5s; INTENTOS_MIGRATE=3; PAUSA_MIGRATE=10

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

# Al salir, por bien o por mal: si `current` no quedó en la versión de este despliegue, su carpeta se borra. Si se
# quedara, --revertir (que elige por fecha) y la limpieza (se conservan 5) la contarían como una versión más. Compara
# rutas resueltas (BASE podría ir por un enlace) y sin un `current` válido (primera instalación) no borra nada.
borrar_si_no_quedo_activa() {
  if [ -d "$REL" ] && [ -d "$BASE/current/" ] && [ "$(readlink -f "$BASE/current")" != "$(readlink -f "$REL")" ]; then
    # Un proceso que aún trabaja dentro (p. ej. un temporizador que arrancó desde current durante la salud) no se queda
    # sin su código: la carpeta se aparta con un nombre oculto, que ni --revertir ni la limpieza ven, y se borra a mano.
    local real usos aparte
    real=$(readlink -f "$REL")
    usos=$(find /proc/[0-9]*/cwd -maxdepth 0 \( -lname "$real" -o -lname "$real/*" \) -print -quit 2>/dev/null || true)
    if [ -n "$usos" ]; then
      aparte="$BASE/releases/.no-activa-$(basename "$REL")"
      mv -T -- "$REL" "$aparte"
      echo "  $(basename "$REL") no quedó activa y aún la usa un proceso: queda aparte en $aparte (bórrala cuando termine)"
    else
      echo "  se borra $(basename "$REL"): no quedó activa"; rm -rf -- "$REL"
    fi
  fi
}

# ¿Acabó un intento de migrate por lock_timeout (lock_not_available, 55P03) o por un interbloqueo
# (deadlock_detected, 40P01)? Lee su salida y mira la última excepción que imprimió Python, la de la última
# «Traceback (most recent call last):», que puede ir en la línea de «Applying …»: la de la base por su clase
# (psycopg.errors.LockNotAvailable o DeadlockDetected; el texto depende del idioma del servidor, la clase no), o el
# OperationalError con que Django la envuelve si esa es su causa directa. Un corte que solo aparece antes en la cadena
# no cuenta: así acaba contabilidad 0009 cuando agota sus propios intentos (RuntimeError). Un statement_timeout también
# es OperationalError, pero no es un bloqueo.
fallo_por_bloqueo() {
  awk '
    function clase(linea) { sub(/:.*/, "", linea); return linea }
    /Traceback \(most recent call last\):$/ { n++; separador[n] = ultima; excepcion[n] = ""; next }
    n && excepcion[n] == "" && /^[^ \t]/ { excepcion[n] = clase($0) }   # la primera sin sangría tras los marcos
    NF { ultima = $0 }
    END {
      bloqueo = "^psycopg2?\\.errors\\.(LockNotAvailable|DeadlockDetected)$"
      if (n && excepcion[n] ~ bloqueo) exit 0
      if (n > 1 && excepcion[n] == "django.db.utils.OperationalError" && excepcion[n-1] ~ bloqueo &&
          separador[n] == "The above exception was the direct cause of the following exception:") exit 0
      exit 1
    }'
}

# migrate con lock_timeout: una migración que topa con una transacción larga sobre una tabla que necesita no espera
# sin límite, con las escrituras de la aplicación en cola detrás de ella; se corta a los $LOCK_TIMEOUT_MIGRATE y lo que
# esperaba detrás pasa. Solo se repite ese corte o un interbloqueo, tras una pausa sin retener nada: cada migración va
# en su propia transacción (ninguna de core/ tiene atomic = False y las apps de terceros instaladas no migran), así que
# la cortada no deja nada, las anteriores quedan confirmadas y el intento siguiente sigue donde se quedó. Cualquier
# otro fallo para el despliegue, como antes. El SET LOCAL lock_timeout de 1 s de contabilidad 0009 manda en su
# transacción sobre el de la sesión, y si 0009 agota sus 8 intentos tampoco se repite: su mensaje dice qué hacer. La
# salida de cada intento va a $REGISTRO (sin el entorno ni la URL de la base) y, al terminar, a la pantalla.
migrar() {
  local intento estado desde
  for intento in $(seq 1 "$INTENTOS_MIGRATE"); do
    if [ "$intento" -gt 1 ]; then
      echo "  se repite migrate en $PAUSA_MIGRATE s (intento $intento de $INTENTOS_MIGRATE)"; sleep "$PAUSA_MIGRATE"
    fi
    echo "  migrate, intento $intento de $INTENTOS_MIGRATE (su salida, al terminar; mientras, en $REGISTRO)"
    echo "== intento $intento de $INTENTOS_MIGRATE, lock_timeout=$LOCK_TIMEOUT_MIGRATE, $(date -Is)" >> "$REGISTRO"
    desde=$(( $(wc -c < "$REGISTRO") + 1 ))   # el byte donde empieza la salida de este intento
    estado=0
    # app.platform=on: migraciones de datos sobre todas las empresas. Al archivo, no por una tubería con tee: así el
    # guion espera solo a migrate, también cuando llega una señal (ver los trap), y no a quien herede su salida. En una
    # subshell: si llega una señal, su trap corre después, fuera de la redirección, y lo que dice al salir se ve.
    ( PGOPTIONS="-c app.platform=on -c lock_timeout=$LOCK_TIMEOUT_MIGRATE" django "$REL" migrate --noinput ) \
      >> "$REGISTRO" 2>&1 || estado=$?
    tail -c +"$desde" "$REGISTRO"
    if [ "$estado" -eq 0 ]; then
      echo "  migrate: bien en el intento $intento de $INTENTOS_MIGRATE (salida en $REGISTRO)"; return 0
    fi
    if ! tail -c +"$desde" "$REGISTRO" | fallo_por_bloqueo; then
      echo "FALLO de migrate en el intento $intento de $INTENTOS_MIGRATE; no se repite (solo se repiten un lock_timeout"
      echo "  o un interbloqueo de la base) y la versión nueva no se activa. El error, arriba y en $REGISTRO"
      exit "$estado"
    fi
    echo "  migrate no consiguió un bloqueo en $LOCK_TIMEOUT_MIGRATE o chocó en un interbloqueo" \
         "(intento $intento de $INTENTOS_MIGRATE)"
  done
  echo "FALLO de migrate: en los $INTENTOS_MIGRATE intentos, una migración no consiguió en $LOCK_TIMEOUT_MIGRATE el"
  echo "  bloqueo de una tabla que necesita (o chocó en un interbloqueo). La cortada no cambió nada, las anteriores"
  echo "  quedan aplicadas y la versión nueva no se activa. Qué hacer: mira en pg_stat_activity y pg_locks qué"
  echo "  transacción retiene la tabla (una transacción larga, un respaldo con pg_dump en curso), espera a que termine"
  echo "  y repite el despliegue, mejor con poco tráfico. La salida de cada intento está en $REGISTRO"
  exit "$estado"
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
trap borrar_si_no_quedo_activa EXIT
# Con la señal atrapada, bash espera a que termine la orden en curso (migrate, collectstatic --clear…) antes de
# salir y limpiar; sin esto, un kill o pkill al script borraba la carpeta con migrate todavía corriendo dentro.
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
echo "FacturaPorAquí — despliegue $ENTORNO — $CORTO ($(git -C "$REPO" log -1 --format=%s "$COMMIT")) — $(date -Is)"

echo "== 1. Código"
install -d -m 750 -o root -g "$USUARIO" "$REL"
# entregas/ (documentación, capturas y material de redes) no forma parte de la aplicación
git -C "$REPO" archive --format=tar "$COMMIT" | tar -x -C "$REL" --anchored --exclude=entregas
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
install -d -m 700 "$REGISTROS"
REGISTRO="$REGISTROS/migrate-$TS-$CORTO.log"; : > "$REGISTRO"
ls -1t "$REGISTROS"/migrate-*.log | tail -n +31 | xargs -r rm -f   # conserva 30
migrar
django "$REL" createcachetable
django "$REL" collectstatic --noinput --clear -v 0
chmod -R a+rX "$STATIC_ROOT"   # nginx (www-data) lee los estáticos
django "$REL" check --deploy --fail-level ERROR
PGOPTIONS="-c app.platform=on" django "$REL" claves_firma   # las claves de firma se descifran con FPA_CLAVES_CIFRADO

if [ -n "$PRIMERA" ]; then
  echo "== 4b. Instalación base (primera vez)"
  TMPD=$(mktemp -d); chown "$USUARIO" "$TMPD"; chmod 700 "$TMPD"
  django "$REL" start_installation --admin-correo "$CORREO_ADMIN" --archivo-credenciales "$TMPD/admin.txt"
  install -d -m 700 "$CRED_DIR"
  install -m 600 -o root -g root "$TMPD/admin.txt" "$CRED_DIR/admin-$ENTORNO-$TS.txt"; rm -rf "$TMPD"
  echo "  credenciales del administrador: $CRED_DIR/admin-$ENTORNO-$TS.txt (0600)"
fi

echo "== 5. Activación"
ANTES=$(readlink -e "$BASE/current" 2>/dev/null || true)   # -e: vacío sin current (con -f, la ruta de current)
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
