package com.aria.assistant;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
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
import android.view.Window;
import android.view.WindowManager;
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
import android.widget.PopupWindow;
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
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Set;
import java.security.SecureRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int BG = Color.rgb(9, 12, 20), PANEL = Color.argb(154, 28, 35, 52), PANEL2 = Color.argb(194, 49, 61, 87);
    private static final int TEXT = Color.rgb(242, 245, 252), MUTED = Color.rgb(165, 176, 197), ACCENT = Color.rgb(127, 155, 255);
    private static final String DEFAULT_SERVER = "https://aria-ai-s5go.onrender.com";
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private String activeChatId = "";
    private final ArrayList<ChatRecord> chatHistory = new ArrayList<>();
    private boolean loadingChat = false;
    private static final String CHAT_PREFS = "aria_chat_history";
    private static final String CHAT_LIST_KEY = "chats_json";
    private static class ChatRecord {
        String id, title, projectName = ""; boolean pinned, archived; long updatedAt; JSONArray messages = new JSONArray();
        ChatRecord(String id, String title) { this.id=id; this.title=title; updatedAt=System.currentTimeMillis(); }
        JSONObject toJson() throws Exception {
            JSONObject o=new JSONObject(); o.put("id",id); o.put("title",title); o.put("pinned",pinned); o.put("archived",archived); o.put("projectName",projectName); o.put("updatedAt",updatedAt); o.put("messages",messages); return o;
        }
        static ChatRecord fromJson(JSONObject o) {
            ChatRecord c=new ChatRecord(o.optString("id",java.util.UUID.randomUUID().toString()),o.optString("title","New chat"));
            c.pinned=o.optBoolean("pinned",false); c.archived=o.optBoolean("archived",false); c.projectName=o.optString("projectName",""); c.updatedAt=o.optLong("updatedAt",System.currentTimeMillis());
            JSONArray a=o.optJSONArray("messages"); if(a!=null)c.messages=a; return c;
        }
    }
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

    /** Request the panel's highest practical refresh rate without assuming that
     * the display can deliver it. The OS/device may cap this to 60/90 Hz. */
    private void configureSmoothWindow() {
        Window window = getWindow();
        if (window == null) return;
        if (android.os.Build.VERSION.SDK_INT >= 23) {
            WindowManager.LayoutParams attrs = window.getAttributes();
            attrs.preferredRefreshRate = 120f;
            window.setAttributes(attrs);
        }
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        configureSmoothWindow();
        getWindow().setStatusBarColor(Color.rgb(12, 16, 28));
        getWindow().setNavigationBarColor(Color.rgb(12, 16, 28));
        getWindow().getDecorView().setSystemUiVisibility(0);
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            getWindow().getAttributes().layoutInDisplayCutoutMode =
                    android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER;
        }
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        createNotificationChannel();
        if (getSharedPreferences("aria_auth", MODE_PRIVATE).getString("access_token", "").isEmpty()) {
            buildSignInUi();
            return;
        }
        loadChatHistory();
        activeChatId = chatHistory.isEmpty() ? "" : chatHistory.get(0).id;
        buildUi();
        restoreActiveChat();
        requestNotificationPermissionIfNeeded();
        checkForUpdates();
    }

    @Override protected void onDestroy() {
        appVisible = false;
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override protected void onResume() { super.onResume(); appVisible = true; }
    @Override protected void onStop() { appVisible = false; super.onStop(); }

    /** All native alert dialogs are restyled after showing so menus, settings,
     * source lists, profile, update prompts and confirmations share ARIA's theme. */
    private final class GlassDialogBuilder extends AlertDialog.Builder {
        GlassDialogBuilder() {
            super(new android.view.ContextThemeWrapper(MainActivity.this,
                    android.R.style.Theme_Material_Dialog_Alert));
        }

        @Override public AlertDialog show() {
            AlertDialog dialog = super.show();
            if (dialog.getWindow() != null) {
                dialog.getWindow().setBackgroundDrawable(glassDialogBackground());
                dialog.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);
                if (android.os.Build.VERSION.SDK_INT >= 31) {
                    dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND);
                    dialog.getWindow().setBackgroundBlurRadius(dp(32));
                }
                android.view.WindowManager.LayoutParams lp = dialog.getWindow().getAttributes();
                lp.dimAmount = 0.72f;
                dialog.getWindow().setAttributes(lp);
            }
            int accent = Color.rgb(165, 190, 255);
            int titleId = getResources().getIdentifier("alertTitle", "id", "android");
            TextView title = dialog.findViewById(titleId);
            if (title != null) title.setTextColor(TEXT);
            TextView message = dialog.findViewById(android.R.id.message);
            if (message != null) message.setTextColor(MUTED);
            for (int id : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEGATIVE,
                    AlertDialog.BUTTON_NEUTRAL}) {
                Button button = dialog.getButton(id);
                if (button != null) {
                    button.setTextColor(accent);
                    button.setAllCaps(false);
                    button.setTypeface(null, Typeface.BOLD);
                }
            }
            return dialog;
        }
    }

    private AlertDialog.Builder dialogBuilder() {
        return new GlassDialogBuilder();
    }

    private GradientDrawable glassDialogBackground() {
        GradientDrawable d = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(43, 52, 76), Color.rgb(24, 30, 47)});
        d.setCornerRadius(dp(24));
        d.setStroke(dp(1), Color.argb(155, 180, 204, 255));
        return d;
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
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{Color.rgb(11, 15, 28), Color.rgb(7, 9, 17)}));
        root.setPadding(dp(16), dp(6), dp(16), dp(6));

        // Compact ChatGPT-inspired header: navigation, brand, and new-chat action.
        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setPadding(0, dp(2), 0, dp(8));
        TextView menu = label("☰", 22, TEXT, false);
        menu.setGravity(Gravity.CENTER);
        header.addView(menu, new LinearLayout.LayoutParams(dp(42), dp(44)));
        menu.setOnClickListener(v -> showSideDrawer());

        LinearLayout brand = new LinearLayout(this);
        brand.setOrientation(LinearLayout.HORIZONTAL);
        brand.setGravity(Gravity.CENTER_VERTICAL);
        TextView mark = label("✦", 21, Color.WHITE, true);
        mark.setGravity(Gravity.CENTER);
        mark.setBackground(glassAccent());
        brand.addView(mark, new LinearLayout.LayoutParams(dp(34), dp(34)));
        TextView title = label("  ARIA", 18, TEXT, true);
        brand.addView(title);
        header.addView(brand, new LinearLayout.LayoutParams(0, -1, 1));
        TextView newChat = label("＋", 27, TEXT, false);
        newChat.setGravity(Gravity.CENTER);
        header.addView(newChat, new LinearLayout.LayoutParams(dp(42), dp(44)));
        newChat.setOnClickListener(v -> newConversation());
        root.addView(header, new LinearLayout.LayoutParams(-1, dp(48)));

        tabRow = new LinearLayout(this); tabRow.setOrientation(LinearLayout.HORIZONTAL); tabRow.setGravity(Gravity.CENTER_VERTICAL);
        tabRow.setPadding(0, dp(2), 0, dp(8));
        answerTab = new Button(this); sourcesTab = new Button(this);
        styleTab(answerTab, "Answer", true); styleTab(sourcesTab, "Sources", false);
        tabRow.addView(answerTab, new LinearLayout.LayoutParams(dp(86), dp(36)));
        tabRow.addView(sourcesTab, new LinearLayout.LayoutParams(dp(86), dp(36)));
        root.addView(tabRow, new LinearLayout.LayoutParams(-1, dp(42)));
        // Sources remain available from individual answers; hide the extra tab strip
        // so the primary chat layout stays close to ChatGPT's uncluttered screen.
        tabRow.setVisibility(View.GONE);
        answerTab.setOnClickListener(v -> showTab(false)); sourcesTab.setOnClickListener(v -> showTab(true));

        // Keep configuration out of the conversation view; accessible through the menu.
        serverInput = new EditText(this);
        serverInput.setSingleLine(true);
        serverInput.setText(DEFAULT_SERVER);

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
        composer.setPadding(dp(8), dp(5), dp(6), dp(5));
        composer.setBackground(glassBackground());
        composer.setElevation(dp(3));
        composer.setElevation(dp(2));
        TextView add = label("＋", 24, MUTED, false);
        add.setGravity(Gravity.CENTER);
        composer.addView(add, new LinearLayout.LayoutParams(dp(38), dp(42)));
        add.setOnClickListener(v -> showAttachmentMenu(v));
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
        TextView disclaimer = label("ARIA can make mistakes. Check important information.", 10, Color.rgb(125, 132, 148), false);
        disclaimer.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams disclaimerParams = new LinearLayout.LayoutParams(-1, dp(20));
        root.addView(disclaimer, disclaimerParams);

        // Profile and settings live in the navigation drawer, not in a permanent bottom dock.

        sendButton.setOnClickListener(v -> sendMessage());
        input.setOnEditorActionListener((v, action, event) -> {
            if (event != null && event.getKeyCode() == android.view.KeyEvent.KEYCODE_ENTER && !event.isShiftPressed()) { sendMessage(); return true; }
            return false;
        });
        setContentView(root);
        // Explicit safe-area padding for Android 15+ edge-to-edge and display cutouts.
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int topInset = insets.getSystemWindowInsetTop();
            int bottomInset = insets.getSystemWindowInsetBottom();
            v.setPadding(dp(16), topInset + dp(6), dp(16), bottomInset + dp(6));
            return insets;
        });
        root.requestApplyInsets();
    }

    private void showAppMenu() {
        showSideDrawer();
    }

    /**
     * ChatGPT-inspired navigation drawer. Uses a real side-aligned Dialog so it
     * adapts to narrow phones, landscape, display cutouts, and system bars.
     */
    private void showSideDrawer() {
        final Dialog drawer = new Dialog(this);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        int statusBarHeight = 0;
        int statusBarRes = getResources().getIdentifier("status_bar_height", "dimen", "android");
        if (statusBarRes > 0) statusBarHeight = getResources().getDimensionPixelSize(statusBarRes);
        panel.setPadding(dp(16), statusBarHeight + dp(12), dp(12), dp(12));
        GradientDrawable drawerGlass = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(38, 45, 64), Color.rgb(24, 28, 41)});
        drawerGlass.setCornerRadius(dp(0));
        drawerGlass.setStroke(dp(1), Color.argb(175, 205, 220, 255));
        panel.setBackground(drawerGlass);

        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView brand = label("ARIA", 21, TEXT, true);
        top.addView(brand, new LinearLayout.LayoutParams(0, dp(48), 1));
        TextView close = label("×", 30, MUTED, false);
        close.setGravity(Gravity.CENTER);
        top.addView(close, new LinearLayout.LayoutParams(dp(42), dp(42)));
        close.setOnClickListener(v -> drawer.dismiss());
        panel.addView(top);

        TextView search = drawerItem("⌕", "Search chats", "Find a past conversation");
        panel.addView(search);
        search.setOnClickListener(v -> { drawer.dismiss(); showHistorySearch(); });

        TextView newChatItem = drawerItem("＋", "New chat", null);
        panel.addView(newChatItem);
        newChatItem.setOnClickListener(v -> { drawer.dismiss(); newConversation(); });

        addDrawerDivider(panel);
        addDrawerSection(panel, "YOUR SPACE");
        addDrawerRow(panel, drawer, "▧", "Images", "Images and generated artwork");
        addDrawerRow(panel, drawer, "▤", "Library", "Files and saved material");
        addDrawerRow(panel, drawer, "▱", "Projects", "Organize chats by project");
        addDrawerRow(panel, drawer, "⌘", "Remote", "Remote tools and computer workflows");
        addDrawerRow(panel, drawer, "◷", "Scheduled", "Reminders and scheduled tasks");
        addDrawerRow(panel, drawer, "◉", "Plugins", "Connected tools and integrations");

        addDrawerDivider(panel);
        addDrawerDivider(panel);
        addDrawerSection(panel, "PINNED CHATS");
        ArrayList<ChatRecord> sorted = new ArrayList<>(chatHistory);
        Collections.sort(sorted, (x,y) -> Long.compare(y.updatedAt, x.updatedAt));
        boolean hasPinned = false;
        for (ChatRecord chat : sorted) if (chat.pinned && !chat.archived) { hasPinned=true; addChatHistoryRow(panel, drawer, chat, true); }
        if (!hasPinned) {
            TextView empty = label("No pinned chats yet", 12, MUTED, false);
            empty.setPadding(dp(10), dp(8), dp(8), dp(8)); panel.addView(empty);
        }
        addDrawerDivider(panel);
        addDrawerSection(panel, "RECENTS");
        boolean hasRecent = false;
        for (ChatRecord chat : sorted) if (!chat.pinned && !chat.archived) { hasRecent=true; addChatHistoryRow(panel, drawer, chat, false); }
        if (!hasRecent) {
            TextView empty = label("Your conversations will appear here", 12, MUTED, false);
            empty.setPadding(dp(10), dp(8), dp(8), dp(8)); panel.addView(empty);
        }

        addDrawerDivider(panel);
        addDrawerSection(panel, "PROJECTS");
        Set<String> projects = getProjectNames();
        if (projects.isEmpty()) {
            TextView emptyProjects = label("No projects yet", 12, MUTED, false);
            emptyProjects.setPadding(dp(10), dp(8), dp(8), dp(8));
            panel.addView(emptyProjects);
        } else {
            for (String project : projects) {
                TextView projectRow = drawerItem("▱", project, null);
                panel.addView(projectRow);
                projectRow.setOnClickListener(v -> { drawer.dismiss(); showProjectChats(project); });
            }
        }
        TextView createProject = drawerItem("＋", "Create project", null);
        panel.addView(createProject);
        createProject.setOnClickListener(v -> { drawer.dismiss(); promptCreateProject(null); });

        boolean hasArchived = false;
        for (ChatRecord c : sorted) if (c.archived) hasArchived = true;
        if (hasArchived) {
            addDrawerDivider(panel);
            addDrawerSection(panel, "ARCHIVED");
            for (ChatRecord c : sorted) if (c.archived) addChatHistoryRow(panel, drawer, c, false);
        }

        View spacer = new View(this);
        panel.addView(spacer, new LinearLayout.LayoutParams(1, 0, 1));

        View divider = new View(this);
        divider.setBackgroundColor(Color.argb(55, 255, 255, 255));
        panel.addView(divider, new LinearLayout.LayoutParams(-1, dp(1)));

        LinearLayout account = new LinearLayout(this);
        account.setGravity(Gravity.CENTER_VERTICAL);
        account.setPadding(dp(4), dp(12), dp(4), dp(4));
        TextView avatar = label("S", 17, Color.WHITE, true);
        avatar.setGravity(Gravity.CENTER);
        avatar.setBackground(round(Color.rgb(217, 112, 99), 40));
        account.addView(avatar, new LinearLayout.LayoutParams(dp(38), dp(38)));
        LinearLayout accountText = new LinearLayout(this);
        accountText.setOrientation(LinearLayout.VERTICAL);
        accountText.setPadding(dp(10), 0, 0, 0);
        accountText.addView(label("ARIA Personal", 14, TEXT, true));
        accountText.addView(label("Profile and settings", 11, MUTED, false));
        account.addView(accountText, new LinearLayout.LayoutParams(0, -2, 1));
        TextView more = label("•••", 18, MUTED, true);
        account.addView(more);
        account.setOnClickListener(v -> { drawer.dismiss(); showProfile(); });
        more.setOnClickListener(v -> { drawer.dismiss(); showSettings(); });
        panel.addView(account);

        ScrollView drawerScroll = new ScrollView(this);
        drawerScroll.setFillViewport(true);
        drawerScroll.setVerticalScrollBarEnabled(false);
        drawerScroll.setBackgroundColor(Color.TRANSPARENT);
        drawerScroll.addView(panel, new ScrollView.LayoutParams(-1, -2));
        drawer.setContentView(drawerScroll);
        Window window = drawer.getWindow();
        if (window != null) {
            window.setBackgroundDrawableResource(android.R.color.transparent);
            window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            if (android.os.Build.VERSION.SDK_INT >= 31) {
                window.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND);
                window.setBackgroundBlurRadius(dp(36));
            }
            WindowManager.LayoutParams lp = window.getAttributes();
            lp.width = Math.min((int)(getResources().getDisplayMetrics().widthPixels * 0.86f), dp(360));
            lp.height = WindowManager.LayoutParams.MATCH_PARENT;
            lp.gravity = Gravity.START;
            lp.dimAmount = 0.58f;
            window.setAttributes(lp);
            window.setWindowAnimations(android.R.style.Animation_Activity);
        }
        drawer.setCanceledOnTouchOutside(true);
        drawer.show();
        if (window != null) {
            window.setLayout(Math.min((int)(getResources().getDisplayMetrics().widthPixels * 0.86f), dp(360)),
                    WindowManager.LayoutParams.MATCH_PARENT);
            window.setGravity(Gravity.START);
        }
    }

    private TextView drawerItem(String symbol, String title, String subtitle) {
        String text = symbol + "    " + title + (subtitle == null ? "" : "\n        " + subtitle);
        TextView row = label(text, 14, TEXT, false);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(10), dp(11), dp(8), dp(11));
        row.setBackground(round(Color.TRANSPARENT, 12));
        row.setOnTouchListener((v, event) -> {
            if (event.getAction() == android.view.MotionEvent.ACTION_DOWN)
                v.setBackground(round(Color.argb(35, 255, 255, 255), 12));
            if (event.getAction() == android.view.MotionEvent.ACTION_UP ||
                    event.getAction() == android.view.MotionEvent.ACTION_CANCEL)
                v.setBackground(round(Color.TRANSPARENT, 12));
            return false;
        });
        return row;
    }

    private void addDrawerSection(LinearLayout panel, String title) {
        TextView section = label(title, 10, Color.rgb(143, 148, 158), true);
        section.setLetterSpacing(0.12f);
        section.setPadding(dp(10), dp(12), 0, dp(5));
        panel.addView(section);
    }

    private void addDrawerDivider(LinearLayout panel) {
        View divider = new View(this);
        divider.setBackgroundColor(Color.argb(38, 255, 255, 255));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(1));
        p.topMargin = dp(8);
        p.bottomMargin = dp(5);
        panel.addView(divider, p);
    }

    private void addDrawerRow(LinearLayout panel, Dialog drawer, String symbol, String title, String description) {
        TextView row = label(symbol + "    " + title, 14, TEXT, false);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(10), dp(11), dp(8), dp(11));
        row.setBackground(round(Color.TRANSPARENT, 10));
        panel.addView(row, new LinearLayout.LayoutParams(-1, -2));
        row.setOnClickListener(v -> {
            drawer.dismiss();
            if ("ARIA backend".equals(title)) showSettings();
            else if ("Projects".equals(title)) showProjects();
            else if ("Scheduled".equals(title)) showFeaturePanel(title, "Scheduled reminders will appear here when task scheduling is connected.");
            else if ("Images".equals(title)) showFeaturePanel(title, "Your image workspace. Image generation and image history require an image-capable backend.");
            else if ("Library".equals(title)) showFeaturePanel(title, "Saved files and documents will appear here when library storage is connected.");
            else if ("Remote".equals(title)) showFeaturePanel(title, "Remote computer control is not connected in this Android build.");
            else if ("Plugins".equals(title)) showFeaturePanel(title, "Tool integrations and plugins will appear here when configured.");
            else if ("Prompts".equals(title)) showFeaturePanel(title, "Save reusable prompts here. Prompt storage is not yet connected.");
            else if ("Education".equals(title)) showFeaturePanel(title, "Study mode, quizzes, and learning projects are planned for ARIA.");
            else if ("Create Android App".equals(title)) showFeaturePanel(title, "Use ARIA to plan Android app screens, architecture, and implementation steps.");
            else showFeaturePanel(title, description);
        });
    }

    private void showFeaturePanel(String title, String message) {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(8), dp(18), dp(8));
        TextView icon = label("✦", 24, ACCENT, true);
        icon.setPadding(0, 0, 0, dp(12));
        content.addView(icon);
        TextView body = label(message, 14, MUTED, false);
        body.setLineSpacing(dp(4), 1f);
        content.addView(body);
        dialogBuilder().setTitle(title).setView(content)
                .setPositiveButton("Done", null)
                .setNeutralButton("Explore ARIA features", (d, w) -> showFeatureDirectory())
                .show();
    }

    private void showHistorySearch() {
        EditText query = new EditText(this);
        query.setSingleLine(true);
        query.setTextColor(TEXT);
        query.setHintTextColor(MUTED);
        query.setHint("Search chats and messages");
        query.setPadding(dp(12), dp(8), dp(12), dp(8));
        query.setBackground(glassBackground());
        dialogBuilder().setTitle("Search chats").setView(query)
                .setPositiveButton("Search", (d, w) -> {
                    String q = query.getText().toString().trim();
                    if (q.isEmpty()) toast("Enter a search term.");
                    else showSearchResults(q);
                })
                .setNegativeButton("Cancel", null).show();
    }


    // Owner-only sign-in: the Telegram ID is fixed to the owner, while the secret is
    // validated by the backend. The secret itself is never stored on the device.
    private void buildSignInUi() {
        // Backend endpoint is an internal app configuration, never displayed in the UI.
        serverInput = new EditText(this);
        serverInput.setSingleLine(true);
        serverInput.setText(DEFAULT_SERVER);
        showSignInUi();
    }

    private String backendBaseUrl() {
        return DEFAULT_SERVER.replaceAll("/+$", "");
    }

    private String getOrCreateDeviceId() {
        android.content.SharedPreferences prefs = getSharedPreferences("aria_device", MODE_PRIVATE);
        String id = prefs.getString("device_id", "");
        if (id == null || id.trim().isEmpty()) {
            id = java.util.UUID.randomUUID().toString();
            prefs.edit().putString("device_id", id).apply();
        }
        return id;
    }

    private void showSignInUi() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(dp(26), dp(24), dp(26), dp(24));
        root.setBackgroundColor(BG);
        TextView logo = label("✦", 34, Color.WHITE, true);
        logo.setGravity(Gravity.CENTER);
        logo.setBackground(glassAccent());
        LinearLayout.LayoutParams logoP = new LinearLayout.LayoutParams(dp(72), dp(72));
        logoP.bottomMargin = dp(22);
        root.addView(logo, logoP);
        TextView title = label("Private ARIA", 27, TEXT, true);
        title.setGravity(Gravity.CENTER);
        root.addView(title);
        TextView subtitle = label("Sign in with the owner credentials to access your private assistant.", 14, MUTED, false);
        subtitle.setGravity(Gravity.CENTER);
        subtitle.setPadding(0, dp(10), 0, dp(22));
        root.addView(subtitle);
        EditText telegramId = new EditText(this);
        telegramId.setSingleLine(true);
        telegramId.setText("7204704497");
        telegramId.setHint("Owner Telegram ID");
        telegramId.setTextColor(TEXT);
        telegramId.setHintTextColor(MUTED);
        telegramId.setEnabled(false);
        telegramId.setPadding(dp(16), dp(12), dp(16), dp(12));
        telegramId.setBackground(glassBackground());
        root.addView(telegramId, new LinearLayout.LayoutParams(-1, -2));
        EditText secret = new EditText(this);
        secret.setSingleLine(true);
        secret.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        secret.setHint("Private sign-in secret");
        secret.setTextColor(TEXT);
        secret.setHintTextColor(MUTED);
        secret.setPadding(dp(16), dp(12), dp(16), dp(12));
        secret.setBackground(glassBackground());
        LinearLayout.LayoutParams secretP = new LinearLayout.LayoutParams(-1, -2);
        secretP.topMargin = dp(12);
        root.addView(secret, secretP);
        Button signIn = new Button(this);
        signIn.setText("Sign in securely");
        signIn.setAllCaps(false);
        signIn.setTextColor(Color.WHITE);
        signIn.setBackground(glassAccent());
        LinearLayout.LayoutParams signP = new LinearLayout.LayoutParams(-1, dp(52));
        signP.topMargin = dp(18);
        root.addView(signIn, signP);
        TextView privacy = label("Only the server can authorize access. The Telegram ID alone is not a password.", 11, MUTED, false);
        privacy.setGravity(Gravity.CENTER);
        privacy.setPadding(0, dp(16), 0, 0);
        root.addView(privacy);
        setContentView(root);
        signIn.setOnClickListener(v -> {
            String base = backendBaseUrl();
            String ownerId = telegramId.getText().toString().trim();
            String password = secret.getText().toString();
            if (password.isEmpty()) {
                toast("Enter your private app password.");
                return;
            }
            signIn.setEnabled(false);
            signIn.setText("Signing in…");
            executor.execute(() -> {
                String token = "";
                String error = "Sign-in failed. Check your credentials and backend configuration.";
                try {
                    HttpURLConnection conn = (HttpURLConnection)new URL(base + "/app/login").openConnection();
                    conn.setRequestMethod("POST");
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(20000);
                    conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    conn.setDoOutput(true);
                    JSONObject body = new JSONObject();
                    body.put("telegram_id", ownerId);
                    body.put("secret", password);
                    body.put("device_id", getOrCreateDeviceId());
                    try (OutputStream os = conn.getOutputStream()) { os.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                    int status = conn.getResponseCode();
                    InputStream stream = status >= 200 && status < 300 ? conn.getInputStream() : conn.getErrorStream();
                    StringBuilder response = new StringBuilder();
                    if (stream != null) try (BufferedReader r = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) { String line; while ((line = r.readLine()) != null) response.append(line); }
                    if (status >= 200 && status < 300) token = new JSONObject(response.toString()).optString("access_token", "");
                    else error = "Sign-in rejected by backend (HTTP " + status + "). Confirm the owner secrets are configured.";
                    conn.disconnect();
                } catch (Exception ex) { error = "Cannot reach the sign-in endpoint. Confirm backend deployment and HTTPS URL."; }
                final String tokenResult = token;
                final String errorResult = error;
                runOnUiThread(() -> {
                    signIn.setEnabled(true);
                    signIn.setText("Sign in securely");
                    if (tokenResult.isEmpty()) { toast(errorResult); return; }
                    getSharedPreferences("aria_auth", MODE_PRIVATE).edit().putString("access_token", tokenResult).apply();
                    recreate();
                });
            });
        });
    }

    private void signOut() {
        getSharedPreferences("aria_auth", MODE_PRIVATE).edit().clear().apply();
        toast("Signed out");
        recreate();
    }

    private Set<String> getProjectNames() {
        LinkedHashSet<String> result = new LinkedHashSet<>();
        String raw = getSharedPreferences(CHAT_PREFS, MODE_PRIVATE).getString("projects_json", "[]");
        try {
            JSONArray a = new JSONArray(raw);
            for (int i=0;i<a.length();i++) {
                String name = a.optString(i, "").trim();
                if (!name.isEmpty()) result.add(name);
            }
        } catch (Exception ignored) {}
        for (ChatRecord c : chatHistory) if (c.projectName != null && !c.projectName.trim().isEmpty()) result.add(c.projectName.trim());
        return result;
    }

    private void saveProjectNames(Set<String> projects) {
        JSONArray a = new JSONArray();
        for (String project : projects) a.put(project);
        getSharedPreferences(CHAT_PREFS, MODE_PRIVATE).edit().putString("projects_json", a.toString()).apply();
    }

    private void showProjects() {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(8), dp(4), dp(8), dp(4));
        Set<String> projects = getProjectNames();
        if (projects.isEmpty()) content.addView(label("No projects yet. Create one to organize chats.", 13, MUTED, false));
        for (String project : projects) {
            TextView row = label("▱   " + project, 14, TEXT, false);
            row.setPadding(dp(12), dp(12), dp(12), dp(12));
            row.setBackground(glassBackground());
            LinearLayout.LayoutParams rp = new LinearLayout.LayoutParams(-1, -2);
            rp.bottomMargin = dp(7);
            content.addView(row, rp);
            row.setOnClickListener(v -> showProjectChats(project));
        }
        dialogBuilder().setTitle("Projects").setView(content)
                .setNeutralButton("Create project", (d,w) -> promptCreateProject(null))
                .setPositiveButton("Done", null).show();
    }

    private void promptCreateProject(ChatRecord chat) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true);
        edit.setHint("Project name");
        edit.setTextColor(TEXT);
        edit.setHintTextColor(MUTED);
        edit.setBackground(glassBackground());
        edit.setPadding(dp(12), dp(10), dp(12), dp(10));
        dialogBuilder().setTitle("Create project").setView(edit)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Create", (d,w) -> {
                    String name = edit.getText().toString().trim();
                    if (name.isEmpty()) { toast("Enter a project name."); return; }
                    Set<String> projects = getProjectNames();
                    projects.add(name);
                    saveProjectNames(projects);
                    if (chat != null) { chat.projectName = name; chat.updatedAt = System.currentTimeMillis(); saveChatHistory(); }
                    toast("Project created");
                }).show();
    }

    private void showAddToProject(ChatRecord chat) {
        ArrayList<String> projects = new ArrayList<>(getProjectNames());
        ArrayList<String> options = new ArrayList<>(projects);
        options.add("＋ Create new project");
        options.add("Remove from project");
        String[] names = options.toArray(new String[0]);
        dialogBuilder().setTitle("Add to project").setItems(names, (d,w) -> {
            if (w == projects.size()) promptCreateProject(chat);
            else if (w == projects.size()+1) { chat.projectName = ""; saveChatHistory(); toast("Removed from project"); }
            else { chat.projectName = projects.get(w); chat.archived = false; chat.updatedAt = System.currentTimeMillis(); saveChatHistory(); toast("Added to " + chat.projectName); }
        }).show();
    }

    private void showProjectChats(String project) {
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        int count = 0;
        for (ChatRecord c : chatHistory) if (project.equals(c.projectName) && !c.archived) {
            count++;
            TextView row = label(c.title, 14, TEXT, false);
            row.setPadding(dp(12), dp(12), dp(12), dp(12));
            list.addView(row);
            row.setOnClickListener(v -> { activeChatId = c.id; restoreActiveChat(); });
            row.setOnLongClickListener(v -> { showChatActions(c, row); return true; });
        }
        if (count == 0) list.addView(label("No chats in this project yet.", 13, MUTED, false));
        dialogBuilder().setTitle(project).setView(list).setPositiveButton("Done", null)
                .setNeutralButton("Rename project", (d,w) -> renameProject(project))
                .setNegativeButton("Delete project", (d,w) -> deleteProject(project)).show();
    }

    private void renameProject(String oldName) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true); edit.setText(oldName); edit.setSelectAllOnFocus(true);
        edit.setTextColor(TEXT); edit.setHintTextColor(MUTED); edit.setBackground(glassBackground());
        dialogBuilder().setTitle("Rename project").setView(edit).setNegativeButton("Cancel", null)
                .setPositiveButton("Save", (d,w) -> {
                    String name = edit.getText().toString().trim();
                    if (name.isEmpty()) { toast("Project name cannot be empty."); return; }
                    Set<String> projects = getProjectNames(); projects.remove(oldName); projects.add(name); saveProjectNames(projects);
                    for (ChatRecord c : chatHistory) if (oldName.equals(c.projectName)) c.projectName = name;
                    saveChatHistory(); toast("Project renamed");
                }).show();
    }

    private void deleteProject(String name) {
        dialogBuilder().setTitle("Delete project?")
                .setMessage("Chats will be kept. They will no longer belong to this project.")
                .setNegativeButton("Cancel", null).setPositiveButton("Delete", (d,w) -> {
                    Set<String> projects = getProjectNames(); projects.remove(name); saveProjectNames(projects);
                    for (ChatRecord c : chatHistory) if (name.equals(c.projectName)) c.projectName = "";
                    saveChatHistory(); toast("Project deleted");
                }).show();
    }

    private ChatRecord getActiveChat() {
        for (ChatRecord c : chatHistory) if (c.id.equals(activeChatId)) return c;
        return null;
    }
    private void loadChatHistory() {
        chatHistory.clear();
        String raw=getSharedPreferences(CHAT_PREFS,MODE_PRIVATE).getString(CHAT_LIST_KEY,"[]");
        try { JSONArray a=new JSONArray(raw); for(int i=0;i<a.length();i++){JSONObject o=a.optJSONObject(i);if(o!=null)chatHistory.add(ChatRecord.fromJson(o));} } catch(Exception ignored) {}
        // Remove only untouched auto-created drafts left by older builds. Never fabricate
        // sample chats, pinned items, or projects for a fresh install.
        for (int i = chatHistory.size() - 1; i >= 0; i--) {
            ChatRecord c = chatHistory.get(i);
            if (c.messages.length() == 0 && "New chat".equals(c.title)
                    && !c.pinned && !c.archived
                    && (c.projectName == null || c.projectName.trim().isEmpty())) {
                chatHistory.remove(i);
            }
        }
        Collections.sort(chatHistory,(x,y)->Long.compare(y.updatedAt,x.updatedAt));
        saveChatHistory();
    }
    private void saveChatHistory() {
        JSONArray a=new JSONArray(); for(ChatRecord c:chatHistory)try{a.put(c.toJson());}catch(Exception ignored){}
        getSharedPreferences(CHAT_PREFS,MODE_PRIVATE).edit().putString(CHAT_LIST_KEY,a.toString()).apply();
    }
    private ChatRecord createChatRecord() {
        ChatRecord c=new ChatRecord(java.util.UUID.randomUUID().toString(),"New chat");
        chatHistory.add(0,c); activeChatId=c.id; saveChatHistory(); return c;
    }
    private void newConversation() {
        // A blank draft is not saved as history. It becomes a real chat only when
        // the user sends the first message, preventing fabricated "New conversation" rows.
        activeChatId = "";
        transcript.removeAllViews();
        lastSources.clear();
        renderSources();
        addWelcome();
    }
    private void restoreActiveChat() {
        ChatRecord chat=getActiveChat(); transcript.removeAllViews(); lastSources.clear();
        if(chat==null || chat.messages.length()==0){addWelcome();renderSources();return;}
        loadingChat=true;
        for(int i=0;i<chat.messages.length();i++){
            JSONObject m=chat.messages.optJSONObject(i); if(m==null)continue;
            String role=m.optString("role",""), content=m.optString("content","");
            if("user".equals(role)) addUserMessageUi(content);
            else if("assistant".equals(role)){
                ArrayList<SourceItem> sources=new ArrayList<>(); JSONArray sa=m.optJSONArray("sources");
                if(sa!=null)for(int j=0;j<sa.length();j++){JSONObject so=sa.optJSONObject(j);if(so!=null)addSourceIfValid(sources,so.optString("title",""),so.optString("url",""));}
                addAssistantMessageUi(content,sources);
            }
        }
        loadingChat=false; renderSources(); scrollDown(transcriptScroll);
    }
    private void persistMessage(String role,String content,ArrayList<SourceItem> sources) {
        if(loadingChat)return; ChatRecord c=getActiveChat(); if(c==null)c=createChatRecord();
        try {
            JSONObject m=new JSONObject();m.put("role",role);m.put("content",content);JSONArray sa=new JSONArray();
            if(sources!=null)for(SourceItem source:sources){JSONObject so=new JSONObject();so.put("title",source.title);so.put("url",source.url);sa.put(so);}
            m.put("sources",sa);c.messages.put(m);
            if("New chat".equals(c.title)&&"user".equals(role)){c.title=content.replaceAll("\\s+"," ").trim();if(c.title.length()>36)c.title=c.title.substring(0,33)+"...";}
            c.updatedAt=System.currentTimeMillis();saveChatHistory();
        }catch(Exception ignored){}
    }
    private void addChatHistoryRow(LinearLayout panel,Dialog drawer,ChatRecord chat,boolean pinned) {
        LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(dp(10),dp(10),dp(8),dp(10));row.setBackground(round(Color.TRANSPARENT,10));
        TextView icon=label(pinned?"★":"◌",13,pinned?ACCENT:MUTED,false);row.addView(icon,new LinearLayout.LayoutParams(dp(24),-2));
        TextView name=label(chat.title,14,TEXT,false);name.setMaxLines(1);name.setEllipsize(android.text.TextUtils.TruncateAt.END);row.addView(name,new LinearLayout.LayoutParams(0,-2,1));
        TextView more=label("⋯",22,MUTED,true);more.setGravity(Gravity.CENTER);row.addView(more,new LinearLayout.LayoutParams(dp(32),dp(34)));
        panel.addView(row,new LinearLayout.LayoutParams(-1,-2));
        row.setOnClickListener(v->{drawer.dismiss();if(chat.archived){showChatActions(chat, item);}else{activeChatId=chat.id;restoreActiveChat();}});
        more.setOnClickListener(v -> showChatActions(chat, more));row.setOnLongClickListener(v -> { showChatActions(chat, row); return true; });
    }
    private void showChatActions(ChatRecord chat, View anchor) {
        String[] actions = new String[]{
            chat.pinned ? "★  Unpin chat" : "☆  Pin chat",
            "✎  Rename chat",
            "▦  Add to project",
            chat.archived ? "↩  Unarchive" : "▣  Archive chat",
            "⌫  Delete chat"
        };
        showAnchoredMenu(anchor, chat.title, actions, index -> {
            if (index == 0) {
                chat.pinned = !chat.pinned; chat.updatedAt = System.currentTimeMillis(); saveChatHistory();
                toast(chat.pinned ? "Chat pinned" : "Chat unpinned");
                if (chat.pinned) showSideDrawer();
            } else if (index == 1) renameChat(chat);
            else if (index == 2) showAddToProject(chat);
            else if (index == 3) {
                chat.archived = !chat.archived; if (chat.archived) chat.pinned = false;
                chat.updatedAt = System.currentTimeMillis(); saveChatHistory();
                if (chat.archived && chat.id.equals(activeChatId)) newConversation();
                toast(chat.archived ? "Chat archived" : "Chat restored");
                showSideDrawer();
            } else if (index == 4) deleteChat(chat);
        });
    }

    private void renameChat(ChatRecord chat) {
        EditText edit=new EditText(this);edit.setSingleLine(true);edit.setText(chat.title);edit.setTextColor(TEXT);edit.setHintTextColor(MUTED);edit.setSelectAllOnFocus(true);edit.setBackground(glassBackground());edit.setPadding(dp(12),dp(10),dp(12),dp(10));
        dialogBuilder().setTitle("Rename chat").setView(edit).setNegativeButton("Cancel",null).setPositiveButton("Save",(d,w)->{
            String title=edit.getText().toString().trim();if(title.isEmpty()){toast("Chat name cannot be empty.");return;}
            chat.title=title;chat.updatedAt=System.currentTimeMillis();saveChatHistory();toast("Chat renamed");
        }).show();
    }
    private void deleteChat(ChatRecord chat) {
        dialogBuilder().setTitle("Delete chat?").setMessage("This removes the conversation from this device.")
            .setNegativeButton("Cancel",null).setPositiveButton("Delete",(d,w)->{
                chatHistory.remove(chat);saveChatHistory();
                if(chat.id.equals(activeChatId)){activeChatId=chatHistory.isEmpty()?"":chatHistory.get(0).id;restoreActiveChat();}
                toast("Chat deleted");
            }).show();
    }
    private void showSearchResults(String query) {
        LinearLayout results=new LinearLayout(this);results.setOrientation(LinearLayout.VERTICAL);ScrollView scroll=new ScrollView(this);scroll.addView(results);int count=0;
        String q=query.toLowerCase(java.util.Locale.ROOT);
        for(ChatRecord chat:chatHistory){
            boolean match=chat.title.toLowerCase(java.util.Locale.ROOT).contains(q);
            for(int i=0;!match&&i<chat.messages.length();i++){JSONObject m=chat.messages.optJSONObject(i);match=m!=null&&m.optString("content","").toLowerCase(java.util.Locale.ROOT).contains(q);}
            if(match){count++;TextView item=label((chat.archived?"▣  ":chat.pinned?"★  ":"")+chat.title,14,TEXT,false);item.setPadding(dp(12),dp(12),dp(12),dp(12));results.addView(item);item.setOnClickListener(v->{if(chat.archived){showChatActions(chat, item);}else{activeChatId=chat.id;restoreActiveChat();}});}
        }
        if(count==0)results.addView(label("No matching conversations",13,MUTED,false));
        dialogBuilder().setTitle("Search results").setView(scroll).setPositiveButton("Done",null).show();
    }

    private void addWelcome() {
        LinearLayout welcome = new LinearLayout(this); welcome.setOrientation(LinearLayout.VERTICAL); welcome.setGravity(Gravity.CENTER); welcome.setPadding(dp(10), dp(20), dp(10), dp(24));
        TextView icon = label("✦", 32, Color.WHITE, true); icon.setGravity(Gravity.CENTER); icon.setBackground(glassAccent());
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(dp(58), dp(58)); ip.bottomMargin = dp(18); welcome.addView(icon, ip);
        TextView heading = label("What can I help with?", 26, TEXT, true); heading.setGravity(Gravity.CENTER); welcome.addView(heading);
        TextView sub = label("Ask anything, explore an idea, or work through a problem.", 15, MUTED, false); sub.setGravity(Gravity.CENTER); sub.setPadding(dp(16), dp(9), dp(16), dp(18)); welcome.addView(sub);
        LinearLayout suggestions = new LinearLayout(this); suggestions.setOrientation(LinearLayout.VERTICAL);
        String[] prompts = {"Explain something clearly", "Help me write or improve code", "Explore an idea with me"};
        for (String prompt : prompts) { TextView item = label("✧    " + prompt, 14, TEXT, false); item.setPadding(dp(16), dp(15), dp(16), dp(15)); item.setBackground(glassBackground()); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.bottomMargin = dp(8); suggestions.addView(item,p); item.setOnClickListener(v -> { input.setText(prompt); input.setSelection(input.length()); input.requestFocus(); }); }
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
            .setNegativeButton("Sign out", (d, w) -> signOut())
            .setPositiveButton("Done", null).show();
    }

    private void showSettings() {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(8), dp(20), dp(4));
        TextView title = label("Privacy & security", 15, TEXT, true);
        content.addView(title);
        TextView description = label("Your ARIA connection is managed securely in the app. The server address is not displayed here.", 12, MUTED, false);
        description.setPadding(0, dp(6), 0, dp(14));
        content.addView(description);
        Button changePassword = new Button(this);
        changePassword.setText("Change app password");
        changePassword.setAllCaps(false);
        changePassword.setTextColor(Color.WHITE);
        changePassword.setBackground(glassAccent());
        content.addView(changePassword, new LinearLayout.LayoutParams(-1, dp(48)));
        changePassword.setOnClickListener(v -> showChangePassword());
        dialogBuilder().setTitle("Settings").setView(content)
                .setNegativeButton("Close", null)
                .setNeutralButton("Sign out", (d, w) -> signOut())
                .show();
    }

    private void showChangePassword() {
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(6), dp(18), dp(4));
        EditText current = new EditText(this);
        current.setSingleLine(true);
        current.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        current.setHint("Current password");
        current.setTextColor(TEXT); current.setHintTextColor(MUTED); current.setPadding(dp(14), dp(10), dp(14), dp(10)); current.setBackground(glassBackground());
        content.addView(current, new LinearLayout.LayoutParams(-1, -2));
        EditText next = new EditText(this);
        next.setSingleLine(true);
        next.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        next.setHint("New password (your choice)");
        next.setTextColor(TEXT); next.setHintTextColor(MUTED); next.setPadding(dp(14), dp(10), dp(14), dp(10)); next.setBackground(glassBackground());
        LinearLayout.LayoutParams nextP = new LinearLayout.LayoutParams(-1, -2); nextP.topMargin = dp(10); content.addView(next, nextP);
        EditText confirm = new EditText(this);
        confirm.setSingleLine(true);
        confirm.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        confirm.setHint("Confirm new password");
        confirm.setTextColor(TEXT); confirm.setHintTextColor(MUTED); confirm.setPadding(dp(14), dp(10), dp(14), dp(10)); confirm.setBackground(glassBackground());
        LinearLayout.LayoutParams confirmP = new LinearLayout.LayoutParams(-1, -2); confirmP.topMargin = dp(10); content.addView(confirm, confirmP);
        TextView warning = label("Choose a unique password. Very short passwords are easier to guess.", 11, MUTED, false);
        warning.setPadding(0, dp(10), 0, 0); content.addView(warning);
        dialogBuilder().setTitle("Change app password").setView(content)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Update password", (d, w) -> {
                    String oldPassword = current.getText().toString();
                    String newPassword = next.getText().toString();
                    String confirmPassword = confirm.getText().toString();
                    if (oldPassword.isEmpty() || newPassword.isEmpty()) { toast("Enter your current and new passwords."); return; }
                    if (!newPassword.equals(confirmPassword)) { toast("New passwords do not match."); return; }
                    changePasswordRequest(oldPassword, newPassword);
                }).show();
    }

    private void changePasswordRequest(String currentPassword, String newPassword) {
        executor.execute(() -> {
            String error = "Password could not be changed. Please try again.";
            boolean success = false;
            HttpURLConnection conn = null;
            try {
                conn = (HttpURLConnection) new URL(backendBaseUrl() + "/app/change-password").openConnection();
                conn.setRequestMethod("POST"); conn.setConnectTimeout(15000); conn.setReadTimeout(20000);
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                String accessToken = getSharedPreferences("aria_auth", MODE_PRIVATE).getString("access_token", "");
                if (!accessToken.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + accessToken);
                conn.setDoOutput(true);
                JSONObject body = new JSONObject(); body.put("current_password", currentPassword); body.put("new_password", newPassword);
                try (OutputStream os = conn.getOutputStream()) { os.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
                int status = conn.getResponseCode();
                InputStream stream = status >= 200 && status < 300 ? conn.getInputStream() : conn.getErrorStream();
                StringBuilder response = new StringBuilder();
                if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) { String line; while ((line = reader.readLine()) != null) response.append(line); }
                success = status >= 200 && status < 300;
                if (!success) {
                    try { error = new JSONObject(response.toString()).optString("detail", error); } catch (Exception ignored) { }
                }
            } catch (Exception ignored) { error = "Could not reach ARIA securely. Check your connection and try again."; }
            finally { if (conn != null) conn.disconnect(); }
            final boolean changed = success; final String message = error;
            runOnUiThread(() -> {
                if (changed) {
                    // Password change increments the backend token version, so all devices sign in again.
                    getSharedPreferences("aria_auth", MODE_PRIVATE).edit().clear().apply();
                    toast("Password changed. Sign in again with your new password.");
                    recreate();
                } else toast(message);
            });
        });
    }

    private void showHistory() {
        showSideDrawer();
    }

    private void showAttachmentMenu(View anchor) {
        String[] items = {"＋  Add photos & files", "▧  Take a photo", "♬  Voice input"};
        showAnchoredMenu(anchor, "Add to ARIA", items, index -> {
            if (index == 0) launchFilePicker();
            else if (index == 1) toast("Camera input needs a camera permission and image-analysis endpoint; it is not connected yet.");
            else if (index == 2) startVoiceInput();
        });
    }

    private interface MenuAction { void onSelect(int index); }

    /** Compact, anchor-relative glass menu: it follows the control instead of opening a centered dialog. */
    private void showAnchoredMenu(View anchor, String title, String[] items, MenuAction action) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(7), dp(8), dp(7), dp(8));
        card.setBackground(glassDialogBackground());
        card.setElevation(dp(18));
        TextView heading = label(title, 12, MUTED, true);
        heading.setPadding(dp(11), dp(7), dp(11), dp(9));
        heading.setMaxLines(1);
        card.addView(heading, new LinearLayout.LayoutParams(-1, -2));
        PopupWindow popup = new PopupWindow(card, dp(248), -2, true);
        popup.setBackgroundDrawable(round(Color.TRANSPARENT, 22));
        popup.setOutsideTouchable(true);
        popup.setElevation(dp(18));
        for (int i = 0; i < items.length; i++) {
            final int index = i;
            TextView item = label(items[i], 14, TEXT, false);
            item.setGravity(Gravity.CENTER_VERTICAL);
            item.setPadding(dp(12), dp(12), dp(12), dp(12));
            item.setBackground(round(Color.TRANSPARENT, 12));
            card.addView(item, new LinearLayout.LayoutParams(-1, -2));
            item.setOnClickListener(v -> { popup.dismiss(); action.onSelect(index); });
            item.setOnTouchListener((v, event) -> {
                if (event.getAction() == android.view.MotionEvent.ACTION_DOWN) v.setBackground(round(Color.argb(55, 170, 190, 255), 12));
                else if (event.getAction() == android.view.MotionEvent.ACTION_UP || event.getAction() == android.view.MotionEvent.ACTION_CANCEL) v.setBackground(round(Color.TRANSPARENT, 12));
                return false;
            });
        }
        int[] loc = new int[2]; anchor.getLocationOnScreen(loc);
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int x = Math.max(dp(8), Math.min(loc[0], screenWidth - dp(256)));
        // Measure first so the menu can open above the composer or below a sidebar row as space allows.
        card.measure(View.MeasureSpec.makeMeasureSpec(dp(248), View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
        int popupHeight = card.getMeasuredHeight();
        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        int y;
        if (loc[1] + anchor.getHeight() + popupHeight + dp(12) < screenHeight - dp(28)) {
            y = loc[1] + anchor.getHeight() + dp(6);
        } else {
            y = Math.max(dp(28), loc[1] - popupHeight - dp(6));
        }
        popup.setWidth(dp(248));
        popup.setHeight(-2);
        popup.showAtLocation(root, Gravity.TOP | Gravity.LEFT, x, y);
    }

    private void launchFilePicker() {
        try {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("*/*"); intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            startActivityForResult(intent, 7402);
        } catch (Exception e) { toast("File picker could not be opened."); }
    }

    private void startVoiceInput() {
        try {
            Intent intent = new Intent("android.speech.action.RECOGNIZE_SPEECH");
            intent.putExtra("android.speech.extra.LANGUAGE_MODEL", "free_form");
            intent.putExtra("android.speech.extra.PROMPT", "Speak to ARIA");
            startActivityForResult(intent, 7403);
        } catch (Exception e) { toast("Voice input is unavailable on this device."); }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null) return;
        if (requestCode == 7402) {
            ArrayList<Uri> selected = new ArrayList<>();
            if (data.getClipData() != null) {
                for (int i = 0; i < data.getClipData().getItemCount(); i++) selected.add(data.getClipData().getItemAt(i).getUri());
            } else if (data.getData() != null) selected.add(data.getData());
            if (!selected.isEmpty()) {
                StringBuilder names = new StringBuilder("Selected file(s): ");
                for (int i = 0; i < selected.size(); i++) { if (i > 0) names.append(", "); names.append(selected.get(i).getLastPathSegment()); }
                if (input != null) { String old = input.getText().toString().trim(); input.setText(old.isEmpty() ? names.toString() : old + "\n" + names); input.setSelection(input.length()); }
                toast("Files selected. ARIA's current backend does not yet upload/analyze their contents.");
            }
        } else if (requestCode == 7403) {
            ArrayList<String> results = data.getStringArrayListExtra("android.speech.extra.RESULTS");
            if (results != null && !results.isEmpty() && input != null) { input.setText(results.get(0)); input.setSelection(input.length()); }
        }
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
        final String base = backendBaseUrl();
        if (message.isEmpty()) return;
        input.setText(""); ((InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(input.getWindowToken(), 0);
        showTab(false); addUserMessage(message); setThinking(true); sendButton.setEnabled(false); sendButton.setAlpha(0.55f);
        executor.execute(() -> {
            String reply; ArrayList<SourceItem> sources = new ArrayList<>();
            try {
                HttpURLConnection conn = (HttpURLConnection)new URL(base + "/chat").openConnection();
                conn.setRequestMethod("POST"); conn.setConnectTimeout(30000); conn.setReadTimeout(180000); conn.setRequestProperty("Accept", "application/json"); conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                String accessToken = getSharedPreferences("aria_auth", MODE_PRIVATE).getString("access_token", "");
                if (!accessToken.isEmpty()) conn.setRequestProperty("Authorization", "Bearer " + accessToken);
                conn.setDoOutput(true);
                JSONObject payload = new JSONObject(); payload.put("message", message); payload.put("session_id", activeChatId.isEmpty() ? "android-default" : activeChatId);
                try (OutputStream os = conn.getOutputStream()) { os.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
                int code = conn.getResponseCode(); InputStream stream = code >= 200 && code < 400 ? conn.getInputStream() : conn.getErrorStream(); StringBuilder body = new StringBuilder();
                if (stream != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) { String line; while ((line = reader.readLine()) != null) body.append(line).append('\n'); }
                if (code >= 200 && code < 300) {
                    JSONObject response = new JSONObject(body.toString()); reply = response.optString("reply", response.optString("answer", "")).trim(); if (reply.isEmpty()) reply = "The ARIA backend returned an empty response. Check the backend logs and try again.";
                    collectSources(response, sources); if (!response.optBoolean("success", true)) reply = "Request did not complete: " + reply;
                } else if (code == 401) {
                    reply = "Your ARIA sign-in has expired or is invalid. Please sign in again.";
                    runOnUiThread(() -> { getSharedPreferences("aria_auth", MODE_PRIVATE).edit().remove("access_token").apply(); showSignInUi(); });
                } else { String detail = body.toString().trim(); if (detail.length() > 700) detail = detail.substring(0, 700); reply = "The ARIA server returned HTTP " + code + (detail.isEmpty() ? ". Please try again shortly." : ".\\n\\nServer detail: " + detail); }
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
        persistMessage("user", text, null);
        addUserMessageUi(text);
    }
    private void addUserMessageUi(String text) {
        LinearLayout wrap = new LinearLayout(this); wrap.setOrientation(LinearLayout.VERTICAL); wrap.setGravity(Gravity.END); wrap.setPadding(dp(32), dp(5), 0, dp(14));
        TextView body = label(text, 15, TEXT, false); body.setPadding(dp(15), dp(11), dp(15), dp(11)); body.setBackground(userBubbleBackground()); body.setMaxWidth(getResources().getDisplayMetrics().widthPixels - dp(76)); wrap.addView(body, new LinearLayout.LayoutParams(-2, -2));
        transcript.addView(wrap); scrollDown(transcriptScroll);
    }

    private void addAssistantMessage(String text, ArrayList<SourceItem> sources) {
        persistMessage("assistant", text, sources);
        addAssistantMessageUi(text, sources);
    }
    private void addAssistantMessageUi(String text, ArrayList<SourceItem> sources) {
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
            new int[]{Color.rgb(43, 52, 76), Color.rgb(24, 30, 47)});
        d.setCornerRadius(dp(22));
        d.setStroke(dp(1), Color.argb(145, 190, 210, 255));
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
}
