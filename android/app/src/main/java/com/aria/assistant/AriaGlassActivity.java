package com.aria.assistant;

import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.Manifest;
import android.content.Intent;
import android.net.Uri;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Local glass UI for ARIA. Authentication and chat requests are performed natively
 * so the bundled file:// page does not depend on browser CORS behavior.
 */
public class AriaGlassActivity extends Activity {
    private static final String BACKEND = "https://aria-ai-s5go.onrender.com";
    private static final String AUTH_PREFS = "aria_auth";
    private static final String TOKEN_KEY = "access_token";
    private static final String DEVICE_KEY = "device_id";

    private static final int REQUEST_RECORD_AUDIO = 7301;
    private WebView webView;
    private SpeechRecognizer speechRecognizer;
    private TextToSpeech textToSpeech;
    private boolean ttsReady = false;
    private boolean voiceListening = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            getWindow().setStatusBarColor(Color.rgb(6, 7, 11));
            getWindow().setNavigationBarColor(Color.rgb(6, 7, 11));
            if (Build.VERSION.SDK_INT >= 29) {
                getWindow().setNavigationBarContrastEnforced(false);
                getWindow().setStatusBarContrastEnforced(false);
            }

            webView = new WebView(this);
            webView.setBackgroundColor(Color.rgb(6, 7, 11));
            webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
            webView.setWebViewClient(new WebViewClient() {
                @Override
                public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    Uri uri = request.getUrl();
                    String url = uri.toString();
                    if (url.startsWith("file:///android_asset/") || "about:blank".equals(url)) {
                        return false;
                    }
                    if ("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        } catch (Exception ex) {
                            android.util.Log.w("ARIA_STARTUP", "No browser can open external URL", ex);
                        }
                    }
                    return true;
                }

