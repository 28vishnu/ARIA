package com.aria.assistant;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
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

public class MainActivity extends Activity {
    private LinearLayout messages;
    private ScrollView scroll;
    private EditText messageInput, serverInput;
    private Button sendButton;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final String sessionId = "android-" + UUID.randomUUID();
    private static final String DEFAULT_SERVER = "https://aria-ai-s5go.onrender.com";

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().getDecorView().setSystemUiVisibility(0);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(15, 23, 42));
        root.setPadding(dp(16), dp(12), dp(16), dp(12));

        TextView title = new TextView(this);
        title.setText("ARIA  /  PERSONAL ASSISTANT");
        title.setTextColor(Color.WHITE); title.setTextSize(20); title.setTypeface(null, Typeface.BOLD);
        root.addView(title, new LinearLayout.LayoutParams(-1, dp(42)));

        serverInput = new EditText(this);
        serverInput.setSingleLine(true); serverInput.setText(DEFAULT_SERVER);
        serverInput.setTextColor(Color.WHITE); serverInput.setHintTextColor(Color.LTGRAY);
        serverInput.setHint("Backend URL (HTTPS)"); serverInput.setTextSize(13);
        serverInput.setPadding(dp(10), 0, dp(10), 0);
        serverInput.setBackgroundColor(Color.rgb(30, 41, 59));
        root.addView(serverInput, new LinearLayout.LayoutParams(-1, dp(44)));

        scroll = new ScrollView(this); scroll.setFillViewport(false);
        messages = new LinearLayout(this); messages.setOrientation(LinearLayout.VERTICAL);
        messages.setPadding(0, dp(12), 0, dp(12)); scroll.addView(messages);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(-1, 0, 1f);
        scrollParams.topMargin = dp(8); root.addView(scroll, scrollParams);
        addMessage("ARIA", "Connected app interface ready. Send a message to your ARIA backend.", false);

        LinearLayout composer = new LinearLayout(this); composer.setOrientation(LinearLayout.HORIZONTAL);
        messageInput = new EditText(this); messageInput.setSingleLine(false); messageInput.setMaxLines(3);
        messageInput.setTextColor(Color.WHITE); messageInput.setHintTextColor(Color.LTGRAY);
        messageInput.setHint("Message ARIA…"); messageInput.setPadding(dp(12), dp(8), dp(12), dp(8));
        messageInput.setBackgroundColor(Color.rgb(30, 41, 59));
        composer.addView(messageInput, new LinearLayout.LayoutParams(0, dp(52), 1f));
        sendButton = new Button(this); sendButton.setText("SEND");
        composer.addView(sendButton, new LinearLayout.LayoutParams(dp(88), dp(52)));
        LinearLayout.LayoutParams composerParams = new LinearLayout.LayoutParams(-1, -2);
        composerParams.topMargin = dp(8); root.addView(composer, composerParams);
        sendButton.setOnClickListener(v -> sendMessage());
        setContentView(root);
    }

    private void sendMessage() {
        String message = messageInput.getText().toString().trim();
        String base = serverInput.getText().toString().trim().replaceAll("/+$", "");
        if (message.isEmpty()) return;
        if (!base.startsWith("https://")) { addMessage("ARIA", "Use an HTTPS backend URL.", true); return; }
        messageInput.setText("");
        addMessage("YOU", message, true);
        sendButton.setEnabled(false);
        addMessage("ARIA", "Thinking…", false);
        executor.execute(() -> {
            String reply;
            try {
                HttpURLConnection conn = (HttpURLConnection) new URL(base + "/chat").openConnection();
                conn.setRequestMethod("POST"); conn.setConnectTimeout(15000); conn.setReadTimeout(60000);
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                conn.setDoOutput(true);
                JSONObject payload = new JSONObject(); payload.put("message", message); payload.put("session_id", sessionId);
                byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream os = conn.getOutputStream()) { os.write(bytes); }
                int status = conn.getResponseCode();
                InputStream stream = status >= 200 && status < 400 ? conn.getInputStream() : conn.getErrorStream();
                StringBuilder body = new StringBuilder();
                if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                    String line; while ((line = reader.readLine()) != null) body.append(line);
                }
                if (status >= 200 && status < 300) {
                    JSONObject response = new JSONObject(body.toString());
                    reply = response.optString("reply", "The server returned no reply.");
                    if (!response.optBoolean("success", true)) reply = "Request did not complete: " + reply;
                } else reply = "Server returned HTTP " + status + ". Check the backend logs and URL.";
                conn.disconnect();
            } catch (Exception e) {
                reply = "Could not reach ARIA. Check your internet connection and backend URL, then try again.";
            }
            final String finalReply = reply;
            runOnUiThread(() -> { addMessage("ARIA", finalReply, false); sendButton.setEnabled(true); });
        });
    }

    private void addMessage(String who, String text, boolean user) {
        TextView bubble = new TextView(this);
        bubble.setText(who + "\n" + text); bubble.setTextColor(Color.WHITE); bubble.setTextSize(15);
        bubble.setPadding(dp(12), dp(10), dp(12), dp(10));
        bubble.setBackgroundColor(user ? Color.rgb(37, 74, 145) : Color.rgb(30, 41, 59));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(8); params.gravity = user ? Gravity.END : Gravity.START;
        messages.addView(bubble, params); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }
    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density + 0.5f); }
    @Override protected void onDestroy() { super.onDestroy(); executor.shutdownNow(); }
}
