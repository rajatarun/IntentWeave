.PHONY: install test lint build deploy deploy-guided validate clean invoke

PYTHON   := python3
PIP      := $(PYTHON) -m pip
PYTEST   := $(PYTHON) -m pytest
STACK    := intentweave
REGION   := us-east-1

# ─── Development ──────────────────────────────────────────────────────────────

install:
	$(PIP) install -r requirements.txt -r requirements-dev.txt

test:
	$(PYTEST) tests/ -v --tb=short

test-cov:
	$(PYTEST) tests/ -v --cov=intentweave --cov-report=term-missing --cov-report=html

lint:
	$(PYTHON) -m flake8 intentweave/ lambda_handler.py --max-line-length=100

# ─── AWS Build & Deploy ────────────────────────────────────────────────────────

bootstrap-oidc:
	@echo "Deploying GitHub OIDC role (one-time setup)..."
	@read -p "GitHub org [rajatarun]: " ORG; ORG=$${ORG:-rajatarun}; \
	 read -p "GitHub repo [IntentWeave]: " REPO; REPO=$${REPO:-IntentWeave}; \
	 read -p "OIDC provider already exists? (true/false) [false]: " EXISTS; EXISTS=$${EXISTS:-false}; \
	 SHOULD_CREATE=$$([ "$$EXISTS" = "true" ] && echo "false" || echo "true"); \
	 aws cloudformation deploy \
	   --template-file infra/github-oidc-role.yaml \
	   --stack-name intentweave-github-oidc \
	   --capabilities CAPABILITY_NAMED_IAM \
	   --region $(REGION) \
	   --parameter-overrides \
	     GitHubOrg=$$ORG \
	     GitHubRepo=$$REPO \
	     CreateOIDCProvider=$$SHOULD_CREATE; \
	 echo ""; \
	 echo "==> Store this ARN as AWS_DEPLOY_ROLE_ARN in GitHub Secrets:"; \
	 aws cloudformation describe-stacks \
	   --stack-name intentweave-github-oidc \
	   --query "Stacks[0].Outputs[?OutputKey=='GitHubDeployRoleArn'].OutputValue" \
	   --output text \
	   --region $(REGION)

validate:
	sam validate --template template.yaml --region $(REGION)

build:
	sam build

deploy: build
	sam deploy

deploy-guided: build
	sam deploy --guided

# ─── Smoke test (post-deploy) ─────────────────────────────────────────────────

invoke:
	@ENDPOINT=$$(aws cloudformation describe-stacks \
		--stack-name $(STACK) \
		--query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
		--output text --region $(REGION)); \
	echo "POST $$ENDPOINT"; \
	curl -s -X POST "$$ENDPOINT" \
		-H "Content-Type: application/json" \
		-d '{"session_id":"smoke-test-1","user_message":"book a flight to Paris","persona":"PROFESSIONAL"}' \
		| python3 -m json.tool

# ─── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	rm -rf .aws-sam htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