                @Override
                public boolean shouldOverrideUrlLoading(WebView view, String url) {
                    Uri uri = Uri.parse(url);
                    if (url.startsWith("file:///android_asset/") || "about:blank".equals(url)) {
                        return false;
                    }
                    if ("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        } catch (Exception ex) {
                            android.util.Log.w("ARIA_STARTUP", "No browser can open external URL", ex);
                        }
                    }
                    return true;
                }
            });
            webView.setWebChromeClient(new WebChromeClient());

            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            settings.setAllowFileAccess(true);
            settings.setAllowContentAccess(false);
            settings.setSupportZoom(false);
            settings.setBuiltInZoomControls(false);
            settings.setDisplayZoomControls(false);
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
            webView.addJavascriptInterface(new AriaBridge(), "AriaNative");
            setContentView(webView);

            // Voice and notifications are optional capabilities: neither should prevent
            // the main chat screen from appearing on devices without those services.
            try {
                initializeVoice();
            } catch (Exception ex) {
                android.util.Log.e("ARIA_STARTUP", "Voice initialization failed", ex);
            }
            try {
                requestNotificationPermissionIfNeeded();
            } catch (Exception ex) {
                android.util.Log.e("ARIA_STARTUP", "Notification permission setup failed", ex);
            }
            try {
                if (!getToken().trim().isEmpty()) {
                    AriaNotificationJobService.schedule(this);
                }
            } catch (Exception ex) {
                android.util.Log.e("ARIA_STARTUP", "Notification scheduling failed", ex);
            }

            webView.loadUrl("file:///android_asset/index.html");
        } catch (Exception ex) {
            android.util.Log.e("ARIA_STARTUP", "Activity initialization failed", ex);
            android.widget.TextView error = new android.widget.TextView(this);
            error.setText("ARIA could not start. " + ex.getClass().getSimpleName()
                    + (ex.getMessage() == null ? "" : ": " + ex.getMessage())
                    + "\n\nPlease check the Android runtime log.");
            error.setTextColor(Color.WHITE);
            error.setTextSize(16);
            error.setPadding(40, 40, 40, 40);
            error.setGravity(android.view.Gravity.CENTER);
            error.setBackgroundColor(Color.rgb(6, 7, 11));
            setContentView(error);
        }
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7302);
        }
    }

    private void initializeVoice() {
        // Speech recognition and TTS are optional. Handle each independently so
        // a missing speech service cannot stop ARIA's chat UI from opening.
        try {
            if (SpeechRecognizer.isRecognitionAvailable(this)) {
                speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
                speechRecognizer.setRecognitionListener(new RecognitionListener() {
                    @Override public void onReadyForSpeech(Bundle params) { voiceStatus("Listening…"); }
                    @Override public void onBeginningOfSpeech() { voiceStatus("Hearing you…"); }
                    @Override public void onRmsChanged(float rmsdB) { }
                    @Override public void onBufferReceived(byte[] buffer) { }
                    @Override public void onEndOfSpeech() { voiceListening = false; }
                    @Override public void onError(int error) {
                        voiceListening = false;
                        voiceStatus("Voice recognition stopped. Tap the microphone and try again.");
                        deliver("onAriaVoiceResult", voiceError("Speech recognition error (" + error + ")."));
                    }
                    @Override public void onResults(Bundle results) {
                        voiceListening = false;
                        ArrayList<String> matches = results == null ? null
                                : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                        String transcript = matches == null || matches.isEmpty() ? "" : matches.get(0).trim();
                        JSONObject payload = new JSONObject();
                        try {
                            payload.put("success", !transcript.isEmpty());
                            payload.put("text", transcript);
                            payload.put("message", transcript.isEmpty()
                                    ? "I didn't catch that. Please try again." : "Speech recognized.");
                        } catch (Exception ignored) { }
                        deliver("onAriaVoiceResult", payload);
                    }
                    @Override public void onPartialResults(Bundle partialResults) { }
                    @Override public void onEvent(int eventType, Bundle params) { }
                });
            }
        } catch (Exception ex) {
            speechRecognizer = null;
            android.util.Log.e("ARIA_VOICE", "Speech recognition unavailable", ex);
        }

        try {
            textToSpeech = new TextToSpeech(this, status -> {
                if (status != TextToSpeech.SUCCESS || textToSpeech == null) {
                    ttsReady = false;
                    android.util.Log.w("ARIA_VOICE", "Text-to-speech initialization failed");
                    return;
                }
                try {
                    int languageStatus = textToSpeech.setLanguage(Locale.getDefault());
                    ttsReady = languageStatus != TextToSpeech.LANG_MISSING_DATA
                            && languageStatus != TextToSpeech.LANG_NOT_SUPPORTED;
                    textToSpeech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                        @Override public void onStart(String utteranceId) { }
                        @Override public void onDone(String utteranceId) {
                            mainHandler.post(() -> deliver("onAriaSpeechFinished", new JSONObject()));
                        }
                        @Override public void onError(String utteranceId) {
                            mainHandler.post(() -> deliver("onAriaSpeechFinished", new JSONObject()));
                        }
                    });
                } catch (Exception ex) {
                    ttsReady = false;
                    android.util.Log.e("ARIA_VOICE", "Text-to-speech setup failed", ex);
                }
            });
        } catch (Exception ex) {
            textToSpeech = null;
            ttsReady = false;
            android.util.Log.e("ARIA_VOICE", "Text-to-speech unavailable", ex);
        }
    }

    private void voiceStatus(String message) {
        JSONObject payload = new JSONObject();
        try { payload.put("success", true); payload.put("status", message); }
        catch (Exception ignored) { }
        deliver("onAriaVoiceStatus", payload);
    }

    private void startVoiceRecognition() {
        runOnUiThread(() -> {
            if (speechRecognizer == null) {
                deliver("onAriaVoiceResult", voiceError("Speech recognition is not available on this device."));
                return;
            }
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO);
                voiceStatus("Microphone permission is required. Allow it, then tap the microphone again.");
                return;
            }
            try {
                if (voiceListening) speechRecognizer.cancel();
                Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault());
                intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
                intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
                voiceListening = true;
                speechRecognizer.startListening(intent);
            } catch (Exception ex) {
                voiceListening = false;
                deliver("onAriaVoiceResult", voiceError("Could not start speech recognition: " + safeMessage(ex)));
            }
        });
    }

    private JSONObject voiceError(String message) {
        JSONObject payload = new JSONObject();
        try { payload.put("success", false); payload.put("message", message); }
        catch (Exception ignored) { }
        return payload;
    }

    private void speakReply(String text) {
        if (text == null || text.trim().isEmpty()) return;
        runOnUiThread(() -> {
            if (textToSpeech == null || !ttsReady) {
                voiceStatus("Speech output is not ready on this device.");
                return;
            }
            String safeText = text.length() > 3500 ? text.substring(0, 3500) : text;
            textToSpeech.speak(safeText, TextToSpeech.QUEUE_FLUSH, null, "aria-reply-" + System.currentTimeMillis());
        });
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            voiceStatus("Microphone enabled. Tap the microphone to speak.");
        } else if (requestCode == REQUEST_RECORD_AUDIO) {
            voiceStatus("Microphone permission was denied.");
        }
    }

    private String getAriaDeviceId() {
        android.content.SharedPreferences prefs = getSharedPreferences(AUTH_PREFS, MODE_PRIVATE);
        String id = prefs.getString(DEVICE_KEY, "");
        if (id == null || id.trim().isEmpty()) {
            id = UUID.randomUUID().toString();
            prefs.edit().putString(DEVICE_KEY, id).apply();
        }
        return id;
    }

    private String getToken() {
        return getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).getString(TOKEN_KEY, "");
    }

    private JSONObject getJson(String path, String token) throws Exception {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(BACKEND + path).openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(20000);
            conn.setRequestProperty("Accept", "application/json");
            if (token != null && !token.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + token);
            int status = conn.getResponseCode();
            InputStream stream = status >= 200 && status < 400 ? conn.getInputStream() : conn.getErrorStream();
            StringBuilder body = new StringBuilder();
            if (stream != null) {
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) body.append(line);
                }
            }
            JSONObject result;
            try { result = body.length() == 0 ? new JSONObject() : new JSONObject(body.toString()); }
            catch (Exception ignored) { result = new JSONObject().put("detail", body.toString()); }
            result.put("_http_status", status);
            return result;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private JSONObject postJson(String path, JSONObject payload, String token) throws Exception {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(BACKEND + path).openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(180000);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            if (token != null && !token.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setDoOutput(true);
            byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = conn.getOutputStream()) { out.write(bytes); }
            int status = conn.getResponseCode();
            InputStream stream = status >= 200 && status < 400 ? conn.getInputStream() : conn.getErrorStream();
            StringBuilder body = new StringBuilder();
            if (stream != null) {
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) body.append(line);
                }
            }
            JSONObject result;
            try { result = body.length() == 0 ? new JSONObject() : new JSONObject(body.toString()); }
            catch (Exception ignored) { result = new JSONObject().put("detail", body.toString()); }
            result.put("_http_status", status);
            return result;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private void deliver(String callback, JSONObject data) {
        runOnUiThread(() -> {
            if (webView == null) return;
            webView.evaluateJavascript("window." + callback + " && window." + callback + "(" + data.toString() + ");", null);
        });
    }

    public final class AriaBridge {
        @JavascriptInterface
        public boolean isSignedIn() {
            return !getToken().trim().isEmpty();
        }

        @JavascriptInterface
        public void signIn(String secret) {
            final String password = secret == null ? "" : secret;
            executor.execute(() -> {
                JSONObject result = new JSONObject();
                try {
                    if (password.trim().isEmpty()) throw new IllegalArgumentException("Enter your private app password.");
                    JSONObject payload = new JSONObject();
                    payload.put("telegram_id", "7204704497");
                    payload.put("secret", password);
                    payload.put("device_id", getAriaDeviceId());
                    JSONObject response = postJson("/app/login", payload, "");
                    int status = response.optInt("_http_status", 0);
                    String token = response.optString("access_token", "");
                    if (status >= 200 && status < 300 && !token.isEmpty()) {
                        getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().putString(TOKEN_KEY, token).apply();
                        AriaNotificationJobService.schedule(AriaGlassActivity.this);
                        result.put("success", true);
                    } else {
                        result.put("success", false);
                        result.put("message", response.optString("detail", "Sign-in failed (HTTP " + status + ")."));
                    }
                } catch (Exception ex) {
                    try {
                        result.put("success", false);
                        result.put("message", ex instanceof java.net.SocketTimeoutException
                                ? "Sign-in timed out. The backend may be waking up; try again."
                                : "Cannot sign in to ARIA: " + safeMessage(ex));
                    } catch (Exception ignored) { }
                }
                deliver("onAriaLoginResult", result);
            });
        }

        @JavascriptInterface
        public void chat(String requestId, String message, String sessionId) {
            final String id = requestId == null ? "" : requestId;
            final String text = message == null ? "" : message.trim();
            final String session = sessionId == null || sessionId.trim().isEmpty() ? "android-glass" : sessionId;
            executor.execute(() -> {
                JSONObject result = new JSONObject();
                try {
                    String token = getToken();
                    if (token.isEmpty()) {
                        result.put("requestId", id).put("success", false).put("authRequired", true)
                                .put("message", "Please sign in to private ARIA.").put("reply", "Sign-in required.");
                    } else {
                        JSONObject payload = new JSONObject();
                        payload.put("message", text);
                        payload.put("session_id", session);
                        JSONObject response = postJson("/chat", payload, token);
                        int status = response.optInt("_http_status", 0);
                        if (status == 401) {
                            getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().remove(TOKEN_KEY).apply();
                            result.put("requestId", id).put("success", false).put("authRequired", true)
                                    .put("message", "Your ARIA session expired. Please sign in again.")
                                    .put("reply", "Your ARIA session expired. Please sign in again.");
                        } else if (status >= 200 && status < 300) {
                            String reply = response.optString("reply", response.optString("answer", "")).trim();
                            boolean success = response.optBoolean("success", true);
                            if (reply.isEmpty()) reply = "ARIA returned an empty response. Check the backend logs and try again.";
                            result.put("requestId", id).put("success", success).put("reply", reply);
                            if (!success) result.put("message", reply);
                        } else {
                            String detail = response.optString("detail", "");
                            if (detail.length() > 600) detail = detail.substring(0, 600);
                            result.put("requestId", id).put("success", false)
                                    .put("message", "ARIA backend returned HTTP " + status + (detail.isEmpty() ? ". Try again shortly." : ": " + detail))
                                    .put("reply", "Request failed. " + (detail.isEmpty() ? "Please try again shortly." : detail));
                        }
                    }
                } catch (Exception ex) {
                    try {
                        result.put("requestId", id).put("success", false)
                                .put("message", "Could not reach ARIA backend: " + safeMessage(ex))
                                .put("reply", ex instanceof java.net.SocketTimeoutException
                                        ? "ARIA is taking longer than expected. The request timed out; try again in a moment."
                                        : "I couldn't reach the ARIA backend. Check your internet connection and try again.");
                    } catch (Exception ignored) { }
                }
                deliver("onAriaChatResult", result);
            });
        }

        @JavascriptInterface
        public void notifications(String requestId) {
            final String id = requestId == null ? "" : requestId;
            executor.execute(() -> {
                JSONObject result = new JSONObject();
                try {
                    String token = getToken();
                    if (token.isEmpty()) {
                        result.put("requestId", id).put("success", false).put("authRequired", true).put("items", new org.json.JSONArray());
                    } else {
                        JSONObject response = getJson("/app/notifications?limit=30", token);
                        int status = response.optInt("_http_status", 0);
                        if (status == 401) {
                            getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().remove(TOKEN_KEY).apply();
                            result.put("requestId", id).put("success", false).put("authRequired", true).put("items", new org.json.JSONArray());
                        } else if (status >= 200 && status < 300) {
                            result.put("requestId", id).put("success", true).put("items", response.optJSONArray("items") == null ? new org.json.JSONArray() : response.optJSONArray("items"));
                        } else {
                            result.put("requestId", id).put("success", false).put("items", new org.json.JSONArray()).put("message", response.optString("detail", "Notifications are temporarily unavailable."));
                        }
                    }
                } catch (Exception ex) {
                    try { result.put("requestId", id).put("success", false).put("items", new org.json.JSONArray()).put("message", "Could not load notifications: " + safeMessage(ex)); }
                    catch (Exception ignored) { }
                }
                deliver("onAriaNotificationsResult", result);
            });
        }

        @JavascriptInterface
        public void startVoice() { startVoiceRecognition(); }

        @JavascriptInterface
        public void stopVoice() {
            runOnUiThread(() -> {
                voiceListening = false;
                if (speechRecognizer != null) speechRecognizer.cancel();
                voiceStatus("Voice input stopped.");
            });
        }

        @JavascriptInterface
        public void speak(String text) { speakReply(text); }

        @JavascriptInterface
        public void stopSpeaking() {
            runOnUiThread(() -> { if (textToSpeech != null) textToSpeech.stop(); });
        }

        @JavascriptInterface
        public void signOut() {
            getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().remove(TOKEN_KEY).apply();
            AriaNotificationJobService.cancel(AriaGlassActivity.this);
        }
    }

    private static String safeMessage(Exception ex) {
        String message = ex.getMessage();
        if (message == null || message.trim().isEmpty()) return ex.getClass().getSimpleName();
        return message.length() > 180 ? message.substring(0, 180) : message;
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.removeJavascriptInterface("AriaNative");
            webView.stopLoading();
            webView.loadUrl("about:blank");
            webView.destroy();
            webView = null;
        }
        executor.shutdownNow();
        if (speechRecognizer != null) {
            speechRecognizer.cancel();
            speechRecognizer.destroy();
            speechRecognizer = null;
        }
        if (textToSpeech != null) {
            textToSpeech.stop();
            textToSpeech.shutdown();
            textToSpeech = null;
        }
        mainHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
