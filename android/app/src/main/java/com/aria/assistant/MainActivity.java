package com.aria.assistant;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.Spannable;
import android.text.SpannableString;
import android.text.style.StyleSpan;
import android.text.style.RelativeSizeSpan;
import android.text.style.ForegroundColorSpan;
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
        getWindow().getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        buildUi();
        // Respect status bars, gesture/navigation bars, and display cutouts across Android versions.
        if (android.os.Build.VERSION.SDK_INT >= 20) {
            root.setOnApplyWindowInsetsListener((view, insets) -> {
                int left = insets.getSystemWindowInsetLeft();
                int top = insets.getSystemWindowInsetTop();
                int right = insets.getSystemWindowInsetRight();
                int bottom = insets.getSystemWindowInsetBottom();
                view.setPadding(dp(16) + left, dp(8) + top, dp(16) + right, dp(8) + bottom);
                return insets;
            });
            root.requestApplyInsets();
        }
        addAssistantMessage("Hey, I'm ARIA. What can I help you with?", null);
    }

    private void buildUi() {
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(BG);
        root.setPadding(dp(16), dp(8), dp(16), dp(8));
        root.setBackground(glassBackground());

        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL); header.setOrientation(LinearLayout.HORIZONTAL);
        TextView mark = new TextView(this); mark.setText("A"); mark.setTextColor(Color.WHITE); mark.setTextSize(19); mark.setTypeface(null, Typeface.BOLD); mark.setGravity(Gravity.CENTER); mark.setBackground(glassAccent());
        header.addView(mark, new LinearLayout.LayoutParams(dp(42), dp(42)));
        LinearLayout titles = new LinearLayout(this); titles.setOrientation(LinearLayout.VERTICAL); titles.setPadding(dp(10), 0, 0, 0);
        TextView title = label("ARIA", 19, TEXT, true); TextView subtitle = label("PERSONAL AI ASSISTANT", 10, MUTED, true);
        titles.addView(title); titles.addView(subtitle); header.addView(titles, new LinearLayout.LayoutParams(0, -2, 1));
        TextView status = label("● ONLINE", 11, Color.rgb(110, 220, 160), true); header.addView(status);
        root.addView(header, new LinearLayout.LayoutParams(-1, dp(48)));

        // Feature launcher: visible product roadmap, with honest status for tools not yet wired to backend.
        Button featuresButton = new Button(this);
        featuresButton.setText("＋  Explore ARIA features");
        featuresButton.setAllCaps(false);
        featuresButton.setTextSize(13);
        featuresButton.setTextColor(TEXT);
        featuresButton.setBackground(glassBackground());
        LinearLayout.LayoutParams featuresP = new LinearLayout.LayoutParams(-1, dp(42));
        featuresP.topMargin = dp(7);
        root.addView(featuresButton, featuresP);
        featuresButton.setOnClickListener(v -> showFeatureDirectory());

        serverInput = new EditText(this); serverInput.setSingleLine(true); serverInput.setText(DEFAULT_SERVER); serverInput.setTextColor(MUTED); serverInput.setTextSize(11); serverInput.setHint("Backend HTTPS URL"); serverInput.setPadding(dp(10), 0, dp(10), 0); serverInput.setBackground(glassBackground());
        LinearLayout.LayoutParams serverP = new LinearLayout.LayoutParams(-1, dp(36)); serverP.topMargin = dp(8); root.addView(serverInput, serverP);

        tabRow = new LinearLayout(this); tabRow.setOrientation(LinearLayout.HORIZONTAL); tabRow.setPadding(dp(3), dp(3), dp(3), dp(3)); tabRow.setBackground(glassBackground());
        answerTab = new Button(this); sourcesTab = new Button(this); styleTab(answerTab, "Answer", true); styleTab(sourcesTab, "Sources", false);
        tabRow.addView(answerTab, new LinearLayout.LayoutParams(0, dp(38), 1)); tabRow.addView(sourcesTab, new LinearLayout.LayoutParams(0, dp(38), 1));
        LinearLayout.LayoutParams tabsP = new LinearLayout.LayoutParams(-1, dp(44)); tabsP.topMargin = dp(9); root.addView(tabRow, tabsP);
        answerTab.setOnClickListener(v -> showTab(false)); sourcesTab.setOnClickListener(v -> showTab(true));

        transcriptScroll = new ScrollView(this); transcriptScroll.setFillViewport(true); transcript = new LinearLayout(this); transcript.setOrientation(LinearLayout.VERTICAL); transcript.setPadding(0, dp(12), 0, dp(14)); transcriptScroll.addView(transcript, new ScrollView.LayoutParams(-1, -2));
        sourcesScroll = new ScrollView(this); sourcesPanel = new LinearLayout(this); sourcesPanel.setOrientation(LinearLayout.VERTICAL); sourcesPanel.setPadding(0, dp(12), 0, dp(14)); sourcesScroll.addView(sourcesPanel, new ScrollView.LayoutParams(-1, -2));
        root.addView(transcriptScroll, new LinearLayout.LayoutParams(-1, 0, 1));

        composer = new LinearLayout(this); composer.setOrientation(LinearLayout.HORIZONTAL); composer.setGravity(Gravity.BOTTOM); composer.setPadding(dp(8), dp(6), dp(5), dp(6)); composer.setBackground(glassBackground()); composer.setElevation(dp(8));
        input = new EditText(this); input.setTextColor(TEXT); input.setHintTextColor(MUTED); input.setTextSize(15); input.setHint("Message ARIA…"); input.setGravity(Gravity.CENTER_VERTICAL); input.setMinHeight(dp(44)); input.setMaxLines(5); input.setPadding(dp(8), dp(7), dp(8), dp(7)); input.setBackgroundColor(Color.TRANSPARENT);
        composer.addView(input, new LinearLayout.LayoutParams(0, -2, 1));
        sendButton = new Button(this); sendButton.setText("↑"); sendButton.setTextSize(22); sendButton.setTextColor(Color.WHITE); sendButton.setAllCaps(false); sendButton.setPadding(0, 0, 0, dp(3)); sendButton.setBackground(round(ACCENT, 14)); composer.addView(sendButton, new LinearLayout.LayoutParams(dp(48), dp(46)));
        LinearLayout.LayoutParams compP = new LinearLayout.LayoutParams(-1, -2); compP.bottomMargin = dp(3); root.addView(composer, compP);
        TextView footer = label("ARIA can make mistakes. Check important information.", 10, MUTED, false); footer.setGravity(Gravity.CENTER); LinearLayout.LayoutParams fp = new LinearLayout.LayoutParams(-1, dp(20)); root.addView(footer, fp);
        sendButton.setOnClickListener(v -> sendMessage());
        input.setOnEditorActionListener((v, action, event) -> { if (event != null && event.getKeyCode() == android.view.KeyEvent.KEYCODE_ENTER && !event.isShiftPressed()) { sendMessage(); return true; } return false; });
        setContentView(root);
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
        new AlertDialog.Builder(this)
            .setTitle("ARIA capabilities")
            .setMessage(list.toString())
            .setPositiveButton("Got it", (dialog, which) -> {})
            .setNeutralButton("Backend settings", (dialog, which) -> showBackendHelp())
            .show();
    }

    private void showBackendHelp() {
        new AlertDialog.Builder(this)
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
        showTab(false); addUserMessage(message); setThinking(true); sendButton.setEnabled(false);
        executor.execute(() -> {
            String reply; ArrayList<SourceItem> sources = new ArrayList<>();
            try {
                HttpURLConnection conn = (HttpURLConnection)new URL(base + "/chat").openConnection();
                conn.setRequestMethod("POST"); conn.setConnectTimeout(20000); conn.setReadTimeout(90000); conn.setRequestProperty("Content-Type", "application/json; charset=utf-8"); conn.setDoOutput(true);
                JSONObject payload = new JSONObject(); payload.put("message", message); payload.put("session_id", sessionId);
                try (OutputStream os = conn.getOutputStream()) { os.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
                int code = conn.getResponseCode(); InputStream stream = code >= 200 && code < 400 ? conn.getInputStream() : conn.getErrorStream(); StringBuilder body = new StringBuilder();
                if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) { String line; while ((line = reader.readLine()) != null) body.append(line).append('\n'); }
                if (code >= 200 && code < 300) {
                    JSONObject response = new JSONObject(body.toString()); reply = response.optString("reply", response.optString("answer", "The server returned no reply."));
                    collectSources(response, sources); if (!response.optBoolean("success", true)) reply = "Request did not complete: " + reply;
                } else reply = "The ARIA server returned HTTP " + code + ". Please try again shortly.";
                conn.disconnect();
            } catch (Exception ex) { reply = "I couldn't reach the ARIA backend. Check your connection; the free Render service may be waking up after inactivity."; }
            final String finalReply = reply; final ArrayList<SourceItem> finalSources = sources;
            runOnUiThread(() -> { setThinking(false); addAssistantMessage(cleanAnswer(finalReply), finalSources); sendButton.setEnabled(true); });
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
        LinearLayout wrap = new LinearLayout(this); wrap.setOrientation(LinearLayout.VERTICAL); wrap.setGravity(Gravity.END); wrap.setPadding(dp(30), dp(4), 0, dp(10));
        TextView who=label("YOU", 10, MUTED, true); who.setGravity(Gravity.RIGHT); wrap.addView(who);
        TextView body = label(text, 15, TEXT, false); body.setPadding(dp(14), dp(11), dp(14), dp(11)); body.setBackground(userBubbleBackground()); wrap.addView(body, new LinearLayout.LayoutParams(-2, -2));
        transcript.addView(wrap); scrollDown(transcriptScroll);
    }

    private void addAssistantMessage(String text, ArrayList<SourceItem> sources) {
        LinearLayout wrap = new LinearLayout(this); wrap.setOrientation(LinearLayout.VERTICAL); wrap.setPadding(0, dp(4), dp(20), dp(14));
        LinearLayout whoRow = new LinearLayout(this); whoRow.setOrientation(LinearLayout.HORIZONTAL); whoRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView badge=label("A", 12, Color.WHITE, true); badge.setGravity(Gravity.CENTER); badge.setBackground(glassAccent()); whoRow.addView(badge, new LinearLayout.LayoutParams(dp(25), dp(25)));
        TextView who=label("  ARIA", 12, TEXT, true); whoRow.addView(who); wrap.addView(whoRow);
        TextView body = new TextView(this); body.setText(markdownLite(text)); body.setTextColor(TEXT); body.setTextSize(15); body.setLineSpacing(dp(3), 1f); body.setTextIsSelectable(true); body.setPadding(dp(2), dp(9), dp(2), dp(2)); wrap.addView(body);
        transcript.addView(wrap); scrollDown(transcriptScroll);
        if (sources != null) { lastSources.clear(); lastSources.addAll(sources); renderSources(); }
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
            new int[]{Color.argb(205, 37, 47, 68), Color.argb(170, 19, 25, 39), Color.argb(190, 31, 39, 58)});
        d.setCornerRadius(dp(20));
        d.setStroke(dp(1), Color.argb(70, 205, 220, 255));
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
