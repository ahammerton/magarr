# Security policy

## Reporting a vulnerability

Please report security problems privately, through GitHub's
[private vulnerability reporting](https://github.com/ahammerton/magarr/security/advisories/new),
not in a public issue. Include what you found, how to reproduce it, and the Magarr version.

You'll get a reply within a few days. Fixes go into a new release, and the advisory is published
once a fixed version is available.

## Supported versions

Security fixes are made for the latest release.

## How Magarr is meant to be run

Magarr is designed for a home network. With basic auth off (the default), anyone who can reach
its port can use it. See [docs/security.md](docs/security.md) for what Magarr protects against and
how to expose it safely.
