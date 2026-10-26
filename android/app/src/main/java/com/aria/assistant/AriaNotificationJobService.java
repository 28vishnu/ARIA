package com.aria.assistant;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.os.Build;
import android.os.PersistableBundle;
import android.Manifest;
import android.content.pm.PackageManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Periodically checks ARIA's authenticated alert inbox and posts Android local
 * notifications for new alerts. Android JobScheduler is intentionally used so
 * this works without adding an external dependency. The OS may defer jobs; this
 * is periodic background delivery, not instant push (FCM).
 */
public final class AriaNotificationJobService extends JobService {
    public static final int JOB_ID = 7402;
    private static final String BACKEND = "https://aria-ai-s5go.onrender.com";
    private static final String AUTH_PREFS = "aria_glass_auth";
    private static final String TOKEN_KEY = "access_token";
    private static final String STATE_PREFS = "aria_notification_state";
    private static final String LAST_ID_KEY = "last_alert_id";
    private static final String CHANNEL_ID = "aria_alerts";
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    public static void schedule(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) return;
        JobInfo.Builder builder = new JobInfo.Builder(JOB_ID,
                new ComponentName(context, AriaNotificationJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true);
        if (Build.VERSION.SDK_INT >= 26) builder.setRequiresBatteryNotLow(false);
        scheduler.schedule(builder.build());
    }

    public static void cancel(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler != null) scheduler.cancel(JOB_ID);
    }

    @Override public boolean onStartJob(JobParameters params) {
        executor.execute(() -> {
            try {
                checkAndNotify();
            } finally {
                jobFinished(params, false);
            }
        });
        return true;
    }

    private void checkAndNotify() {
        String token = getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).getString(TOKEN_KEY, "");
        if (token == null || token.trim().isEmpty()) return;
        try {
            android.content.SharedPreferences state = getSharedPreferences(STATE_PREFS, MODE_PRIVATE);
            long previous = state.getLong(LAST_ID_KEY, -1L);
            JSONObject response = getNotifications(token, previous);
            if (response.optInt("_http_status", 0) == 401) {
                getSharedPreferences(AUTH_PREFS, MODE_PRIVATE).edit().remove(TOKEN_KEY).apply();
                cancel(this);
                return;
            }
            if (response.optInt("_http_status", 0) < 200 || response.optInt("_http_status", 0) >= 300) return;
            JSONArray items = response.optJSONArray("items");
            if (items == null || items.length() == 0) return;
            long newest = previous;
            for (int i = 0; i < items.length(); i++) {
                JSONObject item = items.optJSONObject(i);
                if (item == null) continue;
                long id = item.optLong("id", 0L);
                if (id > newest) newest = id;
            }
            // First successful background check establishes a baseline so an
            // existing inbox does not trigger dozens of old notifications.
            if (previous < 0) {
                state.edit().putLong(LAST_ID_KEY, newest).apply();
                return;
            }
            ensureChannel();
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (manager == null) return;
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
            // Incremental endpoint returns unseen records oldest first.
            for (int i = 0; i < items.length(); i++) {
                JSONObject item = items.optJSONObject(i);
                if (item == null) continue;
                long id = item.optLong("id", 0L);
                if (id <= previous) continue;
                String title = item.optString("title", "ARIA update");
                String body = item.optString("body", "A new ARIA alert is available.");
                String severity = item.optString("severity", "info").toUpperCase();
                Intent launch = new Intent(this, AriaGlassActivity.class);
                launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                PendingIntent contentIntent = PendingIntent.getActivity(
                        this, (int) (id % Integer.MAX_VALUE), launch,
                        PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
                Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                        ? new Notification.Builder(this, CHANNEL_ID)
                        : new Notification.Builder(this);
                Notification notification = builder
                        .setSmallIcon(android.R.drawable.ic_dialog_info)
                        .setContentTitle("ARIA · " + title)
                        .setContentText(body.length() > 140 ? body.substring(0, 137) + "…" : body)
                        .setStyle(new Notification.BigTextStyle().bigText(body))
                        .setCategory("urgent".equalsIgnoreCase(severity) ? Notification.CATEGORY_ALARM : Notification.CATEGORY_STATUS)
                        .setContentIntent(contentIntent)
                        .setAutoCancel(true)
                        .setShowWhen(true)
                        .build();
                manager.notify((int) (id % Integer.MAX_VALUE), notification);
            }
            state.edit().putLong(LAST_ID_KEY, Math.max(previous, newest)).apply();
        } catch (Exception ignored) {
            // Transient network/backend errors are retried on the next job run.
        }
    }

    private JSONObject getNotifications(String token, long afterId) throws Exception {
        HttpURLConnection connection = null;
        try {
            String query = afterId < 0
                    ? "/app/notifications?limit=1"
                    : "/app/notifications?limit=100&after_id=" + afterId;
            connection = (HttpURLConnection) new URL(BACKEND + query).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(12000);
            connection.setReadTimeout(15000);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Authorization", "Bearer " + token);
            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 400 ? connection.getInputStream() : connection.getErrorStream();
            StringBuilder body = new StringBuilder();
            if (stream != null) {
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) body.append(line);
                }
            }
            JSONObject result = body.length() == 0 ? new JSONObject() : new JSONObject(body.toString());
            result.put("_http_status", status);
            return result;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null && manager.getNotificationChannel(CHANNEL_ID) == null) {
            manager.createNotificationChannel(new NotificationChannel(CHANNEL_ID, "ARIA alerts", NotificationManager.IMPORTANCE_DEFAULT));
        }
    }

    @Override public boolean onStopJob(JobParameters params) { return true; }

    @Override public void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
