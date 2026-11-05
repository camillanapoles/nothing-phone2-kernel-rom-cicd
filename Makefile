# Makefile for Nothing Phone 2 Kernel/ROM CI/CD

.PHONY: all stack prove clean help agent agent-phase agent-compat agent-project agent-fingerprint agent-prompt workflow-audit test-agent

PYTHON ?= python3
AO_CMD ?= ao

all: ## Run all CI checks
	@echo "Running stack invariants..."
	$(PYTHON) scripts/stack_gate.py --config objects/install-stack.json
	@echo ""
	@echo "Running kernel build plan validation..."
	$(PYTHON) scripts/kernel_build_gate.py --config objects/kernel-build-plan.json
	@echo ""
	@echo "Running agent process gate..."
	$(PYTHON) scripts/ao_gate.py
	@echo ""
	@echo "✅ All CI checks completed"

stack: ## Validate stack invariants (16 checks)
	@$(PYTHON) scripts/stack_gate.py --config objects/install-stack.json

kernel-build: ## Validate kernel build plan
	@$(PYTHON) scripts/kernel_build_gate.py --config objects/kernel-build-plan.json

agent: ## Validate the agent PROCESS (roles, skills, workflows, prompts) — never the model
	@$(PYTHON) scripts/ao_gate.py

agent-json: ## Same as agent, machine-readable
	@$(PYTHON) scripts/ao_gate.py --json

agent-phase: ## Plan one phase, e.g. `make agent-phase F5`
	@test -n "$(PHASE)" || { echo "uso: make agent-phase PHASE=F5"; exit 2; }
	@$(PYTHON) scripts/ao_gate.py --phase $(PHASE)

agent-compat: ## Validate the same contract on the real agency-orchestrator engine
	@$(PYTHON) scripts/ao_gate.py --require-compat --ao-cmd $(AO_CMD)

agent-project: ## Emit the AO-dialect project into build/ao/
	@$(PYTHON) scripts/ao_gate.py --project ao --out build/ao

agent-prompt: ## Regenerate the published agent prompt from agent/prompts/
	@$(PYTHON) scripts/ao_gate.py --write-prompt

test-agent: ## Prove the agent gate actually rejects (mutation test)
	@$(PYTHON) scripts/test_agent_contract.py

agent-fingerprint: ## Print the process fingerprint (what ran — not which model)
	@$(PYTHON) scripts/ao_gate.py --json | $(PYTHON) -c "import json,sys; print(json.load(sys.stdin)['process_fingerprint'])"

workflow-audit: ## Prove the pipeline boundary: pinned actions, no deploy ops, mandate present
	@$(PYTHON) scripts/workflow_audit.py

prove: ## Full fail-closed verification
	@echo "Running full CI validation..."
	@$(MAKE) stack
	@$(MAKE) kernel-build
	@$(MAKE) agent
	@$(MAKE) workflow-audit
	@$(MAKE) test-agent
	@echo ""
	@echo "✅ Full CI validation passed"

clean: ## Remove generated artifacts
	@rm -rf build/ __pycache__/ scripts/__pycache__/

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .$$' $(MAKEFILE_LIST) | sort | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'
