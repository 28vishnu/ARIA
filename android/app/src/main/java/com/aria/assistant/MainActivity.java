package com.aria.assistant;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.Spannable;
import android.text.SpannableString;
import android.text.style.StyleSpan;
import android.text.style.RelativeSizeSpan;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.ProgressBar;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int BG = Color.rgb(9, 12, 20), PANEL = Color.argb(178, 28, 35, 52), PANEL2 = Color.argb(220, 49, 61, 87);
    private static final int TEXT = Color.rgb(242, 245, 252), MUTED = Color.rgb(165, 176, 197), ACCENT = Color.rgb(127, 155, 255);
    private static final String DEFAULT_SERVER = "https://aria-ai-s5go.onrender.com";
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final String sessionId = "android-" + java.util.UUID.randomUUID();
    private volatile boolean appVisible = false;
    private static final int NOTIFICATION_PERMISSION_REQUEST = 7401;
    private static final String NOTIFICATION_CHANNEL_ID = "aria_replies";
    private LinearLayout root, transcript, sourcesPanel, tabRow, composer;
    private ScrollView transcriptScroll, sourcesScroll;
    private EditText input, serverInput;
    private Button sendButton, answerTab, sourcesTab;
    private TextView thinkingLabel;
    private ProgressBar thinkingSpinner;
    private boolean showingSources = false;
    private final ArrayList<SourceItem> lastSources = new ArrayList<>();

    private static class SourceItem {
        String title, url;
        SourceItem(String title, String url) { this.title = title; this.url = url; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(9, 12, 20));
        getWindow().setNavigationBarColor(Color.rgb(9, 12, 20));
        getWindow().getDecorView().setSystemUiVisibility(0);
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        createNotificationChannel();
        buildUi();
        addWelcome();
        requestNotificationPermissionIfNeeded();
        checkForUpdates();
    }

    @Override protected void onResume() { super.onResume(); appVisible = true; }
    @Override protected void onStop() { appVisible = false; super.onStop(); }

    private AlertDialog.Builder dialogBuilder() {
        // Dark native dialog theme keeps secondary screens consistent with ARIA.
        return new AlertDialog.Builder(new android.view.ContextThemeWrapper(this, android.R.style.Theme_Material_Dialog_Alert));
    }

    private void applyDialogColors(AlertDialog dialog) {
        if (dialog == null) return;
        dialog.setOnShowListener(ignored -> {
            int buttonColor = ACCENT;
            int[] ids = {android.R.id.button1, android.R.id.button2, android.R.id.button3};
            for (int id : ids) {
                Button b = dialog.findViewById(id);
                if (b != null) b.setTextColor(buttonColor);
            }
            TextView message = dialog.findViewById(android.R.id.message);
            if (message != null) message.setTextColor(TEXT);
        });
    }

    private AlertDialog showDialog(AlertDialog dialog) {
        applyDialogColors(dialog);
        dialog.show();
        return dialog;
    }

    private void createNotificationChannel() {
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(NOTIFICATION_CHANNEL_ID, "ARIA replies", NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Notifies you when an ARIA response is ready while the app is in the background.");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private void requestNotificationPermissionIfNeeded() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION_REQUEST);
        }
    }

    private void notifyResponseReady() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pending = PendingIntent.getActivity(this, 7402, intent,
            PendingIntent.FLAG_UPDATE_CURRENT | (android.os.Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
        Notification.Builder builder = android.os.Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, NOTIFICATION_CHANNEL_ID) : new Notification.Builder(this);
        builder.setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("ARIA response ready")
            .setContentText("Your answer is ready. Tap to return to ARIA.")
            .setContentIntent(pending).setAutoCancel(true);
        NotificationManager manager = (NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify((int)(System.currentTimeMillis() & 0x7fffffff), builder.build());
    }

    private void checkForUpdates() {
        executor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection)new URL("https://github.com/28vishnu/ARIA/releases/latest/download/version.json").openConnection();
                connection.setRequestMethod("GET"); connection.setConnectTimeout(7000); connection.setReadTimeout(7000); connection.setInstanceFollowRedirects(true);
                if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) return;
                StringBuilder body = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8))) {
                    String line; while ((line = reader.readLine()) != null) body.append(line);
                }
                JSONObject release = new JSONObject(body.toString());
                int latestCode = release.optInt("versionCode", 0);
                String latestName = release.optString("versionName", "New version");
                String apkUrl = release.optString("apkUrl", "https://github.com/28vishnu/ARIA/releases/latest");
                int installedCode = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                if (latestCode > installedCode) runOnUiThread(() -> dialogBuilder().setTitle("ARIA update available")
                    .setMessage("Version " + latestName + " is ready. Download the latest ARIA build?")
                    .setPositiveButton("Download update", (d, w) -> { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(apkUrl))); } catch (Exception e) { toast("Could not open the download link."); } })
                    .setNegativeButton("Later", null).show());
            } catch (Exception ignored) { } finally { if (connection != null) connection.disconnect(); }
        });
    }

    private void buildUi() {
        getWindow().setStatusBarColor(Color.rgb(12, 16, 28));
        getWindow().setNavigationBarColor(Color.rgb(12, 16, 28));
        getWindow().getDecorView().setSystemUiVisibility(0);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        final int baseLeft = dp(12), baseTop = dp(4), baseRight = dp(12), baseBottom = dp(6);
        root.setPadding(baseLeft, baseTop, baseRight, baseBottom);
        // Respect status bar, camera cut-outs/notches, gesture navigation and keyboard insets.
        // This prevents the hamburger/header from sitting underneath the notification/status area.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            int top = 0, left = 0, right = 0, bottom = 0;
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.statusBars()
                    | android.view.WindowInsets.Type.navigationBars() | android.view.WindowInsets.Type.displayCutout());
                top = bars.top; left = bars.left; right = bars.right; bottom = bars.bottom;
            } else {
                top = insets.getSystemWindowInsetTop();
                left = insets.getSystemWindowInsetLeft();
                right = insets.getSystemWindowInsetRight();
                bottom = insets.getSystemWindowInsetBottom();
            }
            view.setPadding(baseLeft + left, baseTop + top, baseRight + right, baseBottom + bottom);
            return insets;
        });

        // Compact ChatGPT-inspired header: navigation, brand, and new-chat action.
        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setPadding(0, 0, 0, dp(3));
        TextView menu = label("☰", 21, TEXT, false);
        menu.setContentDescription("Open navigation menu");
        menu.setGravity(Gravity.CENTER);
        header.addView(menu, new LinearLayout.LayoutParams(dp(42), dp(44)));
        menu.setOnClickListener(v -> showAppMenu());

        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.HORIZONTAL);
        brand.setGravity(Gravity.CENTER_VERTICAL);
        TextView mark = label("✦", 21, Color.WHITE, true);
        mark.setGravity(Gravity.CENTER);
        mark.setBackground(glassAccent());
        brand.addView(mark, new LinearLayout.LayoutParams(dp(34), dp(34)));
        TextView title = label("  ARIA", 19, TEXT, true);
        brand.addView(title);
        header.addView(brand, new LinearLayout.LayoutParams(0, -1, 1));
        TextView newChat = label("＋", 27, TEXT, false);
        newChat.setGravity(Gravity.CENTER);
        header.addView(newChat, new LinearLayout.LayoutParams(dp(42), dp(44)));
        newChat.setOnClickListener(v -> newConversation());
        root.addView(header, new LinearLayout.LayoutParams(-1, dp(44)));

        tabRow = new LinearLayout(this); tabRow.setOrientation(LinearLayout.HORIZONTAL); tabRow.setGravity(Gravity.CENTER_VERTICAL);
        tabRow.setPadding(0, 0, 0, dp(5));
        answerTab = new Button(this); sourcesTab = new Button(this);
        styleTab(answerTab, "Answer", true); styleTab(sourcesTab, "Sources", false);
        tabRow.addView(answerTab, new LinearLayout.LayoutParams(dp(86), dp(36)));
        tabRow.addView(sourcesTab, new LinearLayout.LayoutParams(dp(86), dp(36)));
        root.addView(tabRow, new LinearLayout.LayoutParams(-1, dp(42)));
        answerTab.setOnClickListener(v -> showTab(false)); sourcesTab.setOnClickListener(v -> showTab(true));

        // Keep configuration out of the conversation view; accessible through the menu.
        serverInput = new EditText(this);
        serverInput.setSingleLine(true);
        serverInput.setText(getSharedPreferences("aria_settings", MODE_PRIVATE)
            .getString("backend_url", DEFAULT_SERVER));

        transcriptScroll = new ScrollView(this);
        transcriptScroll.setFillViewport(true);
        transcriptScroll.setVerticalScrollBarEnabled(false);
        transcriptScroll.setOverScrollMode(View.OVER_SCROLL_NEVER);
        transcript = new LinearLayout(this);
        transcript.setOrientation(LinearLayout.VERTICAL);
        transcript.setPadding(dp(2), dp(18), dp(2), dp(20));
        transcriptScroll.addView(transcript, new ScrollView.LayoutParams(-1, -2));
        root.addView(transcriptScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        sourcesScroll = new ScrollView(this); sourcesScroll.setFillViewport(true); sourcesScroll.setVerticalScrollBarEnabled(false);
        sourcesPanel = new LinearLayout(this); sourcesPanel.setOrientation(LinearLayout.VERTICAL); sourcesPanel.setPadding(dp(2), dp(14), dp(2), dp(20));
        sourcesScroll.addView(sourcesPanel, new ScrollView.LayoutParams(-1, -2));
        renderSources();

        // Floating, rounded message composer that stays compact on small screens.
        composer = new LinearLayout(this);
        composer.setOrientation(LinearLayout.HORIZONTAL);
        composer.setGravity(Gravity.BOTTOM | Gravity.CENTER_VERTICAL);
        composer.setPadding(dp(8), dp(6), dp(6), dp(6));
        composer.setBackground(glassBackground());
        composer.setElevation(dp(2));
        TextView add = label("＋", 24, MUTED, false);
        add.setGravity(Gravity.CENTER);
        composer.addView(add, new LinearLayout.LayoutParams(dp(38), dp(42)));
        add.setOnClickListener(v -> showAttachmentMenu());
        input = new EditText(this);
        input.setTextColor(TEXT);
        input.setHintTextColor(Color.rgb(158, 160, 166));
        input.setTextSize(16);
        input.setHint("Message ARIA");
        input.setGravity(Gravity.CENTER_VERTICAL);
        input.setMinHeight(dp(42));
        input.setMaxLines(5);
        input.setPadding(dp(5), dp(6), dp(5), dp(6));
        input.setBackgroundColor(Color.TRANSPARENT);
        composer.addView(input, new LinearLayout.LayoutParams(0, -2, 1));
        sendButton = new Button(this);
        sendButton.setText("↑");
        sendButton.setTextSize(23);
        sendButton.setTextColor(Color.WHITE);
        sendButton.setAllCaps(false);
        sendButton.setPadding(0, 0, 0, dp(2));
        sendButton.setBackground(round(Color.rgb(240, 242, 245), 24));
        sendButton.setTextColor(Color.rgb(20, 22, 25));
        composer.addView(sendButton, new LinearLayout.LayoutParams(dp(42), dp(42)));
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(-1, -2);
        cp.topMargin = dp(8);
        root.addView(composer, cp);
        TextView disclaimer = label("ARIA may make mistakes. Verify important information.", 10, MUTED, false);
        disclaimer.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams disclaimerParams = new LinearLayout.LayoutParams(-1, dp(20));
        root.addView(disclaimer, disclaimerParams);

        // Profile and settings are in the navigation drawer, never pinned over the chat.

        sendButton.setOnClickListener(v -> sendMessage());
        input.setOnEditorActionListener((v, action, event) -> {
            if ((event == null && action == android.view.inputmethod.EditorInfo.IME_ACTION_SEND) || (event != null && event.getKeyCode() == android.view.KeyEvent.KEYCODE_ENTER && !event.isShiftPressed())) { sendMessage(); return true; }
            return false;
        });
        setContentView(root);
    }

    private void showAppMenu() {
        final String[] options = {"＋   New chat", "◷   Chat history", "✦   Explore ARIA features", "◉   Profile", "⚙   Settings", "ⓘ   About ARIA"};
        AlertDialog dialog = dialogBuilder().setTitle("ARIA  ·  Assistant")
            .setItems(options, (d, which) -> {
                if (which == 0) newConversation();
                else if (which == 1) showHistory();
                else if (which == 2) showFeatureDirectory();
                else if (which == 3) showProfile();
                else if (which == 4) showSettings();
                else dialogBuilder().setTitle("About ARIA")
                    .setMessage("ARIA is your personal assistant connected to your configured backend. Available tools depend on the backend and permissions enabled for this build.")
                    .setPositiveButton("Done", null).show();
            }).create();
        showDialog(dialog);
    }

    private void newConversation() {
        transcript.removeAllViews(); lastSources.clear(); renderSources();
        addWelcome();
    }

    private void addWelcome() {
        LinearLayout welcome = new LinearLayout(this); welcome.setOrientation(LinearLayout.VERTICAL); welcome.setGravity(Gravity.CENTER); welcome.setPadding(dp(10), dp(10), dp(10), dp(16));
        TextView icon = label("✦", 32, Color.WHITE, true); icon.setGravity(Gravity.CENTER); icon.setBackground(glassAccent());
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(dp(54), dp(54)); ip.bottomMargin = dp(14); welcome.addView(icon, ip);
        TextView heading = label("What can I help with?", 23, TEXT, true); heading.setGravity(Gravity.CENTER); welcome.addView(heading);
        TextView sub = label("Ask a question, explore an idea, or work through a problem.", 14, MUTED, false); sub.setGravity(Gravity.CENTER); sub.setPadding(dp(16), dp(9), dp(16), dp(18)); welcome.addView(sub);
        LinearLayout suggestions = new LinearLayout(this); suggestions.setOrientation(LinearLayout.VERTICAL);
        String[] prompts = {"Explain something clearly", "Help me write or improve code", "Explore an idea with me"};
        for (String prompt : prompts) { TextView item = label("✧   " + prompt, 13, TEXT, false); item.setPadding(dp(14), dp(12), dp(14), dp(12)); item.setBackground(glassBackground()); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.bottomMargin = dp(8); suggestions.addView(item,p); item.setOnClickListener(v -> { input.setText(prompt); input.setSelection(input.length()); input.requestFocus(); }); }
        welcome.addView(suggestions, new LinearLayout.LayoutParams(-1, -2)); transcript.addView(welcome, new LinearLayout.LayoutParams(-1, -1));
    }

    private void showProfile() {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(8), dp(20), dp(4));
        TextView name = label("ARIA Personal Assistant", 16, TEXT, true);
        content.addView(name);
        TextView info = label("Connected to your ARIA backend\n\nProfile and chat history are stored locally only where implemented. This build does not sync a personal profile to a cloud account.", 13, MUTED, false);
        info.setPadding(0, dp(10), 0, dp(4));
        content.addView(info);
        dialogBuilder().setTitle("Profile").setView(content)
            .setNeutralButton("Settings", (d, w) -> showSettings())
            .setPositiveButton("Done", null).show();
    }

    private void showSettings() {
        LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(20), dp(8), dp(20), dp(4));
        TextView backendLabel = label("Backend URL", 13, MUTED, true); content.addView(backendLabel);
        EditText backend = new EditText(this); backend.setSingleLine(true); backend.setText(serverInput.getText().toString()); backend.setTextColor(TEXT); backend.setHintTextColor(MUTED); backend.setTextSize(14); backend.setSelectAllOnFocus(true); content.addView(backend);
        TextView note = label("Render hosting is fine. A free service may take time to wake up after inactivity.", 12, MUTED, false); note.setPadding(0,dp(8),0,0); content.addView(note);
        dialogBuilder().setTitle("Settings").setView(content).setNegativeButton("Cancel", null).setPositiveButton("Save", (d,w) -> { String url=backend.getText().toString().trim().replaceAll("/+$", ""); if (url.startsWith("https://")) { serverInput.setText(url); getSharedPreferences("aria_settings", MODE_PRIVATE).edit().putString("backend_url", url).apply(); toast("Backend URL saved"); } else toast("Use a valid HTTPS URL."); }).show();
    }

    private void showHistory() {
        dialogBuilder().setTitle("Chat history").setMessage("Conversation history is not saved between app sessions yet. Persistent history will be added when the backend and storage support are implemented.").setPositiveButton("New chat", (d,w) -> newConversation()).setNegativeButton("Close", null).show();
    }

    private void showAttachmentMenu() {
        dialogBuilder().setTitle("Add to ARIA").setItems(new String[]{"Upload a file (coming soon)", "Take a photo (coming soon)", "Voice input (coming soon)"}, (d,w) -> toast("This feature is not connected yet.")).show();
    }

    private void showFeatureDirectory() {
        final String[] names = {
            "Web search & cited answers", "Deep research", "Voice conversation", "Speech-to-text & read aloud",
            "Image understanding", "Image generation", "Upload PDFs and documents", "Camera input",
            "Code assistant", "Code execution sandbox", "Study mode & quizzes", "Writing assistant",
            "Data analysis & charts", "Long-term memory controls", "Chat history & search", "Projects & files",
            "Custom assistants / personas", "Model selection (local / hosted)", "Streaming responses", "Sources preview cards",
            "Canvas / editable workspace", "Live camera / screen sharing", "Reminders & scheduled tasks", "App settings & privacy"
        };
        StringBuilder list = new StringBuilder();
        for (String name : names) {
            list.append("• ").append(name).append("\n");
        }
        list.append("\nStatus: This is the feature roadmap in the app. Only chat with the current ARIA backend and source-link display are connected today. Other features need implementation and backend/API support before they work.");
        dialogBuilder()
            .setTitle("ARIA capabilities")
            .setMessage(list.toString())
            .setPositiveButton("Got it", (dialog, which) -> {})
            .setNeutralButton("Backend settings", (dialog, which) -> showBackendHelp())
            .show();
    }

    private void showBackendHelp() {
        dialogBuilder()
            .setTitle("Backend connection")
            .setMessage("ARIA currently sends chat requests to the configured HTTPS /chat endpoint. Render is okay for hosting, but a free service may sleep when idle. Advanced tools need explicit API endpoints and response formats before they can be connected.")
            .setPositiveButton("OK", (dialog, which) -> {})
            .show();
    }

    private void sendMessage() {
        final String message = input.getText().toString().trim();
        final String base = serverInput.getText().toString().trim().replaceAll("/+$", "");
        if (message.isEmpty()) return;
        if (!base.startsWith("https://")) { toast("Please use an HTTPS backend URL."); return; }
        input.setText(""); ((InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(input.getWindowToken(), 0);
        showTab(false); addUserMessage(message); setThinking(true); sendButton.setEnabled(false); sendButton.setAlpha(0.55f);
        executor.execute(() -> {
            String reply; ArrayList<SourceItem> sources = new ArrayList<>();
            try {
                HttpURLConnection conn = (HttpURLConnection)new URL(base + "/chat").openConnection();
                conn.setRequestMethod("POST"); conn.setConnectTimeout(30000); conn.setReadTimeout(180000); conn.setRequestProperty("Accept", "application/json"); conn.setRequestProperty("Content-Type", "application/json; charset=utf-8"); conn.setDoOutput(true);
                JSONObject payload = new JSONObject(); payload.put("message", message); payload.put("session_id", sessionId);
                try (OutputStream os = conn.getOutputStream()) { os.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
                int code = conn.getResponseCode(); InputStream stream = code >= 200 && code < 400 ? conn.getInputStream() : conn.getErrorStream(); StringBuilder body = new StringBuilder();
                if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) { String line; while ((line = reader.readLine()) != null) body.append(line).append('\n'); }
                if (code >= 200 && code < 300) {
                    JSONObject response = new JSONObject(body.toString()); reply = response.optString("reply", response.optString("answer", "")).trim(); if (reply.isEmpty()) reply = "The ARIA backend returned an empty response. Check the backend logs and try again.";
                    collectSources(response, sources); if (!response.optBoolean("success", true)) reply = "Request did not complete: " + reply;
                } else { String detail = body.toString().trim(); if (detail.length() > 700) detail = detail.substring(0, 700); reply = "The ARIA server returned HTTP " + code + (detail.isEmpty() ? ". Please try again shortly." : ".\n\nServer detail: " + detail); }
                conn.disconnect();
            } catch (java.net.SocketTimeoutException ex) { reply = "ARIA is taking longer than expected. The request timed out. Please try again; a sleeping free Render service may need time to wake up."; } catch (Exception ex) { reply = "I couldn't reach the ARIA backend (" + ex.getClass().getSimpleName() + "). Check your internet connection and confirm the backend is online."; }
            final String finalReply = reply; final ArrayList<SourceItem> finalSources = sources;
            runOnUiThread(() -> { setThinking(false); addAssistantMessage(cleanAnswer(finalReply), finalSources); sendButton.setEnabled(true); sendButton.setAlpha(1f); if (!appVisible) notifyResponseReady(); });
        });
    }

    private void collectSources(JSONObject response, ArrayList<SourceItem> into) {
        String[] keys = {"sources", "citations", "source_urls", "references"};
        for (String key : keys) {
            Object obj = response.opt(key);
            if (obj instanceof JSONArray) {
                JSONArray a = (JSONArray)obj;
                for (int i=0; i<a.length(); i++) {
                    Object item = a.opt(i); String url = "", title = "";
                    if (item instanceof JSONObject) { JSONObject o=(JSONObject)item; url=o.optString("url", o.optString("href", o.optString("source", ""))); title=o.optString("title", o.optString("name", "")); }
                    else if (item != null) url=item.toString();
                    addSourceIfValid(into, title, url);
                }
            } else if (obj instanceof String) addUrls(into, (String)obj);
        }
        addUrls(into, response.optString("reply", "")); addUrls(into, response.optString("answer", ""));
    }

    private void addUrls(ArrayList<SourceItem> into, String text) {
        Matcher m = Pattern.compile("https?://[^\\s)\\]}>]+", Pattern.CASE_INSENSITIVE).matcher(text);
        while (m.find()) { String u=m.group().replaceAll("[.,;]+$", ""); addSourceIfValid(into, "", u); }
    }
    private void addSourceIfValid(ArrayList<SourceItem> into, String title, String url) {
        if (url == null || !(url.startsWith("https://") || url.startsWith("http://"))) return;
        for (SourceItem s : into) if (s.url.equals(url)) return;
        into.add(new SourceItem(title == null || title.trim().isEmpty() ? Uri.parse(url).getHost() : title, url));
    }

    private String cleanAnswer(String raw) {
        StringBuilder out = new StringBuilder();
        for (String line : raw.split("\\r?\\n")) {
            String t=line.trim();
            if (t.matches("(?i)^(sources?|references?|citations?)\\s*:?\\s*$")) continue;
            if (t.matches("(?i)^(sources?|references?|citations?)\\s*:\\s*https?://.*$")) continue;
            out.append(line).append('\n');
        }
        return out.toString().trim().replaceAll("\\n{3,}", "\n\n");
    }

    private void addUserMessage(String text) {
        LinearLayout wrap = new LinearLayout(this); wrap.setOrientation(LinearLayout.VERTICAL); wrap.setGravity(Gravity.END); wrap.setPadding(dp(32), dp(5), 0, dp(14));
        TextView body = label(text, 15, TEXT, false); body.setPadding(dp(15), dp(11), dp(15), dp(11)); body.setBackground(userBubbleBackground()); body.setMaxWidth(getResources().getDisplayMetrics().widthPixels - dp(76)); wrap.addView(body, new LinearLayout.LayoutParams(-2, -2));
        transcript.addView(wrap); scrollDown(transcriptScroll);
    }

    private void addAssistantMessage(String text, ArrayList<SourceItem> sources) {
        LinearLayout wrap = new LinearLayout(this); wrap.setOrientation(LinearLayout.VERTICAL); wrap.setPadding(dp(2), dp(5), dp(2), dp(18));
        LinearLayout whoRow = new LinearLayout(this); whoRow.setOrientation(LinearLayout.HORIZONTAL); whoRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView badge=label("✦", 13, Color.WHITE, true); badge.setGravity(Gravity.CENTER); badge.setBackground(glassAccent()); whoRow.addView(badge, new LinearLayout.LayoutParams(dp(27), dp(27)));
        TextView who=label("  ARIA", 13, TEXT, true); whoRow.addView(who); wrap.addView(whoRow);
        TextView body = new TextView(this); body.setText(markdownLite(text)); body.setTextColor(TEXT); body.setTextSize(16); body.setLineSpacing(dp(4), 1.02f); body.setTextIsSelectable(true); body.setPadding(dp(1), dp(10), dp(1), dp(4)); wrap.addView(body);
        if (sources != null && !sources.isEmpty()) {
            TextView sourcesLink = label("↗  Sources · " + sources.size(), 12, ACCENT, true); sourcesLink.setPadding(dp(2),dp(8),dp(2),dp(3)); sourcesLink.setOnClickListener(v -> showSourcesDialog(sources)); wrap.addView(sourcesLink);
        }
        LinearLayout actions = new LinearLayout(this); actions.setOrientation(LinearLayout.HORIZONTAL); actions.setGravity(Gravity.CENTER_VERTICAL);
        TextView copy = label("▢  Copy", 11, MUTED, false); copy.setPadding(dp(3),dp(8),dp(15),dp(4)); copy.setOnClickListener(v -> { android.content.ClipboardManager cm=(android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE); cm.setPrimaryClip(android.content.ClipData.newPlainText("ARIA answer", text)); toast("Answer copied"); }); actions.addView(copy);
        wrap.addView(actions); transcript.addView(wrap); scrollDown(transcriptScroll);
        if (sources != null) { lastSources.clear(); lastSources.addAll(sources); renderSources(); }
    }

    private void showSourcesDialog(ArrayList<SourceItem> sources) {
        LinearLayout list = new LinearLayout(this); list.setOrientation(LinearLayout.VERTICAL); list.setPadding(dp(16),dp(8),dp(16),dp(8));
        for (SourceItem item : sources) { TextView link=label(item.title + "\n" + item.url, 13, ACCENT, false); link.setPadding(0,dp(10),0,dp(10)); list.addView(link); link.setOnClickListener(v -> { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(item.url))); } catch(Exception e) { toast("No browser available"); } }); }
        ScrollView sc = new ScrollView(this); sc.setVerticalScrollBarEnabled(false); sc.addView(list); dialogBuilder().setTitle("Sources & links").setView(sc).setPositiveButton("Done",null).show();
    }

    private SpannableString markdownLite(String source) {
        StringBuilder plain = new StringBuilder();
        ArrayList<int[]> boldRanges = new ArrayList<>();
        int i = 0;
        while (i < source.length()) {
            if (i + 1 < source.length() && source.charAt(i) == '*' && source.charAt(i + 1) == '*') {
                int close = source.indexOf("**", i + 2);
                if (close >= 0) {
                    int begin = plain.length();
                    plain.append(source.substring(i + 2, close));
                    boldRanges.add(new int[]{begin, plain.length()});
                    i = close + 2;
                    continue;
                }
            }
            plain.append(source.charAt(i++));
        }
        String text = plain.toString();
        SpannableString span = new SpannableString(text);
        for (int[] range : boldRanges) if (range[1] > range[0] && range[1] <= text.length())
            span.setSpan(new StyleSpan(Typeface.BOLD), range[0], range[1], Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
        int offset = 0;
        for (String line : text.split("\\n", -1)) {
            String trimmed = line.trim();
            if (trimmed.startsWith("#") && !trimmed.isEmpty()) {
                int st = offset + line.indexOf(trimmed);
                while (st < text.length() && text.charAt(st) == '#') st++;
                while (st < text.length() && text.charAt(st) == ' ') st++;
                int en = offset + line.length();
                if (st < en) {
                    span.setSpan(new StyleSpan(Typeface.BOLD), st, en, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
                    span.setSpan(new RelativeSizeSpan(1.12f), st, en, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
                }
            }
            offset += line.length() + 1;
        }
        return span;
    }
    private void renderSources() {
        sourcesPanel.removeAllViews();
        TextView intro=label("LINKS & SOURCES", 12, MUTED, true); intro.setPadding(0,0,0,dp(10)); sourcesPanel.addView(intro);
        if (lastSources.isEmpty()) { TextView none=label("No source links were returned for this answer.", 14, MUTED, false); none.setPadding(dp(14),dp(14),dp(14),dp(14)); none.setBackground(round(PANEL,14)); sourcesPanel.addView(none); return; }
        for (SourceItem s : lastSources) {
            LinearLayout card=new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(13),dp(12),dp(13),dp(12)); card.setBackground(round(PANEL,14)); LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-1,-2); cp.bottomMargin=dp(8); sourcesPanel.addView(card,cp);
            card.addView(label(s.title,14,TEXT,true)); TextView url=label(s.url,12,ACCENT,false); url.setPadding(0,dp(5),0,0); card.addView(url);
            card.setOnClickListener(v -> { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(s.url))); } catch(Exception e) { toast("No browser available to open this link."); } });
        }
    }

    private void setThinking(boolean active) {
        if (active) {
            LinearLayout row=new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL); row.setOrientation(LinearLayout.HORIZONTAL); row.setTag("thinking"); row.setPadding(dp(2),dp(8),0,dp(12));
            thinkingSpinner=new ProgressBar(this); row.addView(thinkingSpinner,new LinearLayout.LayoutParams(dp(22),dp(22)));
            thinkingLabel=label("  Thinking…",13,MUTED,false); row.addView(thinkingLabel); transcript.addView(row); scrollDown(transcriptScroll);
            thinkingLabel.postDelayed(new Runnable(){ int i=0; String[] states={"  Thinking…","  Checking knowledge…","  Preparing answer…","  Almost there…"}; public void run(){ if (thinkingLabel==null || thinkingLabel.getParent()==null) return; thinkingLabel.setText(states[i++%states.length]); thinkingLabel.postDelayed(this,1100); }},1100);
        } else {
            for(int i=transcript.getChildCount()-1;i>=0;i--) { View v=transcript.getChildAt(i); if("thinking".equals(v.getTag())) { transcript.removeViewAt(i); break; } }
            thinkingLabel=null; thinkingSpinner=null;
        }
    }

    private void showTab(boolean sources) {
        showingSources=sources; styleTab(answerTab,"Answer",!sources); styleTab(sourcesTab,"Sources",sources);
        int idx=root.indexOfChild(transcriptScroll); if(idx>=0) root.removeView(transcriptScroll); idx=root.indexOfChild(sourcesScroll); if(idx>=0) root.removeView(sourcesScroll);
        int composerIndex=root.indexOfChild(composer); root.addView(sources ? sourcesScroll : transcriptScroll, composerIndex);
    }
    private void styleTab(Button b,String text,boolean active) { b.setText(text); b.setAllCaps(false); b.setTextSize(13); b.setTypeface(null, active?Typeface.BOLD:Typeface.NORMAL); b.setTextColor(active?TEXT:MUTED); b.setBackground(round(active?PANEL2:Color.TRANSPARENT,10)); b.setPadding(0,0,0,0); }
    private TextView label(String text,int size,int color,boolean bold) { TextView t=new TextView(this); t.setText(text); t.setTextSize(size); t.setTextColor(color); if(bold)t.setTypeface(null,Typeface.BOLD); return t; }
    private GradientDrawable round(int color,int radius) { GradientDrawable d=new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d; }
    private GradientDrawable glassBackground() {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
            new int[]{Color.rgb(27, 30, 36), Color.rgb(21, 23, 28)});
        d.setCornerRadius(dp(18));
        d.setStroke(dp(1), Color.argb(45, 210, 220, 240));
        return d;
    }
    private GradientDrawable glassAccent() {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
            new int[]{Color.rgb(145, 168, 255), Color.rgb(92, 112, 221)});
        d.setCornerRadius(dp(14));
        d.setStroke(dp(1), Color.argb(90, 255, 255, 255));
        return d;
    }
    private GradientDrawable userBubbleBackground() {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
            new int[]{Color.rgb(54, 73, 116), Color.rgb(35, 49, 82)});
        d.setCornerRadius(dp(19));
        d.setStroke(dp(1), Color.argb(65, 190, 207, 255));
        return d;
    }
    private int dp(int v) { return (int)(v*getResources().getDisplayMetrics().density+0.5f); }
    private void scrollDown(ScrollView s) { s.post(() -> s.fullScroll(View.FOCUS_DOWN)); }
    private void toast(String msg) { Toast.makeText(this,msg,Toast.LENGTH_SHORT).show(); }
    @Override protected void onDestroy() { super.onDestroy(); executor.shutdownNow(); }
}
