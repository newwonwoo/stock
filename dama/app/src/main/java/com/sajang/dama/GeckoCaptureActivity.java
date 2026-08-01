package com.sajang.dama;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import org.json.JSONObject;
import org.mozilla.geckoview.GeckoResult;
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoView;
import org.mozilla.geckoview.WebExtension;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class GeckoCaptureActivity extends Activity {
    private static final String EXTENSION_URI = "resource://android/assets/dama_capture/";
    private static final String EXTENSION_ID = "dama-capture@sajang.local";
    private static final String NATIVE_APP = "dama.capture";
    private static final String FALLBACK_UA =
            "Mozilla/5.0 (Android 14; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0";

    private static GeckoRuntime runtime;

    private GeckoView geckoView;
    private GeckoSession session;
    private TextView statusView;
    private TextView detailView;
    private ProgressBar progressBar;
    private Spinner spinner;
    private Button downloadButton;
    private ArrayAdapter<String> adapter;
    private final Map<String, Candidate> candidates = new LinkedHashMap<>();
    private String originalPageUrl = "";

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        originalPageUrl = extractUrl(getIntent());
        if (originalPageUrl.isEmpty()) {
            Toast.makeText(this, "열 주소가 없습니다.", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }

        setContentView(buildUi());
        status("Gecko 안전 브라우저 준비 중", 2,
                "Android System WebView 대신 앱에 포함된 Gecko 엔진을 시작합니다.");

        try {
            if (runtime == null) {
                runtime = GeckoRuntime.create(getApplicationContext());
            }
            session = new GeckoSession();
            session.setContentDelegate(new GeckoSession.ContentDelegate() {});
            session.setProgressDelegate(new GeckoSession.ProgressDelegate() {
                @Override
                public void onPageStart(@NonNull GeckoSession session, @NonNull String url) {
                    runOnUiThread(() -> status("페이지 연결 중", 8, url));
                }

                @Override
                public void onProgressChange(@NonNull GeckoSession session, int progress) {
                    runOnUiThread(() -> status(
                            progress < 100 ? "페이지 로딩 중" : "재생 대기 중",
                            Math.max(8, Math.min(45, progress / 2)),
                            progress < 100
                                    ? "페이지를 불러오고 있습니다. " + progress + "%"
                                    : "페이지가 열렸습니다. 영상을 실제로 재생하세요."
                    ));
                }

                @Override
                public void onPageStop(@NonNull GeckoSession session, boolean success) {
                    runOnUiThread(() -> status(
                            success ? "재생 요청 감지 대기" : "페이지 로딩 실패",
                            success ? 45 : 100,
                            success
                                    ? "플레이어의 재생 버튼을 누르면 MP4 또는 비암호화 HLS 요청을 찾습니다."
                                    : "Gecko 엔진에서도 페이지를 열지 못했습니다."
                    ));
                }
            });
            session.open(runtime);
            geckoView.setSession(session);

            runtime.getWebExtensionController()
                    .ensureBuiltIn(EXTENSION_URI, EXTENSION_ID)
                    .accept(
                            extension -> {
                                extension.setMessageDelegate(
                                        new WebExtension.MessageDelegate() {
                                            @Override
                                            public GeckoResult<Object> onMessage(
                                                    @NonNull String nativeApp,
                                                    @NonNull Object message,
                                                    @NonNull WebExtension.MessageSender sender
                                            ) {
                                                if (NATIVE_APP.equals(nativeApp)) {
                                                    handleExtensionMessage(String.valueOf(message));
                                                }
                                                return null;
                                            }
                                        },
                                        NATIVE_APP
                                );
                                runOnUiThread(() -> {
                                    status("Gecko 안전 브라우저 연결 중", 5,
                                            "페이지가 열린 뒤 영상을 실제로 재생하세요.");
                                    session.loadUri(originalPageUrl);
                                });
                            },
                            error -> runOnUiThread(() -> status(
                                    "감지 모듈 시작 실패",
                                    100,
                                    error == null ? "내장 감지 확장을 시작하지 못했습니다."
                                            : error.getMessage()
                            ))
                    );
        } catch (Throwable error) {
            status("Gecko 엔진 시작 실패", 100,
                    error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    private View buildUi() {
        final int pad = dp(14);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("담아 · Gecko 안전 감지");
        title.setTextSize(22);
        title.setTextColor(Color.rgb(20, 36, 31));
        title.setTypeface(null, 1);
        root.addView(title, matchWrap());

        statusView = new TextView(this);
        statusView.setTextSize(17);
        statusView.setTextColor(Color.rgb(11, 102, 76));
        statusView.setPadding(0, dp(10), 0, dp(3));
        root.addView(statusView, matchWrap());

        detailView = new TextView(this);
        detailView.setTextSize(13);
        detailView.setTextColor(Color.DKGRAY);
        detailView.setMaxLines(3);
        root.addView(detailView, matchWrap());

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(7));
        progressParams.setMargins(0, dp(8), 0, dp(8));
        root.addView(progressBar, progressParams);

        geckoView = new GeckoView(this);
        LinearLayout.LayoutParams browserParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(geckoView, browserParams);

        spinner = new Spinner(this);
        adapter = new ArrayAdapter<>(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                new ArrayList<>()
        );
        spinner.setAdapter(adapter);
        LinearLayout.LayoutParams spinnerParams = matchWrap();
        spinnerParams.setMargins(0, dp(8), 0, dp(6));
        root.addView(spinner, spinnerParams);

        downloadButton = new Button(this);
        downloadButton.setText("감지된 영상 다운로드");
        downloadButton.setEnabled(false);
        downloadButton.setAllCaps(false);
        downloadButton.setGravity(Gravity.CENTER);
        downloadButton.setOnClickListener(v -> sendSelectedToMain());
        root.addView(downloadButton, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52)));

        return root;
    }

    private void handleExtensionMessage(String raw) {
        try {
            JSONObject json = new JSONObject(raw);
            String url = json.optString("url", "").trim();
            if (!isSupportedMedia(url)) return;
            String pageUrl = json.optString("pageUrl", "").trim();
            String title = json.optString("title", "").trim();
            String referer = json.optString("referer", "").trim();
            String origin = json.optString("origin", "").trim();
            String cookie = json.optString("cookie", "").trim();
            String userAgent = json.optString("userAgent", "").trim();
            if (referer.isEmpty()) referer = pageUrl.isEmpty() ? originalPageUrl : pageUrl;
            if (origin.isEmpty()) origin = originOf(referer);
            if (userAgent.isEmpty()) userAgent = FALLBACK_UA;
            if (title.isEmpty()) title = "감지된 영상";

            Candidate candidate = new Candidate(
                    url,
                    title,
                    url.toLowerCase(Locale.US).contains(".m3u8") ? "HLS" : "DIRECT",
                    referer,
                    origin,
                    cookie,
                    userAgent
            );
            runOnUiThread(() -> addCandidate(candidate));
        } catch (Throwable ignored) {
            // Invalid extension messages are ignored rather than crashing the browser process.
        }
    }

    private void addCandidate(Candidate candidate) {
        if (candidates.containsKey(candidate.url)) return;
        candidates.put(candidate.url, candidate);
        refreshCandidateLabels();
        spinner.setSelection(candidates.size() - 1);
        downloadButton.setEnabled(true);
        status("영상 요청 감지", 55,
                candidates.size() + "개 후보를 찾았습니다. 재생이 시작된 뒤 가장 최근 후보를 선택하세요.");
    }

    private void refreshCandidateLabels() {
        List<String> labels = new ArrayList<>();
        int index = 1;
        for (Candidate candidate : candidates.values()) {
            labels.add(index + ". " + candidate.type + " · " + shortUrl(candidate.url));
            index++;
        }
        adapter.clear();
        adapter.addAll(labels);
        adapter.notifyDataSetChanged();
    }

    private void sendSelectedToMain() {
        int position = spinner.getSelectedItemPosition();
        if (position < 0 || position >= candidates.size()) return;
        Candidate candidate = new ArrayList<>(candidates.values()).get(position);
        Intent intent = new Intent(this, MainActivity.class);
        intent.setAction(MainActivity.ACTION_CAPTURED_DOWNLOAD);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                Intent.FLAG_ACTIVITY_CLEAR_TOP |
                Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_URL, candidate.url);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_TITLE, candidate.title);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_TYPE, candidate.type);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_REFERER, candidate.referer);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_ORIGIN, candidate.origin);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_COOKIE, candidate.cookie);
        intent.putExtra(MainActivity.EXTRA_CAPTURED_USER_AGENT, candidate.userAgent);
        startActivity(intent);
        finish();
    }

    private void status(String title, int progress, String detail) {
        if (statusView == null) return;
        statusView.setText(title);
        progressBar.setProgress(Math.max(0, Math.min(100, progress)));
        detailView.setText(detail == null ? "" : detail);
    }

    private String extractUrl(Intent intent) {
        if (intent == null) return "";
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (text == null) text = "";
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("https?://\\S+", java.util.regex.Pattern.CASE_INSENSITIVE)
                .matcher(text.trim());
        return matcher.find() ? matcher.group() : text.trim();
    }

    private boolean isSupportedMedia(String url) {
        return url != null && url.matches("(?i)^https?://.+(?:\\.m3u8|\\.mp4|\\.webm|\\.mov|\\.m4v)(?:$|[?#].*)");
    }

    private String originOf(String url) {
        try {
            Uri uri = Uri.parse(url);
            if (uri.getScheme() == null || uri.getHost() == null) return "";
            int port = uri.getPort();
            return uri.getScheme() + "://" + uri.getHost() + (port > 0 ? ":" + port : "");
        } catch (Throwable ignored) {
            return "";
        }
    }

    private String shortUrl(String url) {
        if (url.length() <= 70) return url;
        return url.substring(0, 32) + "…" + url.substring(url.length() - 30);
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        if (session != null) {
            try {
                session.close();
            } catch (Throwable ignored) {
            }
        }
        super.onDestroy();
    }

    private static final class Candidate {
        final String url;
        final String title;
        final String type;
        final String referer;
        final String origin;
        final String cookie;
        final String userAgent;

        Candidate(
                String url,
                String title,
                String type,
                String referer,
                String origin,
                String cookie,
                String userAgent
        ) {
            this.url = url;
            this.title = title;
            this.type = type;
            this.referer = referer;
            this.origin = origin;
            this.cookie = cookie;
            this.userAgent = userAgent;
        }
    }
}
