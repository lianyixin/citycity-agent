# Contributing to CityCity Agent

Thanks for helping improve CityCity Agent.

## Development workflow

1. Fork the repository and create a focused branch.
2. Copy `.env.example` to `.env.development`; never commit local credentials.
3. Keep map-provider changes behind a small adapter boundary.
4. Add or update tests for behavior changes.
5. Run:

```bash
PYTHONPATH=backend python -m pytest backend/tests -v
cd frontend && npm run build
```

6. Open a pull request that explains the problem, approach, and verification.

## Pull request guidelines

- Keep each pull request focused and reviewable.
- Preserve bounded concurrency; do not add unbounded provider calls.
- Do not silently replace grounded POIs with invented locations.
- Never add API keys, private keys, tokens, database credentials, user data, or production deployment config.
- Document new environment variables in `.env.example` and both READMEs.
- Clearly label provider-specific behavior.

## Good first contributions

- Google Maps or Mapbox provider adapters
- Prompt localization
- Route-quality evaluation fixtures
- Accessibility improvements
- Streaming generation progress
- Documentation and reproducible deployment examples

By contributing, you agree that your contribution is licensed under the MIT License.
