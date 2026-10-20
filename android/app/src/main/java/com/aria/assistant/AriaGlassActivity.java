package com.aria.assistant;

import android.app.Activity;
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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Local glass UI for ARIA. Authentication and chat requests are performed natively
 * so the bundled file:// page does not depend on browser CORS behavior.
 */
public class AriaGlassActivity extends Activity {
    private static final String BACKEND = "https://aria-ai-s5go.onrender.com";
    private static final String AUTH_PREFS = "aria_glass_auth";
    private static final String TOKEN_KEY = "access_token";
    private static final String DEVICE_KEY = "device_id";

    private WebView webView;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(6, 7, 11));
        getWindow().setNavigationBarColor(Color.rgb(6, 7, 11));
        if (Build.VERSION.SDK_INT >= 29) {
            getWindow().setNavigationBarContrastEnforced(false);
            getWindow().setStatusBarContrastEnforced(false);
        }
        if (Build.VERSION.SDK_INT >= 28) {
            WindowManager.LayoutParams attrs = getWindow().getAttributes();
            attrs.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(attrs);
        }

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(6, 7, 11));
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                // Keep the JavaScript bridge confined to the bundled local app page.
                return !(url.startsWith("file:///android_asset/") || url.equals("about:blank"));
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !(url.startsWith("file:///android_asset/") || url.equals("about:blank"));
            }
        });
        webView.setWebChromeClient(new WebChromeClient());

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true); // Only the bundled, trusted asset is loaded here.
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        webView.addJavascriptInterface(new AriaBridge(), "AriaNative");

        setContentView(webView);
        webView.loadUrl("file:///android_asset/index.html");
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
        public void signOut() {
            getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().remove(TOKEN_KEY).apply();
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
        super.onDestroy();
    }
}
