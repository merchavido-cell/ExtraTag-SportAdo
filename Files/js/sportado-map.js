// ============================================================
//  SportAdo Map - מפה Leaflet + רינדור מסלול
// ============================================================

window.SportAdoMap = (function () {

    let map = null;
    let routeLine = null;
    let currentMarker = null;
    let startMarker = null;

    function init(containerId) {
        map = L.map(containerId, {
            zoomControl: true,
            attributionControl: false
        }).setView([32.0853, 34.7818], 15);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
        }).addTo(map);

        routeLine = L.polyline([], {
            color: '#38bdf8', weight: 5, opacity: 0.9,
        }).addTo(map);

        // נסה להתמקד על המיקום הנוכחי
        navigator.geolocation.getCurrentPosition(
            (pos) => map.setView([pos.coords.latitude, pos.coords.longitude], 16),
            () => {},
            { enableHighAccuracy: true, timeout: 8000 }
        );

        return map;
    }

    function addPoint(lat, lng, isFirst) {
        if (!map) return;
        routeLine.addLatLng([lat, lng]);

        if (!currentMarker) {
            currentMarker = L.circleMarker([lat, lng], {
                radius: 8, color: '#fff', fillColor: '#38bdf8',
                fillOpacity: 1, weight: 3,
            }).addTo(map);
        } else {
            currentMarker.setLatLng([lat, lng]);
        }

        if (isFirst) {
            startMarker = L.circleMarker([lat, lng], {
                radius: 6, color: '#fff', fillColor: '#22c55e',
                fillOpacity: 1, weight: 3,
            }).addTo(map);
            map.setView([lat, lng], 17);
        }
    }

    function clear() {
        if (!map) return;
        routeLine.setLatLngs([]);
        if (currentMarker) { map.removeLayer(currentMarker); currentMarker = null; }
        if (startMarker)   { map.removeLayer(startMarker);   startMarker = null; }
    }

    function fitRoute() {
        if (!map || routeLine.getLatLngs().length < 2) return;
        map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });
    }

    return {
        init: init,
        addPoint: addPoint,
        clear: clear,
        fitRoute: fitRoute
    };
})();