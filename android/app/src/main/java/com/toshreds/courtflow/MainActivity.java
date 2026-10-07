package com.toshreds.courtflow;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** A real device WebView displays the genuine CAPTCHA using an already signed-in account. */
public class MainActivity extends Activity {
    private static final String COURTFLOW_ORIGIN = "https://to-shreds.github.io";
    private static final String COURTFLOW_URL = COURTFLOW_ORIGIN + "/PlayLoc/?native=1";
    private static final String SESSION_URL = "https://courtflow-playlocal.onrender.com/native-session";
    private static final String BRIDGE_SCRIPT = "(function(){if(window!==window.top||location.protocol!=='https:'||location.hostname!=='to-shreds.github.io'||location.pathname!=='/PlayLoc/')return;window.CourtFlowNative={apiVersion:function(){return 2;},startBooking:function(raw){CourtFlowNativeMessages.postMessage(JSON.stringify({action:'start',payload:raw}));},closeBooking:function(requestId){CourtFlowNativeMessages.postMessage(JSON.stringify({action:'close',requestId:requestId}));}};window.dispatchEvent(new Event('courtflow-native-ready'));})();";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final ArrayDeque<CookieBatch> cookieQueue = new ArrayDeque<>();
    private boolean cookieBusy;
    private boolean destroyed;
    private long generation;
    private WebView courtFlow;
    private Booking active;
    private String reservationScript;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try { reservationScript = readBounded(getAssets().open("reservation.js"), 131072); }
        catch (Exception e) { finish(); return; }
        courtFlow = new WebView(this);
        configureWebView(courtFlow);
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            WebViewCompat.addWebMessageListener(courtFlow, "CourtFlowNativeMessages", Collections.singleton(COURTFLOW_ORIGIN), (view, message, origin, mainFrame, reply) -> {
                if (!mainFrame || !("https".equals(origin.getScheme()) && "to-shreds.github.io".equals(origin.getHost()) && origin.getPort() == -1) || !trustedCourtFlow(view.getUrl())) return;
                try {
                    JSONObject data = new JSONObject(message.getData());
                    if ("start".equals(data.optString("action"))) startBooking(new JSONObject(data.getString("payload")));
                    else if ("close".equals(data.optString("action")) && active != null && active.requestId.equals(data.optString("requestId"))) closeBooking(active, "closed", "Reservation window closed.", true);
                } catch (Exception ignored) { }
            });
            if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) WebViewCompat.addDocumentStartJavaScript(courtFlow, BRIDGE_SCRIPT, Collections.singleton(COURTFLOW_ORIGIN));
        }
        courtFlow.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return request.isForMainFrame() && !trustedCourtFlow(request.getUrl().toString());
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (trustedCourtFlow(url) && WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) view.evaluateJavascript(BRIDGE_SCRIPT, null);
            }
        });
        setContentView(courtFlow);
        courtFlow.loadUrl(COURTFLOW_URL);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView(WebView view) {
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        // Keep the device's ordinary WebView user agent and browser APIs intact.
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, true);
        view.setWebChromeClient(new WebChromeClient());
    }

    private static boolean trustedCourtFlow(String value) {
        if (value == null) return false;
        Uri url = Uri.parse(value);
        return "https".equals(url.getScheme()) && "to-shreds.github.io".equals(url.getHost()) && url.getPort() == -1 && "/PlayLoc/".equals(url.getPath()) && url.getUserInfo() == null;
    }

    private static boolean playLocal(String value) {
        if (value == null) return false;
        Uri url = Uri.parse(value);
        return "https".equals(url.getScheme()) && ("www.playlocal.com".equals(url.getHost()) || "playlocal.com".equals(url.getHost())) && url.getPort() == -1 && url.getUserInfo() == null;
    }

    private boolean live(Booking booking) { return !destroyed && active == booking && !booking.closed && booking.generation == generation; }

    private void startBooking(JSONObject payload) {
        if (destroyed || !trustedCourtFlow(courtFlow.getUrl())) return;
        String ticket = payload.optString("ticket"), requestId = payload.optString("requestId");
        if (ticket.length() < 20 || ticket.length() > 8192 || !requestId.matches("[A-Za-z0-9_-]{1,100}")) return;
        // A page cannot replace an active request while its outcome is uncertain.
        if (active != null && !active.closed) {
            emitState(requestId, "failed", "Another reservation window is still active.", false);
            return;
        }
        Booking booking = new Booking(requestId, ++generation);
        active = booking;
        openDialog(booking);
        emitState(booking, "loading", "Signing in automatically using your saved account.");
        booking.fetch = executor.submit(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(SESSION_URL).openConnection();
                booking.connection = connection;
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(20000);
                connection.setReadTimeout(35000);
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setRequestProperty("Accept", "application/json");
                connection.setUseCaches(false);
                connection.setDoOutput(true);
                JSONObject request = new JSONObject(); request.put("ticket", ticket);
                byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                connection.getOutputStream().write(body);
                int status = connection.getResponseCode();
                JSONObject material = new JSONObject(readBounded(status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream(), 524288));
                if (status != 200 || !material.optBoolean("ok")) throw new Exception("The saved account could not be transferred. Retry automatic sign-in.");
                runOnUiThread(() -> installSession(booking, material));
            } catch (Exception ignored) {
                runOnUiThread(() -> { if (live(booking)) closeBooking(booking, "failed", "Automatic sign-in could not complete. Retry automatic sign-in.", true); });
            } finally { if (connection != null) connection.disconnect(); booking.connection = null; }
        });
    }

    private static String readBounded(InputStream stream, int limit) throws Exception {
        if (stream == null) throw new Exception("Missing response");
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) != -1) { if (output.size() + count > limit) throw new Exception("Response too large"); output.write(buffer, 0, count); }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }

    private void installSession(Booking booking, JSONObject material) {
        if (!live(booking)) return;
        try {
            booking.slot = material.getJSONObject("slot");
            booking.url = material.getString("reservationUrl");
            String facility = booking.slot.getString("facilityId");
            String court = booking.slot.getString("courtId");
            int start = booking.slot.getInt("start"), end = booking.slot.getInt("end");
            if (!facility.matches("\\d+") || !court.matches("\\d+") || !booking.slot.getString("date").matches("\\d{4}-\\d{2}-\\d{2}") || start < 0 || end <= start || end > 1440 || !playLocal(booking.url) || !Uri.parse(booking.url).getPath().matches("/facilities/[A-Za-z0-9_-]+/reservations/new")) throw new Exception("Unexpected reservation");
            JSONArray cookies = material.getJSONArray("cookies");
            if (cookies.length() == 0 || cookies.length() > 100) throw new Exception("Missing account session");
            List<CookieWrite> writes = new ArrayList<>();
            JSONArray descriptors = new JSONArray();
            for (int i = 0; i < cookies.length(); i++) {
                JSONObject cookie = cookies.getJSONObject(i);
                String name = cookie.getString("name"), value = cookie.getString("value"), domain = cookie.getString("domain"), path = cookie.optString("path", "/");
                String host = domain.startsWith(".") ? domain.substring(1) : domain;
                if (!(host.equals("playlocal.com") || host.equals("www.playlocal.com")) || !name.matches("[!#$%&'*+.^_`|~0-9A-Za-z-]+") || name.startsWith("cf_") || name.startsWith("__cf") || value.matches("(?s).*[;\\r\\n].*") || !path.startsWith("/") || path.matches("(?s).*[;\\r\\n].*") || !cookie.optBoolean("secure", false)) throw new Exception("Unexpected session cookie");
                String header = name + "=" + value + "; Domain=" + domain + "; Path=" + path + "; Secure" + (cookie.optBoolean("httpOnly") ? "; HttpOnly" : "") + "; SameSite=Lax";
                writes.add(new CookieWrite("https://" + host + path, header));
                JSONObject descriptor = new JSONObject(); descriptor.put("name", name); descriptor.put("domain", domain); descriptor.put("path", path); descriptors.put(descriptor);
            }
            setStatus(booking, "Opening " + booking.slot.optString("courtName", "your court") + ". Complete verification if PlayLocal asks.");
            List<CookieWrite> deletions = clearPlayLocalWrites(booking.url);
            enqueueCookies(deletions, booking, () -> {
                if (!live(booking)) return;
                // Save only identities, never cookie values, for precise cleanup after app restarts.
                getPreferences(MODE_PRIVATE).edit().putString("playlocal-cookie-identities", descriptors.toString()).apply();
                enqueueCookies(writes, booking, () -> { if (live(booking)) booking.view.loadUrl(booking.url); });
            });
        } catch (Exception ignored) { closeBooking(booking, "failed", "The automatic session transfer was rejected. Retry automatic sign-in.", true); }
    }

    private List<CookieWrite> clearPlayLocalWrites(String reservationUrl) {
        List<CookieWrite> writes = new ArrayList<>();
        Set<String> names = new LinkedHashSet<>();
        Set<String> paths = new LinkedHashSet<>(Arrays.asList("/", "/sign_in", "/activity", "/users"));
        List<String> urls = new ArrayList<>(Arrays.asList("https://www.playlocal.com/", "https://playlocal.com/", "https://www.playlocal.com/sign_in", "https://www.playlocal.com/activity"));
        if (playLocal(reservationUrl)) {
            urls.add(reservationUrl);
            String path = Uri.parse(reservationUrl).getPath();
            while (path != null && !path.isEmpty()) { paths.add(path); int index = path.lastIndexOf('/'); path = index > 0 ? path.substring(0, index) : ""; }
        }
        try {
            JSONArray previous = new JSONArray(getPreferences(MODE_PRIVATE).getString("playlocal-cookie-identities", "[]"));
            for (int i = 0; i < previous.length(); i++) {
                JSONObject cookie = previous.getJSONObject(i);
                names.add(cookie.getString("name")); paths.add(cookie.getString("path"));
            }
        } catch (Exception ignored) { }
        CookieManager manager = CookieManager.getInstance();
        for (String url : urls) {
            String header = manager.getCookie(url);
            if (header != null) for (String item : header.split(";")) { int equals = item.indexOf('='); if (equals > 0) names.add(item.substring(0, equals).trim()); }
        }
        for (String name : names) for (String path : paths) for (String host : Arrays.asList("playlocal.com", "www.playlocal.com")) {
            String expired = name + "=; Path=" + path + "; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; HttpOnly";
            writes.add(new CookieWrite("https://" + host + path, expired));
            for (String domain : Arrays.asList("playlocal.com", ".playlocal.com", "www.playlocal.com", ".www.playlocal.com")) writes.add(new CookieWrite("https://" + host + path, expired + "; Domain=" + domain));
        }
        return writes;
    }

    private void enqueueCookies(List<CookieWrite> writes, Booking owner, Runnable done) {
        cookieQueue.add(new CookieBatch(writes, owner, done));
        drainCookies();
    }
    private void drainCookies() {
        if (cookieBusy || cookieQueue.isEmpty()) return;
        cookieBusy = true;
        CookieBatch batch = cookieQueue.remove();
        if (batch.writes.isEmpty()) { cookieBusy = false; batch.done.run(); drainCookies(); return; }
        int[] remaining = { batch.writes.size() };
        boolean[] rejected = { false };
        for (CookieWrite write : batch.writes) CookieManager.getInstance().setCookie(write.url, write.header, accepted -> {
            if (!Boolean.TRUE.equals(accepted) && !write.header.contains("Max-Age=0")) rejected[0] = true;
            if (--remaining[0] == 0) {
                cookieBusy = false;
                if (rejected[0]) { if (batch.owner != null && live(batch.owner)) closeBooking(batch.owner, "failed", "PlayLocal rejected the transferred session cookies. Retry automatic sign-in.", true); }
                else batch.done.run();
                drainCookies();
            }
        });
    }

    private void openDialog(Booking booking) {
        booking.dialog = new Dialog(this, android.R.style.Theme_Material_Light_NoActionBar_Fullscreen);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.WHITE);
        LinearLayout header = new LinearLayout(this); header.setOrientation(LinearLayout.HORIZONTAL); header.setGravity(Gravity.CENTER_VERTICAL); header.setPadding(dp(14), dp(10), dp(8), dp(10));
        booking.status = new TextView(this); booking.status.setTextSize(16); booking.status.setTextColor(Color.rgb(21, 37, 29)); booking.status.setText("Signing in automatically…");
        header.addView(booking.status, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button close = new Button(this); close.setText("Close"); close.setAllCaps(false); close.setOnClickListener(v -> closeBooking(booking, "closed", "Reservation window closed.", true));
        header.addView(close); root.addView(header);
        booking.view = new WebView(this); configureWebView(booking.view);
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) WebViewCompat.addWebMessageListener(booking.view, "CourtFlowReservationSignal", new LinkedHashSet<>(Arrays.asList("https://www.playlocal.com", "https://playlocal.com")), (view, message, origin, mainFrame, reply) -> {
            if (!mainFrame || !live(booking) || !playLocal(view.getUrl())) return;
            try {
                JSONObject data = new JSONObject(message.getData());
                if (booking.requestId.equals(data.optString("requestId")) && "submitting".equals(data.optString("status"))) markSubmitted(booking);
            } catch (Exception ignored) { }
        });
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            String earlyGuard = "if(window===window.top){document.addEventListener('submit',function(event){const form=event.target;if(!form||form.tagName!=='FORM')return;let reservation=!!form.querySelector('[name=\"reservation[reservable_id]\"]');try{reservation=reservation||/\\/reservations\\/?$/.test(new URL(form.action,location.href).pathname);}catch(e){}if(!reservation)return;const guard=window.__courtflowReservationGuard;if(!guard||guard.requestId!==" + JSONObject.quote(booking.requestId) + "||guard.attempted||form.dataset.courtflowReservation!==" + JSONObject.quote(booking.requestId) + "){event.preventDefault();event.stopImmediatePropagation();}},true);}";
            WebViewCompat.addDocumentStartJavaScript(booking.view, earlyGuard, new LinkedHashSet<>(Arrays.asList("https://www.playlocal.com", "https://playlocal.com")));
        }
        booking.view.setWebViewClient(new BookingClient(booking));
        root.addView(booking.view, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        booking.dialog.setContentView(root);
        booking.dialog.setOnDismissListener(dialog -> { if (!booking.closed) closeBooking(booking, "closed", "Reservation window closed.", true); });
        booking.dialog.show();
        Window window = booking.dialog.getWindow(); if (window != null) window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        handler.postDelayed(() -> { if (live(booking) && !booking.submissionAttempted) closeBooking(booking, "timed-out", "Verification timed out. Retry automatic sign-in.", true); }, 300000);
    }

    private final class BookingClient extends WebViewClient {
        private final Booking booking;
        BookingClient(Booking booking) { this.booking = booking; }
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            // Preserve challenge iframe navigation, about:blank/srcdoc, and standard APIs.
            if (!request.isForMainFrame()) return false;
            return !allowedBookingNavigation(booking, request.getUrl().toString());
        }
        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            if (request.isForMainFrame() && "POST".equals(request.getMethod()) && formDestination(booking, request.getUrl().toString())) {
                runOnUiThread(() -> { if (live(booking)) markSubmitted(booking); });
            }
            return null;
        }
        @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
            booking.pageGeneration++;
            if (!live(booking)) return;
            if (!allowedBookingNavigation(booking, url)) { view.stopLoading(); closeBooking(booking, "failed", "PlayLocal opened an unexpected page.", true); }
            else if (booking.submissionAttempted && Uri.parse(url).getPath().equals(Uri.parse(booking.url).getPath())) { view.stopLoading(); closeBooking(booking, "failed", "PlayLocal returned to the form after submission. Checking Activity before any retry.", true); }
        }
        @Override public void onPageFinished(WebView view, String url) {
            if (!live(booking)) return;
            if (!allowedBookingNavigation(booking, url)) { closeBooking(booking, "failed", "PlayLocal opened an unexpected page.", true); return; }
            String path = Uri.parse(url).getPath();
            if ("/sign_in".equals(path) || "/users/sign_in".equals(path)) { closeBooking(booking, "authentication-rejected", "Refreshing the saved account's sign-in automatically.", true); return; }
            if (receiptPath(booking, path)) {
                if (booking.submissionAttempted) completeForActivityCheck(booking);
                else closeBooking(booking, "failed", "An existing reservation page opened. Check Activity.", true);
                return;
            }
            if (path.equals(Uri.parse(booking.url).getPath())) {
                long page = booking.pageGeneration;
                view.evaluateJavascript(reservationScript, ignored -> { if (live(booking) && page == booking.pageGeneration) {
                    try { view.evaluateJavascript("JSON.stringify(CourtFlowReservation.inspect(" + scriptRequest(booking) + "))", ignoredResult -> { if (live(booking) && page == booking.pageGeneration) poll(booking, page); }); }
                    catch (Exception ignoredException) { closeBooking(booking, "failed", "Could not inspect the reservation form.", true); }
                } });
            }
        }
        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame() && live(booking)) closeBooking(booking, "failed", "PlayLocal could not load. Check Activity before retrying.", true);
        }
        @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && response.getStatusCode() >= 400 && live(booking)) closeBooking(booking, "failed", "PlayLocal rejected the request. Check Activity before retrying.", true);
        }
    }

    private static boolean receiptPath(Booking booking, String path) {
        String prefix = Uri.parse(booking.url).getPath().replace("/reservations/new", "");
        return path != null && (path.matches("/reservations/\\d+(?:/(?:confirmation|receipt))?/?") || path.matches(java.util.regex.Pattern.quote(prefix) + "/reservations/\\d+(?:/(?:confirmation|receipt))?/?"));
    }
    private static boolean allowedBookingNavigation(Booking booking, String url) {
        if (!playLocal(url) || booking.url == null || booking.slot == null) return false;
        String path = Uri.parse(url).getPath();
        return path != null && (path.equals(Uri.parse(booking.url).getPath()) || path.equals("/sign_in") || path.equals("/users/sign_in") || receiptPath(booking, path) || (booking.submissionAttempted && formDestination(booking, url)));
    }

    private static boolean formDestination(Booking booking, String url) {
        if (!playLocal(url) || booking.url == null) return false;
        String path = Uri.parse(url).getPath();
        String expected = Uri.parse(booking.url).getPath().replace("/new", "");
        return expected.equals(path) || (expected + "/").equals(path) || "/reservations".equals(path) || "/reservations/".equals(path);
    }

    private JSONObject scriptRequest(Booking booking) throws Exception {
        JSONObject request = new JSONObject(); request.put("requestId", booking.requestId); request.put("slot", booking.slot); request.put("reservationUrl", booking.url); request.put("submissionAttempted", booking.submissionAttempted); return request;
    }
    private void poll(Booking booking, long page) {
        if (!live(booking) || page != booking.pageGeneration || booking.inspecting) return;
        if (booking.submissionAttempted) {
            if (SystemClock.elapsedRealtime() - booking.submittedAt > 45000) closeBooking(booking, "timed-out", "The reservation was submitted once but its outcome is unconfirmed. Checking Activity.", true);
            else handler.postDelayed(() -> poll(booking, page), 650);
            return;
        }
        try {
            booking.inspecting = true;
            booking.view.evaluateJavascript("JSON.stringify(CourtFlowReservation.inspect(" + scriptRequest(booking) + "))", value -> {
                booking.inspecting = false;
                if (!live(booking) || page != booking.pageGeneration) return;
                try {
                    Object decoded = new JSONTokener(value).nextValue();
                    JSONObject result = new JSONObject((String) decoded);
                    String status = result.optString("status"), message = result.optString("message");
                    setStatus(booking, message);
                    if ("failed".equals(status)) { closeBooking(booking, "failed", message, true); return; }
                    if ("submitted".equals(status)) markSubmitted(booking);
                    if ("ready".equals(status) && !booking.submissionAttempted) {
                        // Set the native latch before the single permitted click. Never reset it.
                        markSubmitted(booking);
                        booking.view.evaluateJavascript("JSON.stringify(CourtFlowReservation.submit(" + scriptRequest(booking) + "))", ignored -> { });
                    }
                    handler.postDelayed(() -> poll(booking, page), 650);
                } catch (Exception ignored) { closeBooking(booking, "failed", "The reservation form could not be inspected. Check Activity.", true); }
            });
        } catch (Exception ignored) { booking.inspecting = false; closeBooking(booking, "failed", "Could not prepare the exact reservation. Check Activity.", true); }
    }
    private void markSubmitted(Booking booking) {
        if (booking.submissionAttempted) return;
        booking.submissionAttempted = true; booking.submittedAt = SystemClock.elapsedRealtime();
        emitState(booking, "submitted", "Reservation submitted once. Checking Activity.");
        handler.postDelayed(() -> { if (live(booking)) closeBooking(booking, "timed-out", "The reservation was submitted once but its outcome is unconfirmed. Checking Activity.", true); }, 45000);
    }
    private void completeForActivityCheck(Booking booking) {
        String requestId = booking.requestId; boolean attempted = booking.submissionAttempted;
        // Destroy the owned dialog first, so the next queued request cannot be destroyed by this callback.
        closeBooking(booking, "submitted", "Checking the account's actual reservations.", false);
        try { JSONObject detail = new JSONObject(); detail.put("requestId", requestId); detail.put("submissionAttempted", attempted); dispatch("courtflow-native-booking-complete", detail); } catch (Exception ignored) { }
    }
    private void closeBooking(Booking booking, String status, String message, boolean notify) {
        if (booking.closed) return;
        booking.closed = true;
        if (booking.connection != null) booking.connection.disconnect();
        if (booking.fetch != null) booking.fetch.cancel(true);
        if (active == booking) { active = null; generation++; }
        if (booking.view != null) { booking.view.stopLoading(); booking.view.destroy(); booking.view = null; }
        if (booking.dialog != null && booking.dialog.isShowing()) booking.dialog.dismiss();
        if (booking.url != null) enqueueCookies(clearPlayLocalWrites(booking.url), null, () -> { });
        if (notify) emitState(booking, status, message);
    }
    private void setStatus(Booking booking, String message) { if (booking.status != null) booking.status.setText(message); }
    private void emitState(Booking booking, String status, String message) { setStatus(booking, message); emitState(booking.requestId, status, message, booking.submissionAttempted); }
    private void emitState(String requestId, String status, String message, boolean attempted) {
        try { JSONObject detail = new JSONObject(); detail.put("requestId", requestId); detail.put("status", status); detail.put("message", message); detail.put("submissionAttempted", attempted); dispatch("courtflow-native-booking-state", detail); } catch (Exception ignored) { }
    }
    private void dispatch(String event, JSONObject detail) {
        if (!destroyed && courtFlow != null && trustedCourtFlow(courtFlow.getUrl())) courtFlow.evaluateJavascript("window.dispatchEvent(new CustomEvent(" + JSONObject.quote(event) + ",{detail:" + detail + "}));", null);
    }
    @Override public void onBackPressed() {
        if (active != null) { closeBooking(active, "closed", "Reservation window closed.", true); return; }
        super.onBackPressed();
    }
    @Override protected void onDestroy() {
        if (active != null) closeBooking(active, "closed", "Reservation window closed.", true);
        destroyed = true; handler.removeCallbacksAndMessages(null); executor.shutdownNow();
        if (courtFlow != null) { courtFlow.stopLoading(); courtFlow.destroy(); courtFlow = null; }
        super.onDestroy();
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private static final class Booking {
        final String requestId; final long generation;
        boolean closed, submissionAttempted, inspecting;
        long submittedAt, pageGeneration;
        JSONObject slot; String url;
        Dialog dialog; WebView view; TextView status;
        volatile HttpURLConnection connection; Future<?> fetch;
        Booking(String requestId, long generation) { this.requestId = requestId; this.generation = generation; }
    }
    private static final class CookieWrite {
        final String url, header; CookieWrite(String url, String header) { this.url = url; this.header = header; }
    }
    private static final class CookieBatch {
        final List<CookieWrite> writes; final Booking owner; final Runnable done;
        CookieBatch(List<CookieWrite> writes, Booking owner, Runnable done) { this.writes = writes; this.owner = owner; this.done = done; }
    }
}
