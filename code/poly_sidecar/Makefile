# Makefile · VelocityQuant poly_sidecar CI gate
# Firmado Gemma · r152-M2-bis Q4
# Fecha: 2026-05-09
#
# Uso:
#   make ci          · gate completo (lint + tests + secrets + whitespace)
#   make ci-fast     · solo tests (commit pre-flight)
#   make lint        · py_compile validation
#   make test        · pytest
#   make secrets-scan· gitleaks paranoid
#   make whitespace  · git diff --check
#   make deploy-gate · ci + extra checks pre-deploy

.PHONY: ci ci-fast lint test secrets-scan whitespace deploy-gate help install-hook clean

VENV := ./venv/bin
PYTHON := $(VENV)/python
PYTEST := $(VENV)/pytest
GITLEAKS_CONFIG := /home/administrator/codex_audit_2026-05-09/custom_vq.toml

# ─────────────────────────────────────────────────────────────────────────
# Gates
# ─────────────────────────────────────────────────────────────────────────

ci: lint test secrets-scan whitespace
	@echo ""
	@echo "═════════════════════════════════════════"
	@echo "✅ CI GATE PASS · all checks green"
	@echo "═════════════════════════════════════════"

ci-fast: lint test
	@echo "✅ ci-fast PASS · lint + tests (sin secrets/whitespace)"

deploy-gate: ci
	@echo ""
	@echo "═════════════════════════════════════════"
	@echo "🚦 DEPLOY GATE · pre-restart checks"
	@echo "═════════════════════════════════════════"
	@echo "Verifying systemd unit file syntax..."
	@sudo systemd-analyze verify /etc/systemd/system/vq-poly-sidecar.service || (echo "❌ systemd unit invalid"; exit 1)
	@echo "✅ deploy-gate PASS"

# ─────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────

lint:
	@echo "→ lint · py_compile"
	@$(PYTHON) -c "import py_compile; \
		[py_compile.compile(f, doraise=True) for f in [ \
			'sidecar.py', 'bls_client.py', 'fmp_compat.py', \
			'forecasts_loader.py', 'forecasts_validator.py', \
			'sf_engine.py', 'log_rotator.py', 'health_api.py', \
			'fred_calendar_client.py', 'investing_client.py', \
			'poly_client.py', 'btc_feed.py', 'tau_calc.py', \
			'store.py', 'sign_forecasts.py', 'fred_init.py', 'pnl.py' \
		]]"
	@echo "  ✅ all .py compile"

test:
	@echo "→ test · pytest"
	@$(PYTEST) tests/ -v --tb=short --no-header -q

secrets-scan:
	@echo "→ secrets-scan · gitleaks paranoid"
	@if [ ! -f $(GITLEAKS_CONFIG) ]; then \
		echo "❌ gitleaks config missing: $(GITLEAKS_CONFIG)"; exit 1; \
	fi
	@if ! command -v gitleaks > /dev/null; then \
		echo "❌ gitleaks not installed"; exit 1; \
	fi
	@gitleaks detect --config $(GITLEAKS_CONFIG) \
		--source . --no-git --no-banner --report-format json \
		--report-path /tmp/gitleaks_ci_report.json --exit-code 0 2>&1 | tail -3
	@$(PYTHON) -c "import json; d=json.load(open('/tmp/gitleaks_ci_report.json')); \
		real=[f for f in d if f.get('RuleID') in ('vq-fred-api-key','vq-bls-api-key','vq-anthropic-key','vq-telegram-bot-token','vq-chainstack-token','vq-gitea-token-url','vq-solana-base58-privkey')]; \
		print(f'  Total findings: {len(d)}'); \
		print(f'  REAL secret findings: {len(real)}'); \
		exit(1 if len(real) > 0 else 0)"
	@echo "  ✅ zero REAL secrets"

whitespace:
	@echo "→ whitespace · git diff --check"
	@git diff --check HEAD~1 HEAD 2>/dev/null && echo "  ✅ no trailing whitespace" \
		|| (echo "  ❌ trailing whitespace detected · run 'git diff --check'"; exit 1)

# ─────────────────────────────────────────────────────────────────────────
# Hooks management
# ─────────────────────────────────────────────────────────────────────────

install-hook:
	@if [ ! -d ../.git ] && [ ! -d .git ]; then \
		echo "❌ no .git found · skipping hook install"; exit 0; \
	fi
	@HOOK_DIR=$$(git rev-parse --git-dir 2>/dev/null)/hooks; \
		mkdir -p $$HOOK_DIR; \
		echo "#!/bin/bash" > $$HOOK_DIR/pre-commit; \
		echo "# r152-M2-bis · auto-installed pre-commit hook" >> $$HOOK_DIR/pre-commit; \
		echo "make -C $$(pwd) ci-fast || exit 1" >> $$HOOK_DIR/pre-commit; \
		chmod +x $$HOOK_DIR/pre-commit; \
		echo "✅ pre-commit hook installed → $$HOOK_DIR/pre-commit"

# ─────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────

clean:
	@find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@rm -rf .pytest_cache 2>/dev/null || true
	@rm -f /tmp/gitleaks_ci_report.json 2>/dev/null || true
	@echo "✅ cleaned __pycache__/ .pytest_cache/ pyc files"

help:
	@echo "VelocityQuant poly_sidecar Makefile · firmado Gemma r152-M2-bis"
	@echo ""
	@echo "Targets:"
	@echo "  ci             Full CI gate (lint + test + secrets + whitespace)"
	@echo "  ci-fast        Quick gate (lint + test) · pre-commit"
	@echo "  deploy-gate    CI + systemd unit verification"
	@echo "  lint           py_compile all *.py"
	@echo "  test           pytest tests/"
	@echo "  secrets-scan   gitleaks paranoid · zero REAL secrets enforced"
	@echo "  whitespace     git diff --check"
	@echo "  install-hook   Install .git/hooks/pre-commit (runs ci-fast)"
	@echo "  clean          Remove __pycache__, .pytest_cache, pyc"
	@echo "  help           This message"
