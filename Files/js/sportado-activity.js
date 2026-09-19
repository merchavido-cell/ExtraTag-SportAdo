// ============================================================
//  SportAdo Activity - לוגיקת מסך פעילות (start/pause/stop/save)
// ============================================================

(function () {

    const sport = sessionStorage.getItem('sportado_sport') || 'run';
    const sportLabels = {
        run: 'Run', bike: 'Bike', walk: 'Walk',
        duathlon: 'Duathlon', navigate: 'Navigate', strength: 'Strength'
    };
    const sportCalPerMin = {
        run: 10, bike: 8, walk: 4, duathlon: 9, navigate: 5, strength: 6
    };

    let recording = false;
    let paused = false;
    let startedAt = null;
    let endedAt = null;
    let pausedAccum = 0;
    let pauseStartTs = 0;
    let watchId = null;

    let points = [];
    let totalDistance = 0;
    let maxSpeed = 0;
    let lastPoint = null;

    let timerInterval = null;

    // ---------- Wake Lock helpers ----------
    function wakeLockOn() {
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.keep_screen_on) {
                window.pywebview.api.keep_screen_on().catch(() => {});
            }
        } catch (e) { /* ignore */ }
    }

    function wakeLockOff() {
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.release_screen_on) {
                window.pywebview.api.release_screen_on().catch(() => {});
            }
        } catch (e) { /* ignore */ }
    }

    // ---------- Timer ----------
    function elapsedSeconds() {
        if (!startedAt) return 0;
        const now = paused ? pauseStartTs : Date.now();
        return Math.floor((now - startedAt - pausedAccum) / 1000);
    }

    function formatTime(sec) {
        sec = Math.max(0, Math.floor(sec));
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = sec % 60;
        return String(h).padStart(2,'0') + ':' +
               String(m).padStart(2,'0') + ':' +
               String(s).padStart(2,'0');
    }

    function startTimer() {
        if (timerInterval) clearInterval(timerInterval);
        timerInterval = setInterval(() => {
            document.getElementById('timerDisplay').textContent = formatTime(elapsedSeconds());
            updateStats();
        }, 1000);
    }

    function stopTimer() {
        if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
    }

    // ---------- Stats ----------
    function updateStats() {
        const sec = elapsedSeconds();
        const km = totalDistance / 1000;
        const avgKmh = sec > 0 ? (km / (sec / 3600)) : 0;
        const curSpeed = lastPoint && lastPoint.spd ? lastPoint.spd * 3.6 : 0;

        document.getElementById('statDistance').textContent = km.toFixed(2);
        document.getElementById('statSpeed').textContent = (curSpeed || avgKmh).toFixed(1);

        const calPerMin = sportCalPerMin[sport] || 6;
        const cal = Math.round((sec / 60) * calPerMin);
        document.getElementById('statCalories').textContent = cal;
    }

    // ---------- Status ----------
    function setStatus(text, cls) {
        document.getElementById('statusText').textContent = text;
        document.getElementById('statusDot').className = 'status-dot ' + (cls || '');
    }

    function showToast(msg) {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.style.display = 'block';
        clearTimeout(t._timer);
        t._timer = setTimeout(() => { t.style.display = 'none'; }, 3000);
    }

    // ---------- GPS callbacks ----------
    function onPosition(pos) {
        if (paused) return;

        const c = pos.coords;
        const point = {
            lat: c.latitude,
            lng: c.longitude,
            t: pos.timestamp,
            alt: c.altitude || 0,
            acc: c.accuracy || 0,
            spd: c.speed || 0,
        };

        if (!window.SportAdoGPS.isPointValid(lastPoint, point)) return;

        if (lastPoint) {
            totalDistance += window.SportAdoGPS.haversine(
                lastPoint.lat, lastPoint.lng, point.lat, point.lng
            );
        }
        if (point.spd > maxSpeed) maxSpeed = point.spd;

        points.push(point);
        lastPoint = point;

        const isFirst = (points.length === 1);
        if (window.SportAdoMap) {
            window.SportAdoMap.addPoint(point.lat, point.lng, isFirst);
        }

        updateStats();
    }

    function onGpsError(err) {
        showToast('GPS error: ' + (err.message || err.code));
    }

    // ---------- Controls ----------
    window.startRecording = function () {
        recording = true;
        paused = false;
        startedAt = Date.now();
        endedAt = null;
        pausedAccum = 0;
        points = [];
        totalDistance = 0;
        maxSpeed = 0;
        lastPoint = null;

        if (window.SportAdoMap) {
            window.SportAdoMap.clear();
        }

        watchId = navigator.geolocation.watchPosition(
            onPosition, onGpsError,
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
        );

        // >>> WAKE LOCK ON <<<
        wakeLockOn();

        startTimer();
        setStatus('Recording', 'active');

        document.getElementById('btnStart').style.display = 'none';
        document.getElementById('btnPause').style.display = 'block';
        document.getElementById('btnStop').style.display = 'block';
        document.getElementById('btnSave').style.display = 'none';
    };

    window.togglePause = function () {
        if (!recording) return;
        if (paused) {
            paused = false;
            pausedAccum += Date.now() - pauseStartTs;
            setStatus('Recording', 'active');
            document.getElementById('btnPause').textContent = 'Pause';
        } else {
            paused = true;
            pauseStartTs = Date.now();
            setStatus('Paused', 'paused');
            document.getElementById('btnPause').textContent = 'Resume';
        }
    };

    window.stopRecording = function () {
        if (!recording) return;
        recording = false;
        endedAt = Date.now();

        if (watchId !== null) {
            navigator.geolocation.clearWatch(watchId);
            watchId = null;
        }
        stopTimer();

        // >>> WAKE LOCK OFF <<<
        wakeLockOff();

        setStatus('Completed', 'done');

        document.getElementById('btnPause').style.display = 'none';
        document.getElementById('btnStop').style.display = 'none';
        document.getElementById('btnSave').style.display = 'block';
    };

    window.goBack = function () {
        if (recording) {
            if (!confirm('Discard current activity?')) return;
            if (watchId !== null) navigator.geolocation.clearWatch(watchId);
            stopTimer();
            // >>> WAKE LOCK OFF <<<
            wakeLockOff();
        }
        window.pywebview.api.navigate_to('home.html', 'SportAdo - Home');
    };

    window.saveActivity = async function () {
        if (!startedAt) return;

        const btn = document.getElementById('btnSave');
        btn.disabled = true;
        btn.textContent = 'Saving...';

        const sec = elapsedSeconds();
        const km = totalDistance / 1000;
        const avgKmh = sec > 0 ? (km / (sec / 3600)) : 0;
        const calPerMin = sportCalPerMin[sport] || 6;
        const calories = Math.round((sec / 60) * calPerMin);

        // דחיסת המסלול לפורמט קומפקטי
        const compactRoute = points.map(p =>
            [p.lat.toFixed(6), p.lng.toFixed(6), p.t, Math.round(p.alt), p.spd.toFixed(2)].join(',')
        ).join('|');

        const payload = {
            sport: sport,
            started_at: new Date(startedAt).toISOString(),
            ended_at: new Date(endedAt || Date.now()).toISOString(),
            duration_seconds: sec,
            distance_meters: totalDistance,
            avg_speed_kmh: avgKmh,
            max_speed_kmh: maxSpeed * 3.6,
            calories: calories,
            elevation_gain_m: 0,
            route_compact: compactRoute,
            points_count: points.length,
        };

        try {
            const res = await window.pywebview.api.upload_activity(payload);
            const parsed = typeof res === 'string' ? JSON.parse(res) : res;

            if (parsed && parsed.success) {
                showToast('Saved: ' + parsed.file_name);
                // >>> WAKE LOCK OFF (ביטחון כפול - אם לא כיבה ב-stop) <<<
                wakeLockOff();
                setTimeout(() => {
                    window.pywebview.api.navigate_to('history.html', 'SportAdo - History');
                }, 1200);
            } else {
                showToast('Save failed: ' + (parsed && parsed.error || 'unknown'));
                btn.disabled = false;
                btn.textContent = 'Save';
            }
        } catch (e) {
            showToast('Save error: ' + e.message);
            btn.disabled = false;
            btn.textContent = 'Save';
        }
    };

    // ---------- Init ----------
    document.getElementById('sportTitle').textContent = sportLabels[sport] || 'Activity';

    if (window.SportAdoMap) {
        try {
            window.SportAdoMap.init('map');
        } catch (e) {
            console.error('Map init error:', e);
            showToast('Map unavailable');
        }
    } else {
        console.error('SportAdoMap not loaded');
    }

    setStatus('Ready', '');

})();