#!/bin/sh
set -eu
: "${TEST_AUTH_USER:?Set TEST_AUTH_USER}"
: "${TEST_AUTH_HASH:?Set TEST_AUTH_HASH to a password hash}"
umask 077
printf '%s:%s\n' "$TEST_AUTH_USER" "$TEST_AUTH_HASH" > /etc/nginx/test.htpasswd
chmod 644 /etc/nginx/test.htpasswd
