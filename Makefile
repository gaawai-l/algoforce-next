.PHONY: setup dev sync check build doctor stop contract

setup dev sync check build doctor stop:
	python3 scripts/foundation.py $@

contract:
	.venv-foundation/bin/python scripts/export_foundation_contract.py
	npx --yes openapi-typescript@7.13.0 integrations/wealthfolio/openapi.json -o integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/api-schema.d.ts
	python3 scripts/foundation.py sync

.PHONY: verify-a5
verify-a5:
	.venv-foundation/bin/python scripts/verify_a5.py

.PHONY: setup-broker
setup-broker:
	python3 scripts/foundation.py setup-broker
