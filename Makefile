# D143 (TODO P1): one entry point for the checks this repo already runs.
# Everything stays inside the canonical Docker image (compose `test` service).

.PHONY: test compile check smoke lock

test:            ## full canonical suite in the docker test image
	COMPOSE_PROFILES=test docker compose run --build --rm test

compile:         ## byte-compile all app modules (host python)
	python3 -m compileall -q app

check:           ## JS syntax gate
	@for f in app/static/js/*.js; do node --check "$$f"; done; echo "js ok"

smoke:           ## live server smoke: health + register + room (scripts/smoke.sh)
	bash scripts/smoke.sh

lock:            ## regenerate requirements.lock from the canonical image
	COMPOSE_PROFILES=test docker compose run --rm --no-deps test pip freeze \
	  | grep -E '^[A-Za-z0-9_.-]+==' | sort -f > /tmp/lock.new && \
	  { head -4 requirements.lock; cat /tmp/lock.new; } > requirements.lock && rm /tmp/lock.new
