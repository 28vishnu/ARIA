# ARIA Android APK (Stage 10)

This is a minimal native Android chat client for the ARIA backend. It sends JSON to `POST /chat` using the existing API shape (`message`, `session_id`) and reads the `reply` / `success` response.

## Add to the ARIA repository

Copy the `android/` folder and `.github/workflows/android-apk.yml` into the repository root. Keep the backend Python project in place.

## Build APK on GitHub

1. Commit these files to `main`.
2. Open the repository's **Actions** tab.
3. Select **Build ARIA Android APK** and click **Run workflow** (or push a change under `android/`).
4. Open the completed workflow run and download the `aria-android-debug-apk` artifact.
5. Extract the artifact ZIP and install `app-debug.apk` on your Android device. Android may ask you to allow installation from the browser/file manager.

## Notes and limitations

- Default backend is `https://aria-ai-s5go.onrender.com`; the URL can be edited in the app. It must be HTTPS.
- The Render free service may sleep, so the first request can take longer or time out. This is not an offline AI model.
- This workflow creates a **debug APK**, not a signed Play Store release.
- No API secrets are embedded in the APK. The app talks to the existing `/chat` endpoint.
