# Branding migration report

The primary visible identity is now **JARVIS — JUST A RATHER VERY INTELLIGENT SYSTEM**
in FastAPI metadata and the root response. The Android launcher label, embedded web
title and interface, native screen copy, settings project name, release artifact labels,
and README were updated.

ARIA references remain intentionally in compatibility-sensitive identifiers: MongoDB
database/collections, SQLite and vector paths, environment keys, Android application
ID/package, app preference keys, notification identifiers, API host/release URLs,
workflow and resource names. These are not user-facing product labels and changing
them could strand stored data or prevent existing Android installs from upgrading.
There are also remaining legacy phrases in backend logs, comments and native Android
screen copy; this archive-wide branding pass is therefore partial, not complete.

No file was deleted. No package ID, signing identity, route or persistent identifier
was migrated.
