// ============================================================
//  SportAdo Bridge - תקשורת עם Python דרך document.title
//  משתמש ב-Proxy כדי לספק ממשק נוח: window.pywebview.api.X(...)
// ============================================================

(function () {
    var callbackCounter = 0;

    function callPython(method, args) {
        return new Promise(function (resolve, reject) {
            var callbackName = "_pyCallback_" + (callbackCounter++);
            var timedOut = false;

            window[callbackName] = function (result) {
                if (timedOut) return;
                clearTimeout(timeoutId);
                delete window[callbackName];
                resolve(result);
            };

            var timeoutId = setTimeout(function () {
                timedOut = true;
                delete window[callbackName];
                reject(new Error("Bridge timeout for " + method));
            }, 15000);

            try {
                document.title = "PY_BRIDGE:" + JSON.stringify({
                    action: method,
                    args: args,
                    callback: callbackName
                });
            } catch (err) {
                clearTimeout(timeoutId);
                delete window[callbackName];
                reject(err);
            }
        });
    }

    window.pywebview = {
        api: new Proxy({}, {
            get: function (target, prop) {
                return function () {
                    return callPython(prop, Array.prototype.slice.call(arguments));
                };
            }
        })
    };

    window.dispatchEvent(new Event('pywebviewready'));
})();