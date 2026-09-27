#!/bin/sh
set -eu
: "${TEST_AUTH_USER:?Set TEST_AUTH_USER}"
: "${TEST_AUTH_HASH:?Set TEST_AUTH_HASH to a base64-encoded APR1 hash}"
umask 077
decoded_hash=$(printf '%s' "$TEST_AUTH_HASH" | base64 -d)
printf '%s:%s\n' "$TEST_AUTH_USER" "$decoded_hash" > /etc/nginx/test.htpasswd
chmod 644 /etc/nginx/test.htpasswd
