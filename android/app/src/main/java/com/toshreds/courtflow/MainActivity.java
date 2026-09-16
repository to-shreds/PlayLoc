package com.toshreds.courtflow;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final String COURTFLOW_URL = "https://to-shreds.github.io/PlayLoc/?native=1";

    private WebView courtFlow;
    private Dialog bookingDialog;
    private WebView bookingWebView;
    private TextView bookingStatus;
    private BookingRequest activeBooking;
    private boolean loginSubmitted;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        courtFlow = new WebView(this);
        configureWebView(courtFlow);
        courtFlow.addJavascriptInterface(new CourtFlowNativeBridge(), "CourtFlowNative");
        courtFlow.setWebViewClient(new WebViewClient());
        setContentView(courtFlow);
        courtFlow.loadUrl(COURTFLOW_URL);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView(WebView webView) {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
        webView.setWebChromeClient(new WebChromeClient());
    }

    @Override
    public void onBackPressed() {
        if (bookingDialog != null && bookingDialog.isShowing()) {
            bookingDialog.dismiss();
            return;
        }
        if (courtFlow.canGoBack()) {
            courtFlow.goBack();
            return;
        }
        super.onBackPressed();
    }

    private final class CourtFlowNativeBridge {
        @JavascriptInterface
        public void startBooking(String rawJson) {
            try {
                JSONObject o = new JSONObject(rawJson);
                BookingRequest request = new BookingRequest(
                        o.optString("url"),
                        o.optString("accountName"),
                        o.optString("email"),
                        o.optString("password"),
                        o.optString("courtId"),
                        o.optString("courtName"),
                        o.optString("timeLabel")
                );
                if (!request.url.startsWith("https://www.playlocal.com/") &&
                        !request.url.startsWith("https://playlocal.com/")) {
                    nativeMessage("CourtFlow refused an unexpected booking URL.");
                    return;
                }
                runOnUiThread(() -> openBookingWebView(request));
            } catch (Exception e) {
                nativeMessage("Could not open the PlayLocal booking window: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void closeBooking() {
            runOnUiThread(() -> {
                if (bookingDialog != null) bookingDialog.dismiss();
            });
        }
    }

    private static final class BookingRequest {
        final String url;
        final String accountName;
        final String email;
        final String password;
        final String courtId;
        final String courtName;
        final String timeLabel;

        BookingRequest(String url, String accountName, String email, String password,
                       String courtId, String courtName, String timeLabel) {
            this.url = url;
            this.accountName = accountName;
            this.email = email;
            this.password = password;
            this.courtId = courtId;
            this.courtName = courtName;
            this.timeLabel = timeLabel;
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void openBookingWebView(BookingRequest request) {
        activeBooking = request;
        loginSubmitted = false;

        if (bookingDialog != null && bookingDialog.isShowing()) {
            bookingDialog.dismiss();
        }

        bookingDialog = new Dialog(this, android.R.style.Theme_Material_Light_NoActionBar_Fullscreen);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(14), dp(10), dp(8), dp(10));

        bookingStatus = new TextView(this);
        bookingStatus.setTextSize(16);
        bookingStatus.setTextColor(Color.rgb(21, 37, 29));
        bookingStatus.setText("Opening PlayLocal for " + request.accountName + " · " + request.courtName + " · " + request.timeLabel);
        header.addView(bookingStatus, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        Button close = new Button(this);
        close.setText("Close");
        close.setAllCaps(false);
        close.setOnClickListener(v -> bookingDialog.dismiss());
        header.addView(close, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(header, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        bookingWebView = new WebView(this);
        configureWebView(bookingWebView);
        bookingWebView.addJavascriptInterface(new BookingPageBridge(), "CourtFlowBookingNative");
        bookingWebView.setWebViewClient(new BookingClient());
        root.addView(bookingWebView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        bookingDialog.setContentView(root);
        Window window = bookingDialog.getWindow();
        if (window != null) {
            window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        }
        bookingDialog.setOnDismissListener(d -> {
            if (bookingWebView != null) {
                bookingWebView.stopLoading();
                bookingWebView.destroy();
                bookingWebView = null;
            }
        });
        bookingDialog.show();

        CookieManager cookies = CookieManager.getInstance();
        cookies.removeAllCookies(success -> {
            cookies.flush();
            runOnUiThread(() -> {
                if (bookingWebView != null) bookingWebView.loadUrl(request.url);
            });
        });
    }

    private final class BookingClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            return !url.startsWith("https://www.playlocal.com/") && !url.startsWith("https://playlocal.com/");
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            if (activeBooking == null) return;

            if (url.contains("/sign_in")) {
                if (!loginSubmitted) {
                    loginSubmitted = true;
                    setBookingStatus("Signing in as " + activeBooking.accountName + "…");
                    view.evaluateJavascript(loginScript(activeBooking), null);
                } else {
                    setBookingStatus("PlayLocal is still on the sign-in page. Check the credentials shown in CourtFlow.");
                }
                return;
            }

            if (url.matches("https://(www\\.)?playlocal\\.com/.*/reservations/\\d+.*") ||
                    url.matches("https://(www\\.)?playlocal\\.com/reservations/\\d+.*")) {
                bookingCompleted();
                return;
            }

            if (url.contains("/reservations/new")) {
                setBookingStatus("Selecting " + activeBooking.courtName + ". Complete PlayLocal verification if it asks.");
                view.evaluateJavascript(reservationScript(activeBooking), null);
                return;
            }

            if (loginSubmitted && url.startsWith("https://") && url.contains("playlocal.com")) {
                setBookingStatus("Signed in. Opening the exact reservation…");
                view.postDelayed(() -> {
                    if (bookingWebView != null) bookingWebView.loadUrl(activeBooking.url);
                }, 350);
            }
        }
    }

    private final class BookingPageBridge {
        @JavascriptInterface
        public void status(String message) {
            runOnUiThread(() -> setBookingStatus(message));
        }

        @JavascriptInterface
        public void completed() {
            runOnUiThread(MainActivity.this::bookingCompleted);
        }

        @JavascriptInterface
        public void failed(String message) {
            runOnUiThread(() -> setBookingStatus(message));
        }
    }

    private void bookingCompleted() {
        setBookingStatus("Reservation submitted. Confirming it in CourtFlow…");
        if (courtFlow != null) {
            courtFlow.evaluateJavascript(
                    "window.dispatchEvent(new CustomEvent('courtflow-native-booking-complete'));",
                    null
            );
        }
        if (bookingDialog != null) {
            bookingStatus.postDelayed(() -> {
                if (bookingDialog != null && bookingDialog.isShowing()) bookingDialog.dismiss();
            }, 900);
        }
    }

    private void setBookingStatus(String message) {
        if (bookingStatus != null) bookingStatus.setText(message);
    }

    private void nativeMessage(String message) {
        runOnUiThread(() -> {
            if (courtFlow == null) return;
            String js = "window.dispatchEvent(new CustomEvent('courtflow-native-message',{detail:" + JSONObject.quote(message) + "}));";
            courtFlow.evaluateJavascript(js, null);
        });
    }

    private String loginScript(BookingRequest r) {
        return "(function(){" +
                "const email=" + JSONObject.quote(r.email) + ";" +
                "const pass=" + JSONObject.quote(r.password) + ";" +
                "const e=document.querySelector('input[type=email],input[name*=email i]');" +
                "const p=document.querySelector('input[type=password]');" +
                "if(!e||!p){CourtFlowBookingNative.failed('Could not find the PlayLocal sign-in fields.');return;}" +
                "function set(el,v){el.focus();el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}" +
                "set(e,email);set(p,pass);" +
                "const f=p.form||e.form||document.querySelector('form');" +
                "if(!f){CourtFlowBookingNative.failed('Could not find the PlayLocal sign-in form.');return;}" +
                "f.submit();" +
                "})();";
    }

    private String reservationScript(BookingRequest r) {
        String courtId = JSONObject.quote(r.courtId);
        String courtName = JSONObject.quote(r.courtName);
        return "(function(){" +
                "const courtId=" + courtId + ";const courtName=" + courtName + ";" +
                "let controls=[...document.querySelectorAll('[name*=\\\"reservable_id\\\"]')];" +
                "let exact=controls.find(x=>String(x.value)===String(courtId));" +
                "if(!exact){CourtFlowBookingNative.failed('PlayLocal no longer offers '+courtName+' for this time.');return;}" +
                "if(exact.tagName==='SELECT'){exact.value=courtId;exact.dispatchEvent(new Event('change',{bubbles:true}));}" +
                "else if((exact.type||'').toLowerCase()==='radio'){exact.click();exact.checked=true;exact.dispatchEvent(new Event('change',{bubbles:true}));}" +
                "else {let box=exact.closest('[data-role=\\\"court-selection\\\"],label,li,article,.card,div');if(box){let c=box.querySelector('input[type=radio],label,button');if(c)c.click();}}" +
                "document.querySelectorAll('input[type=checkbox]').forEach(x=>{let h=((x.name||'')+' '+(x.id||'')+' '+(x.getAttribute('aria-label')||'')).toLowerCase();if(x.required||/term|policy|agree|accept/.test(h)){if(!x.checked)x.click();}});" +
                "CourtFlowBookingNative.status(''+courtName+' selected. Waiting for PlayLocal verification…');" +
                "let submitted=false;" +
                "function done(){if(submitted)return;let body=(document.body.innerText||'').toLowerCase();if(/reservation (confirmed|created|booked)|successfully reserved|reservation receipt/.test(body)){submitted=true;CourtFlowBookingNative.completed();return;}" +
                "let challenge=document.querySelector('input[name=\\\"cf-turnstile-response\\\"],textarea[name=\\\"cf-turnstile-response\\\"],[name*=captcha i],[name*=challenge i]');" +
                "let token=challenge&&String(challenge.value||'').trim();" +
                "let waiting=/please wait for verification to complete|complete verification|verify you are human/.test(body);" +
                "let btn=document.querySelector('button[type=submit],input[type=submit]');" +
                "let ready=btn&&!btn.disabled&&((challenge&&token)||(!challenge&&!waiting));" +
                "if(ready){submitted=true;CourtFlowBookingNative.status('Verification complete. Submitting reservation…');btn.click();setTimeout(()=>{submitted=false;},5000);}" +
                "}" +
                "setInterval(done,500);done();" +
                "})();";
    }

    private int dp(int value) {
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }
}
