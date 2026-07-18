# Security Policy

## Secrets

Never commit real API keys, passwords, JWTs, cookies, Dify app keys, Dataset
IDs, or cloud credentials. Use `.env` locally and keep `.env.example` limited
to placeholders.

If a secret is accidentally published, revoke or rotate it immediately. A Git
history rewrite does not make an exposed credential safe again.

## Reporting

Please report security issues privately through GitHub's security advisory
feature instead of opening a public issue containing exploit details or
credentials.

## Scope

This repository is a teaching and local demonstration project. It has not been
audited for production Internet exposure. Review authentication, cookie/token
storage, TLS, backups, rate limits, and infrastructure hardening before any
public deployment.
