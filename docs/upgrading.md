# Upgrading

```sh
docker compose pull && docker compose up -d       # published image
git pull && docker compose up -d --build          # from source
```

## What happens on start

- **Database migrations run automatically.** Before any migration Magarr copies the database to
  `/config/magarr.db.pre-<new>-from-<old>.bak`, and checks the result's integrity afterwards.
- **`config.yaml` stays as it is.** New settings get their defaults; you never need to edit the
  file to upgrade.

## Rolling back

Stop Magarr, put back the previous version's image, and restore the matching database: copy the
`.bak` file over `/config/magarr.db` (or restore a backup from System → Backup *before*
downgrading). A newer database can't be opened by an older Magarr: restoring a backup made by a
newer version is refused with a message saying so.

## Versions

Magarr uses semantic versioning: `1.x` releases keep the API and configuration compatible; a
`2.0` would say in the [changelog](../CHANGELOG.md) what changes.
