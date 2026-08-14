# Security Policy

## Reporting a vulnerability

Please do not open a public issue for credential exposure, authentication bypass, payment issues, injection, or other security vulnerabilities.

Contact the maintainer through [Ethan Lian's GitHub profile](https://github.com/lianyixin) with:

- affected version or commit
- reproduction steps
- expected impact
- suggested mitigation, if available

Please allow reasonable time to investigate before public disclosure.

## Secrets

CityCity loads secrets from environment variables. Never commit:

- `.env.development`, `.env.production`, or `.env.local`
- map or LLM API keys
- database URLs containing credentials
- authentication, payment, image-provider, or deployment tokens
- private keys

If a secret is committed, revoke or rotate it immediately. Deleting it from the latest commit does not remove it from Git history.

## Supported versions

Security fixes target the latest version on the default branch.
