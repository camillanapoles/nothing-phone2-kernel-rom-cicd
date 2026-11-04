# Makefile for Nothing Phone 2 Kernel/ROM CI/CD

.PHONY: all stack prove clean help

all: ## Run all CI checks
	@echo "Running stack invariants..."
	python3 scripts/stack_gate.py --config objects/install-stack.json
	@echo ""
	@echo "Running kernel build plan validation..."
	python3 scripts/kernel_build_gate.py --config objects/kernel-build-plan.json
	@echo ""
	@echo "✅ All CI checks completed"

stack: ## Validate stack invariants (16 checks)
	@python3 scripts/stack_gate.py --config objects/install-stack.json

prove: ## Full build verification
	@echo "Running full CI validation..."
	@$(MAKE) stack
	@$(MAKE) kernel-build
	@echo ""
	@echo "✅ Full CI validation passed"

kernel-build: ## Validate kernel build plan
	@python3 scripts/kernel_build_gate.py --config objects/kernel-build-plan.json

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .$$' $(MAKEFILE_LIST) | sort | awk -F'[: ]' 'BEGIN {ORS=" "} {print $$1, $$2}'