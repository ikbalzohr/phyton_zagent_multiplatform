#!/bin/bash
# Secrets are not command-line arguments or Docker environment configuration.
# Runtime process memory/environment and Docker/root remain trusted boundaries.
set -euo pipefail
set +x
for name in database_password bootstrap_password introspection_secret; do
    test -r "/run/secrets/$name" && test -s "/run/secrets/$name" || {
        printf 'Missing/unreadable required secret file: %s\n' "$name" >&2
        exit 78
    }
done
KC_DB_PASSWORD="$(</run/secrets/database_password)"
KC_BOOTSTRAP_ADMIN_PASSWORD="$(</run/secrets/bootstrap_password)"
ZAGENT_INTROSPECTION_SECRET="$(</run/secrets/introspection_secret)"
export KC_DB_PASSWORD KC_BOOTSTRAP_ADMIN_PASSWORD ZAGENT_INTROSPECTION_SECRET
exec /opt/keycloak/bin/kc.sh "$@"
