# Deployment and rollback notes

## Deployment

1. Use the existing Docker/Render or other deployment configuration and persistent
   storage. Do not point a first rollout at an unbacked production volume.
2. Configure existing provider credentials and owner authentication secrets using the
   deployment secret manager. Never commit them to `.env` or logs.
3. Existing `AR_ENVIRONMENT`, `AR_TIMEOUT`, `AR_PERMISSION_MODE` and
   `RENDER_PERSISTENT_DIR` continue to work. `JARVIS_ENVIRONMENT`, `JARVIS_TIMEOUT`,
   `JARVIS_PERMISSION_MODE` and `JARVIS_VECTOR_PERSIST_PATH` take precedence where
   supported by centralized configuration.
4. Confirm `/health` is live and `/ready` is ready after startup; then verify sign-in,
   chat and configured integrations in staging.
5. Build Android with the existing application ID, keystore and `ARIA_*` signing
   variables. Do not rotate signing credentials as part of branding.

## Rollback

Restore the prior backend artifact and APK signed with the existing key. Keep the same
database, vector and persistent-disk paths. This change makes no schema migrations, so
application rollback does not require data rollback. Restore a database backup only
if a separately planned data operation has changed it.

Exact hosting-specific commands depend on the deployment provider and were not
verified against a live environment.
