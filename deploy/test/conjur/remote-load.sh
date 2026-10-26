#!/bin/bash
# Runs inside the Conjur pod. Reads files under /tmp/conjur-boot.
# Prints HTTP status codes only. Never prints an API key or a variable value.
set -euo pipefail
umask 077
cd /tmp/conjur-boot
code=$(curl -sS -o token -w "%{http_code}" -H "Accept-Encoding: base64" --data-binary @admin.api \
  http://127.0.0.1/authn/agentrt/admin/authenticate)
echo "auth HTTP ${code}"
test "$code" = "200"
ruby -e 'token = File.read("token").strip; File.write("authz.cfg", %(header = "Authorization: Token token=\\"#{token}\\"\n"))'
code=$(curl -sS -o policy.out -w "%{http_code}" --config authz.cfg -X POST --data-binary @policy.yml \
  http://127.0.0.1/policies/agentrt/policy/root)
echo "policy HTTP ${code}"
rm -f token
if [[ "$code" != "200" && "$code" != "201" ]]; then
  rm -f policy.out authz.cfg admin.api
  exit 1
fi
ruby -e 'require "json"; data = JSON.parse(File.read("policy.out")); key = ""; (data["created_roles"] || {}).each_value { |role| key = role["api_key"].to_s if role.is_a?(Hash) && role["api_key"] }; File.write("host.api", key)'
rm -f policy.out
if [[ ! -s host.api ]]; then
  rm -f authz.cfg admin.api
  echo "host anahtarı dönmedi; politika zaten yüklü olabilir"
  exit 2
fi
set_var() {
  id="$1"
  file="$2"
  enc=$(ruby -e 'require "cgi"; puts CGI.escape(ARGV[0])' "$id")
  code=$(curl -sS -o /dev/null -w "%{http_code}" --config authz.cfg -X POST --data-binary @"$file" \
    "http://127.0.0.1/secrets/agentrt/variable/${enc}")
  echo "${id} HTTP ${code}"
  test "$code" = "201" -o "$code" = "200"
}
set_var "agent-runtime/postgres-sales/password" values/postgres-sales
set_var "agent-runtime/oracle-sales/password" values/oracle-sales
set_var "agent-runtime/deepseek/api-key" values/deepseek
rm -f authz.cfg admin.api
echo "yüklendi"
