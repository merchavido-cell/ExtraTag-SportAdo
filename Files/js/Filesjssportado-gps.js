// ============================================================
//  SportAdo GPS - לקיחת מיקום, חישוב מרחק, סינון רעשים
// ============================================================

window.SportAdoGPS = (function () {

    // Haversine distance in meters
    function haversine(lat1, lng1, lat2, lng2) {
        const R = 6371000;
        const toRad = (x) => x * Math.PI / 180;
        const dLat = toRad(lat2 - lat1);
        const dLng = toRad(lng2 - lng1);
        const a = Math.sin(dLat / 2) ** 2 +
                  Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                  Math.sin(dLng / 2) ** 2;
        return 2 * R * Math.asin(Math.sqrt(a));
    }

    // בודק אם נקודה חדשה חוקית (לא קפיצה, לא רעש)
    function isPointValid(lastPoint, newPoint) {
        if (!lastPoint) return true;
        if (newPoint.acc > 60) return false;

        const dt = (newPoint.t - lastPoint.t) / 1000;
        if (dt <= 0) return false;

        const d = haversine(lastPoint.lat, lastPoint.lng, newPoint.lat, newPoint.lng);
        // אם המהירות גדולה מ-100 מ/ש = 360 קמ"ש, זה כנראה glitch
        if (d / dt > 100) return false;

        return true;
    }

    return {
        haversine: haversine,
        isPointValid: isPointValid
    };
})();