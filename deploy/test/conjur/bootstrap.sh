#!/bin/bash
# Prepare Conjur OSS on CRC. Secret values come from files in the directory
# you pass. They are not arguments and this script does not print them.
#
#   umask 077
#   dir=$(mktemp -d)
#   printf '%s' 'db-password' > "$dir/db-password"
#   openssl rand -base64 32 > "$dir/data-key"
#   printf '%s' 'sales-password' > "$dir/postgres-sales"
#   printf '%s' 'oracle-password' > "$dir/oracle-sales"
#   printf '%s' 'deepseek-key' > "$dir/deepseek"
#   bash deploy/test/conjur/bootstrap.sh "$dir"
#
# Required files: db-password, data-key, postgres-sales, oracle-sales, deepseek.
# Optional: admin.api from a previous run, when the account already exists.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! -d "$1" ]]; then
  echo "kullanım: bash deploy/test/conjur/bootstrap.sh <gizli-dizin>" >&2
  exit 1
fi
src=$(cd "$1" && pwd)
for name in db-password data-key postgres-sales oracle-sales deepseek; do
  if [[ ! -s "$src/$name" ]]; then
    echo "eksik dosya: $name" >&2
    exit 1
  fi
done

root=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

python3 - "$src" "$work" <<'PY'
import sys
from pathlib import Path
from urllib.parse import quote

src = Path(sys.argv[1])
work = Path(sys.argv[2])
password = src.joinpath("db-password").read_text(encoding="utf-8").strip()
escaped = password.replace("'", "''")
sql = (
    "DO $body$\n"
    "BEGIN\n"
    "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'conjur') THEN\n"
    f"    CREATE ROLE conjur LOGIN PASSWORD '{escaped}';\n"
    "  ELSE\n"
    f"    ALTER ROLE conjur WITH LOGIN PASSWORD '{escaped}';\n"
    "  END IF;\n"
    "END\n"
    "$body$;\n"
    "SELECT 'CREATE DATABASE conjur OWNER conjur' "
    "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'conjur')\\gexec\n"
    "ALTER DATABASE conjur OWNER TO conjur;\n"
)
work.joinpath("init.sql").write_text(sql, encoding="utf-8")
url = "postgresql://conjur:" + quote(password, safe="") + "@postgres.agent-runtime.svc.cluster.local:5432/conjur"
work.joinpath("database-url").write_text(url, encoding="utf-8")
work.joinpath("data-key").write_bytes(src.joinpath("data-key").read_bytes())
values = work.joinpath("values")
values.mkdir()
for name in ("postgres-sales", "oracle-sales", "deepseek"):
    text = src.joinpath(name).read_text(encoding="utf-8")
    if text.endswith("\n"):
        text = text[:-1]
    values.joinpath(name).write_text(text, encoding="utf-8")
if src.joinpath("admin.api").is_file():
    work.joinpath("admin.api").write_bytes(src.joinpath("admin.api").read_bytes())
PY

oc apply -f "$root/namespace.yaml"
oc apply -f "$root/scc.yaml"
oc -n agent-runtime cp "$work/init.sql" deploy/postgres:/tmp/conjur-init.sql
oc -n agent-runtime exec deploy/postgres -- bash -c 'export PGPASSWORD="$POSTGRESQL_ADMIN_PASSWORD"; psql -U postgres -h 127.0.0.1 -d postgres -v ON_ERROR_STOP=1 -q -f /tmp/conjur-init.sql'
oc -n agent-runtime exec deploy/postgres -- rm -f /tmp/conjur-init.sql
rm -f "$work/init.sql"
oc -n conjur-test create secret generic conjur-db --from-file=url="$work/database-url" --dry-run=client -o yaml | oc apply -f -
oc -n conjur-test create secret generic conjur-data-key --from-file=key="$work/data-key" --dry-run=client -o yaml | oc apply -f -
rm -f "$work/database-url" "$work/data-key"
oc apply -f "$root/deployment.yaml"
oc apply -f "$root/networkpolicy.yaml"
oc -n conjur-test rollout status deploy/conjur --timeout=180s

pod=$(oc -n conjur-test get pod -l app=conjur -o jsonpath='{.items[0].metadata.name}')
if ! oc -n conjur-test exec "$pod" -- conjurctl account create agentrt >"$work/account.out" 2>&1; then
  if grep -q "already exists" "$work/account.out"; then
    echo "hesap zaten var"
    rm -f "$work/account.out"
  else
    grep -v -E 'API key|[A-Za-z0-9]{30,}' "$work/account.out" >&2 || true
    rm -f "$work/account.out"
    exit 1
  fi
else
  python3 - "$work" <<'PY'
import re
import sys
from pathlib import Path
work = Path(sys.argv[1])
text = work.joinpath("account.out").read_text(encoding="utf-8", errors="replace")
work.joinpath("account.out").unlink()
keys = re.findall(r"[A-Za-z0-9]{20,}", text)
if not keys:
    raise SystemExit("admin anahtarı okunamadı")
work.joinpath("admin.api").write_text(keys[-1], encoding="utf-8")
PY
fi

if [[ ! -s "$work/admin.api" ]]; then
  echo "admin anahtarı yok; ikinci kurulumda gizli dizine admin.api koyun" >&2
  exit 1
fi

oc -n conjur-test exec "$pod" -- mkdir -p /tmp/conjur-boot/values
oc -n conjur-test cp "$work/admin.api" "$pod:/tmp/conjur-boot/admin.api"
oc -n conjur-test cp "$root/policy.yml" "$pod:/tmp/conjur-boot/policy.yml"
oc -n conjur-test cp "$root/remote-load.sh" "$pod:/tmp/conjur-boot/remote-load.sh"
oc -n conjur-test cp "$work/values/postgres-sales" "$pod:/tmp/conjur-boot/values/postgres-sales"
oc -n conjur-test cp "$work/values/oracle-sales" "$pod:/tmp/conjur-boot/values/oracle-sales"
oc -n conjur-test cp "$work/values/deepseek" "$pod:/tmp/conjur-boot/values/deepseek"
set +e
oc -n conjur-test exec "$pod" -- bash /tmp/conjur-boot/remote-load.sh
status=$?
set -e
if [[ "$status" -eq 0 ]]; then
  oc -n conjur-test cp "$pod:/tmp/conjur-boot/host.api" "$work/host.api"
  oc -n agent-runtime create secret generic conjur-host --from-file=api_key="$work/host.api" --dry-run=client -o yaml | oc apply -f -
  echo "conjur-host Secret yazıldı (agent-runtime)"
elif [[ "$status" -eq 2 ]]; then
  echo "politika duruyor; conjur-host Secret değiştirilmedi"
else
  oc -n conjur-test exec "$pod" -- rm -rf /tmp/conjur-boot
  exit 1
fi
oc -n conjur-test exec "$pod" -- rm -rf /tmp/conjur-boot
echo "Conjur hazır. Deneme bitince: oc -n conjur-test scale deploy/conjur --replicas=0"
