from pathlib import Path

p = Path('android/app/src/main/java/com/toshreds/courtflow/MainActivity.java')
s = p.read_text()
old = '''        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            return !url.startsWith("https://www.playlocal.com/") && !url.startsWith("https://playlocal.com/");
        }
'''
new = '''        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            // Allow verification/challenge iframes and other subresources to load normally.
            // Restrict only top-level navigation away from PlayLocal.
            if (!request.isForMainFrame()) return false;
            String url = request.getUrl().toString();
            return !url.startsWith("https://www.playlocal.com/") && !url.startsWith("https://playlocal.com/");
        }
'''
if old not in s:
    if 'if (!request.isForMainFrame()) return false;' not in s:
        raise SystemExit('WebView navigation block not found')
else:
    s = s.replace(old, new, 1)
p.write_text(s)
