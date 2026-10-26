#!/bin/bash
# Reload Oracle test objects after a pod restart. There is no PVC, so the
# database is empty again. Passwords are read from the mounted Secret inside
# the pod and are never printed.
#
# Optional: put load-sales.sql next to this script to reload rows as SALES_OWNER.
# After the test, scale the deployment to 0:
#   oc -n oracle-test scale deploy/oracle-free --replicas=0
set -euo pipefail
cd "$(dirname "$0")"
NS=oracle-test
POD=$(oc -n "$NS" get pod -l app=oracle-free -o jsonpath='{.items[0].metadata.name}')
oc -n "$NS" cp setup-ro.sql "$POD:/tmp/setup-ro.sql"
oc -n "$NS" exec "$POD" -- bash -c '
set -euo pipefail
export NLS_LANG=AMERICAN_AMERICA.AL32UTF8
sed "s/__RO__/$(cat /run/secrets/oracle/ro)/" /tmp/setup-ro.sql > /tmp/s.sql
{
  echo "CONNECT system/\"$(cat /run/secrets/oracle/sys)\"@localhost:1521/FREE"
  echo "@/tmp/s.sql"
} | sqlplus -s /nolog
status=$?
rm -f /tmp/s.sql
exit "$status"
'
if [[ -f load-sales.sql ]]; then
  oc -n "$NS" cp load-sales.sql "$POD:/tmp/load.sql"
  oc -n "$NS" exec "$POD" -- bash -c '
set -euo pipefail
export NLS_LANG=AMERICAN_AMERICA.AL32UTF8
{
  echo "CONNECT sales_owner/\"$(cat /run/secrets/oracle/owner)\"@localhost:1521/FREEPDB1"
  echo "@/tmp/load.sql"
} | sqlplus -s /nolog
'
fi
