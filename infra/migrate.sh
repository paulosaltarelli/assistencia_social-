#!/bin/sh
set -eu
: "${SOCIAL_ADMIN_PASSWORD:?}"
SOCIAL_DB_PASSWORD="$SOCIAL_ADMIN_PASSWORD" SOCIAL_DB_USER=postgres exec python manage.py migrate "$@"
