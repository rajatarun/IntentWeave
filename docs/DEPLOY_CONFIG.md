# GitHub Actions deploy configuration

IntentWeave’s **Deploy prod (SAM)** job in [.github/workflows/ci.yml](../.github/workflows/ci.yml) assumes OIDC into AWS and deploys `template.yaml`. Configure the repository (or the `prod` GitHub Environment) before the next production deploy.

## Required secrets

| Name | Purpose | Example placeholder |
| --- | --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for GitHub OIDC (`configure-aws-credentials` `role-to-assume`) | `arn:aws:iam::123456789012:role/example-github-actions-sam-deployer` |

## Required variables

| Name | Purpose | Example placeholder |
| --- | --- | --- |
| `AWS_REGION` | Region for SAM deploy, stack describe, and smoke tests | `us-east-1` |
| `AWS_STACK_NAME` | CloudFormation stack name (also used for deploy concurrency group) | `intentweave-prod` |

## Local / SAM parameters

Local deploys use `sam deploy --guided` and are not tied to the GitHub values above. Stack outputs use standard pseudo-parameters (`AWS::Region`, stack name) from `template.yaml`; no account-specific defaults are committed in the template.

## Before you deploy

1. Create the IAM OIDC trust for GitHub Actions in **your** AWS account and note the deploy role ARN.
2. Add `AWS_DEPLOY_ROLE_ARN` as a **secret** (repository or `prod` environment).
3. Add `AWS_REGION` and `AWS_STACK_NAME` as **variables** (repository or `prod` environment).
4. Run the **IntentWeave CI** workflow on `main` (push or `workflow_dispatch`); deploy runs after tests and SAM build when the event is not a pull request.

If any required secret or variable is missing, the deploy job fails at credential or `sam deploy` time.
