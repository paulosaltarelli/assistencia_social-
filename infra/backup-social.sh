#!/usr/bin/env bash
set -euo pipefail
umask 077
projeto=/opt/social-prefeituras
destino=/var/backups/social-prefeituras
chave=/root/.social-prefeituras/recuperacao
install -d -m 0700 "$destino/diarios"
exec 9>"$destino/diarios/.lock"
flock -n 9 || exit 0
cd "$projeto"
db() { docker compose -p social-prefeituras -f compose.yaml -f compose.prod.yaml exec -T social-db "$@"; }
bytes=$(db psql -XAtq -U postgres -d social -c 'SELECT pg_database_size(current_database())')
livre=$(df --output=avail -B1 "$destino" | tail -1)
if (( livre < bytes + 10 * 1024 ** 3 )); then
    echo 'Espaço insuficiente para criar o backup social com a reserva de disco da VPS.' >&2
    exit 1
fi
cd "$destino/diarios"
hoje=$(date -u +%F)
arquivo="social-$hoje.dump.gpg"
if [[ -f "$arquivo.sha256" ]]; then
    sha256sum --check "$arquivo.sha256"
    exit 0
fi
parcial=$(mktemp .social-novo.XXXXXXXX)
trap 'rm -f -- "$parcial"' EXIT
db pg_dump -U postgres -d social --format=custom | gpg --batch --yes --pinentry-mode loopback --passphrase-file "$chave" --symmetric --cipher-algo AES256 -o "$parcial"
gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$chave" --decrypt "$parcial" | {
    db pg_restore --list > /dev/null
    cat > /dev/null
}
mv -- "$parcial" "$arquivo"
sha256sum -- "$arquivo" > "$arquivo.sha256"
sha256sum --check "$arquivo.sha256"
# Exclusiva da série diária fictícia. Cópias de implantação ficam no diretório pai.
find . -maxdepth 1 -type f \( -name 'social-????-??-??.dump.gpg' -o -name 'social-????-??-??.dump.gpg.sha256' \) -mtime +14 -delete
