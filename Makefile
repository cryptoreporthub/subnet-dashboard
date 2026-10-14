.PHONY: restless-openapi restless-openapi-check

restless-openapi:
	DISABLE_BACKGROUND_SCANS=1 python scripts/restless_openapi.py --write

restless-openapi-check:
	DISABLE_BACKGROUND_SCANS=1 python scripts/restless_openapi.py --check
