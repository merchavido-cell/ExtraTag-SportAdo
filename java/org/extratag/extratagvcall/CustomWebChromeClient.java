package org.extratag.extratagvcall;

import android.app.Activity;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;

/**
 * WebChromeClient אמיתי (extends, לא interface) שמאשר אוטומטית בקשות
 * הרשאה שמגיעות מתוך ה-WebView (getUserMedia - מצלמה/מיקרופון).
 *
 * חובה מחלקה ג'אווה אמיתית: pyjnius/PythonJavaClass יכול לממש רק
 * Java interfaces, ואילו WebChromeClient הוא class קונקרטי -
 * לכן לא ניתן לממש את זה נכון ישירות מפייתון.
 *
 * הקובץ הזה נכלל בבנייה דרך android.add_src = java שכבר מוגדר
 * ב-buildozer_vcall.spec.
 */
public class CustomWebChromeClient extends WebChromeClient {

    private final Activity activity;

    public CustomWebChromeClient(Activity activity) {
        super();
        this.activity = activity;
    }

    @Override
    public void onPermissionRequest(final PermissionRequest request) {
        if (request == null) {
            return;
        }
        if (activity == null) {
            request.deny();
            return;
        }
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    request.grant(request.getResources());
                } catch (Exception e) {
                    request.deny();
                }
            }
        });
    }
}