# JARVIS migration plan

## Completed in this delivery

1. Kept the supplied project intact in a separate output copy.
2. Added centralized product constants and JARVIS-first configuration aliases for
   environment, vector path, timeout and permission mode.
3. Updated FastAPI title/root identity and Android launcher/web UI labels.
4. Preserved ARIA database, file, collection, Android ID, preference, route, URL and
   signing names to avoid silently breaking existing installations.
5. Added architecture, inventory, compatibility and implementation status documents.

## Recommended staged rollout

1. Back up MongoDB, persistent disk and Android release signing assets.
2. Deploy this build to a staging environment using the existing storage paths and
   credentials. Configure the JARVIS aliases first; legacy names remain fallbacks.
3. Verify `/health`, `/ready`, sign-in, chat, integrations and persistent knowledge
   against a staging copy of data.
4. Publish Android under the retained `com.aria.assistant` application ID and the
   existing signing key. A new ID or signing key would prevent an in-place update.
5. Promote only after operational checks pass. Keep the previous backend image and
   APK available for rollback.

No database schema migration is included. This release performs no data deletion.
