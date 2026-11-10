# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `main` branch (pre-1.0) | Yes |
| Tagged releases | Yes, latest tag only after v1.0 |

IntentWeave is pre-1.0; pin to a commit or tag in production and watch `main` for security fixes.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Report vulnerabilities privately by opening a **GitHub Security Advisory** (Repository → Security → Advisories → Report a vulnerability) on this repository. If that is unavailable, contact the repository owner through GitHub's private communication channels.

Include:

- Affected component (Lambda handler, DynamoDB store, provider adapter, etc.)
- Steps to reproduce
- Impact assessment (data exposure, denial of service, etc.)
- Suggested fix, if you have one

We aim to acknowledge reports within **5 business days** and coordinate disclosure timing with you.

## Scope

In scope:

- This repository's code paths (API handler, thread store, providers, SAM template defaults)
- Misconfiguration that leads to unintended public access when deployed as documented

Out of scope:

- Vulnerabilities in upstream AWS services or third-party LLM APIs
- Deployments that disable encryption, expose the API without authentication, or use overly broad IAM — see [docs/design/SECURITY_NOTES.md](docs/design/SECURITY_NOTES.md)
