# Security Policy

ChatRPG is pre-alpha software. Please treat both local installs and hosted
test deployments as experimental.

## Supported Versions

Security fixes target the current `main` branch. There are no stable release
branches yet.

## Reporting A Vulnerability

Please do not open a public issue for a vulnerability or leaked credential.
Use GitHub Private Vulnerability Reporting when it is enabled for this
repository. If that is not available yet, contact the maintainer privately and
include only the minimum details needed to reproduce the issue.

Good reports include:

- affected commit or version;
- reproduction steps;
- expected and actual impact;
- whether credentials, invite codes, uploaded files, or personal data may be
  involved.

Do not include real API keys, private invite codes, session tokens, production
database dumps, copyrighted books, or private campaign material in reports.

## Hosted Test Platform

The public test platform is invite-only and intended for evaluation, not for
sensitive personal data or private campaign archives. Account registration,
provider keys, rate limits, origin TLS, backups, and abuse controls are still
being hardened.

The hosted test platform is not a bug bounty program. Please avoid destructive
testing, denial-of-service traffic, credential stuffing, or attempts to access
other users' private rooms.

## Operator Notes

For public deployments:

- keep `JWT_SECRET`, provider keys, invite codes, admin bootstrap files, and
  database passwords server-local;
- rotate any credential that was pasted into a chat, issue, log, or commit;
- use invite-only registration until quotas, email verification, and abuse
  controls exist;
- prefer end-to-end TLS to the origin before broad public account testing;
- never commit uploaded files, generated user content, local databases, or
  private parser artifacts.
