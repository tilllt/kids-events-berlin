/* Change 018 — „In meiner Nähe" (Umkreissuche) und Kalender-Abo.
 *
 * Ergänzt die bestehende Filterleiste, ohne deren Logik anzufassen: Mittelpunkt
 * und Umkreis landen als Parameter (lat, lon, km) in der URL. Dadurch bleiben
 * alle anderen Filter wirksam, und die Auswahl ist als Link teilbar.
 *
 * Datenschutz: Der Mittelpunkt wird VOR dem Senden gerundet — Gerätestandort
 * auf drei Nachkommastellen (rund 110 m), PLZ/Ort auf zwei (rund 1 km). So
 * steht in den Server-Logs kein genauer Aufenthaltsort. Nichts wird gespeichert.
 */
(function () {
  "use strict";

  var STD_KM = 2;
  var KM_WAHL = [1, 2, 5, 10];
  var merker = { lat: null, lon: null, km: null };
  var kreis = null;

  function runde(v, stellen) {
    var f = Math.pow(10, stellen);
    return Math.round(Number(v) * f) / f;
  }

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- Zustand in der URL ---------- */

  function ausUrl() {
    var p = new URLSearchParams(location.search);
    var lat = p.get("lat"), lon = p.get("lon"), km = p.get("km");
    merker = (lat && lon) ? { lat: lat, lon: lon, km: km || String(STD_KM) }
                          : { lat: null, lon: null, km: null };
  }

  function setze(lat, lon, km) {
    merker = (lat == null || lon == null)
      ? { lat: null, lon: null, km: null }
      : { lat: String(lat), lon: String(lon), km: String(km || STD_KM) };
    syncUi();
    if (typeof load === "function") load();
  }

  /* ---------- Anbindung an die App ---------- */

  // queryParams() der App baut die Abfrage aus ihren eigenen Filtern. Wir
  // hängen Mittelpunkt und Umkreis an — sonst gingen sie bei jedem Laden
  // verloren (die Funktion schreibt die URL neu).
  function haengeEin() {
    if (typeof window.queryParams !== "function") return;
    var orig = window.queryParams;
    window.queryParams = function () {
      var qs = orig();
      if (!merker.lat || !merker.lon) return qs;
      var p = new URLSearchParams(qs);
      p.set("lat", merker.lat);
      p.set("lon", merker.lon);
      p.set("km", merker.km || String(STD_KM));
      var voll = p.toString();
      history.replaceState(null, "", voll ? "?" + voll : location.pathname);
      return voll;
    };
  }

  // renderGeo() der App zeichnet Karte und Liste. Wir lesen die Zahlen aus und
  // ergänzen Entfernung + Kreis, ohne die Darstellung der App zu verändern.
  function haengeRenderEin() {
    if (typeof window.renderGeo !== "function") return;
    var orig = window.renderGeo;
    window.renderGeo = function (gj) {
      var r = orig.apply(this, arguments);
      try { nachbereiten(gj); } catch (e) { zeigeFehler("Nähe-Anzeige: " + e.message); }
      return r;
    };
  }

  /* ---------- Nachbereitung der Anzeige ---------- */

  function nachbereiten(gj) {
    if (!merker.lat || !merker.lon) { infoLeeren(); kreisEntfernen(); return; }
    var km = Number(merker.km || STD_KM);
    var drin = (gj.features || []).length;
    var ohne = (gj.ohne_position || []).length;
    var draussen = gj.ausserhalb_umkreis || 0;

    var teile = [drin + (drin === 1 ? " Termin" : " Termine") +
                 " im Umkreis von " + km + " km"];
    if (ohne) teile.push(ohne + " ohne Kartenposition können hier nicht erscheinen");
    if (draussen) teile.push(draussen + " liegen außerhalb");
    setzeInfo(teile.join(" · "), "ok");

    // Entfernung an die Listeneinträge schreiben (die App kennzeichnet sie mit
    // data-ev-id) — wenn das Attribut fehlt, passiert einfach nichts.
    var entf = {};
    (gj.features || []).forEach(function (f) {
      var p = f.properties || {};
      if (p.id != null && p.entfernung_km != null) entf[String(p.id)] = p.entfernung_km;
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-ev-id]"), function (li) {
      var alt = li.querySelector(".naehe-km");
      if (alt) alt.remove();
      var d = entf[li.getAttribute("data-ev-id")];
      if (d == null) return;
      var s = el("span", { class: "naehe-km" },
                 String(d).replace(".", ",") + " km");
      var ziel = li.querySelector(".ev-kopf, .ev-titel, h3") || li.firstElementChild || li;
      ziel.appendChild(s);
    });

    zeichneKreis();
  }

  function zeichneKreis() {
    if (typeof map === "undefined" || !map) return;
    kreisEntfernen();
    if (!merker.lat || !merker.lon) return;
    var c = [Number(merker.lat), Number(merker.lon)];
    kreis = L.circle(c, {
      radius: Number(merker.km || STD_KM) * 1000,
      color: "#2ea043", weight: 1.5, fillOpacity: 0.06,
    }).addTo(map);
    L.circleMarker(c, { radius: 5, color: "#2ea043", fillOpacity: 1 }).addTo(map);
    try { map.fitBounds(kreis.getBounds(), { maxZoom: 14 }); } catch (e) { /* egal */ }
  }

  function kreisEntfernen() {
    if (kreis && typeof map !== "undefined" && map) { map.removeLayer(kreis); }
    kreis = null;
  }

  /* ---------- Oberfläche ---------- */

  var ui = {};

  function baueUi() {
    var aside = document.getElementById("filters");
    if (!aside) return false;
    var style = el("style");
    style.textContent =
      ".naehe-block{border:1px solid #2a2f36;border-radius:10px;padding:.6rem .7rem;" +
      "margin:.2rem 0 .8rem;background:#14181d}" +
      ".naehe-block h3{margin:0 0 .5rem;font-size:.85rem;letter-spacing:.02em;" +
      "text-transform:uppercase;color:#9aa4b2}" +
      ".naehe-zeile{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin:.35rem 0}" +
      ".naehe-block button{cursor:pointer}" +
      ".naehe-km{margin-left:.4rem;color:#2ea043;font-weight:600;white-space:nowrap}" +
      ".naehe-info{margin:.35rem 0 0;font-size:.82rem;color:#9aa4b2}" +
      ".naehe-info.fehler{color:#f85149;font-weight:600}" +
      ".naehe-abo{font-size:.8rem;color:#9aa4b2;margin:.35rem 0 0}" +
      ".naehe-abo code{display:block;word-break:break-all;color:#c9d1d9}";
    document.head.appendChild(style);

    var block = el("div", { class: "naehe-block" });
    block.appendChild(el("h3", {}, "In meiner Nähe"));

    var zeile1 = el("div", { class: "naehe-zeile" });
    ui.standort = el("button", { type: "button", class: "ghost" }, "📍 Mein Standort");
    ui.standort.title = "Standort einmalig abfragen — wird auf ~110 m gerundet übertragen, nicht gespeichert";
    zeile1.appendChild(ui.standort);
    ui.aus = el("button", { type: "button", class: "ghost" }, "✕ Nähe aus");
    ui.aus.style.display = "none";
    zeile1.appendChild(ui.aus);
    block.appendChild(zeile1);

    var zeile2 = el("div", { class: "naehe-zeile" });
    ui.plz = el("input", { type: "search", placeholder: "PLZ oder Ortsteil…",
                           autocomplete: "off", style: "flex:1 1 8rem" });
    ui.plzBtn = el("button", { type: "button", class: "ghost" }, "Übernehmen");
    zeile2.appendChild(ui.plz);
    zeile2.appendChild(ui.plzBtn);
    block.appendChild(zeile2);

    var zeile3 = el("div", { class: "naehe-zeile" });
    zeile3.appendChild(el("label", { for: "naehe-km", style: "font-size:.85rem" }, "Umkreis"));
    ui.km = el("select", { id: "naehe-km" });
    KM_WAHL.forEach(function (k) {
      var o = el("option", { value: String(k) }, k + " km");
      if (k === STD_KM) o.setAttribute("selected", "selected");
      ui.km.appendChild(o);
    });
    zeile3.appendChild(ui.km);
    zeile3.appendChild(el("span", { style: "font-size:.78rem;color:#9aa4b2" },
                          "Tipp: Klick auf die Karte setzt den Mittelpunkt"));
    block.appendChild(zeile3);

    ui.info = el("p", { class: "naehe-info" });
    block.appendChild(ui.info);

    var abo = el("div", { class: "naehe-abo" });
    ui.aboLink = el("a", { href: "#", target: "_blank", rel: "noopener" },
                    "Diese Auswahl als Kalender abonnieren");
    abo.appendChild(ui.aboLink);
    block.appendChild(abo);

    aside.insertBefore(block, aside.firstChild);

    ui.standort.addEventListener("click", holeStandort);
    ui.aus.addEventListener("click", function () { setze(null, null, null); });
    ui.plzBtn.addEventListener("click", ausPlz);
    ui.plz.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); ausPlz(); }
    });
    ui.km.addEventListener("change", function () {
      if (merker.lat && merker.lon) setze(merker.lat, merker.lon, ui.km.value);
    });
    karteKlickbar();
    return true;
  }

  function karteKlickbar() {
    if (typeof map === "undefined" || !map) return;
    map.on("click", function (ev) {
      if (!merker.lat) return;   // nur wenn die Nähe-Suche aktiv ist
      setze(runde(ev.latlng.lat, 2), runde(ev.latlng.lng, 2),
            ui.km ? ui.km.value : STD_KM);
    });
  }

  function syncUi() {
    if (!ui.km) return;
    var aktiv = !!(merker.lat && merker.lon);
    ui.aus.style.display = aktiv ? "" : "none";
    if (merker.km) ui.km.value = merker.km;
    aktualisiereAbo();
  }

  function setzeInfo(text, art) {
    if (!ui.info) return;
    ui.info.className = "naehe-info" + (art === "fehler" ? " fehler" : "");
    ui.info.textContent = text || "";
  }

  function infoLeeren() { setzeInfo("", "ok"); }

  function zeigeFehler(text) { setzeInfo(text, "fehler"); }

  function aktualisiereAbo() {
    if (!ui.aboLink) return;
    var p = new URLSearchParams(typeof window.queryParams === "function"
      ? window.queryParams() : location.search);
    if (merker.lat && merker.lon) {
      p.set("lat", merker.lat); p.set("lon", merker.lon);
      p.set("km", merker.km || String(STD_KM));
    }
    ui.aboLink.href = "/api/kalender.ics?" + p.toString();
  }

  /* ---------- Eingaben ---------- */

  function holeStandort() {
    if (!navigator.geolocation) {
      zeigeFehler("Dieser Browser kann keinen Standort liefern — bitte Postleitzahl eingeben.");
      return;
    }
    setzeInfo("Standort wird einmalig abgefragt…", "ok");
    navigator.geolocation.getCurrentPosition(function (pos) {
      // Drei Nachkommastellen (rund 110 m): genau genug für 1 km Umkreis,
      // kein genauer Aufenthaltsort in den Server-Logs.
      setze(runde(pos.coords.latitude, 3), runde(pos.coords.longitude, 3),
            ui.km ? ui.km.value : STD_KM);
    }, function (err) {
      zeigeFehler("Standort nicht freigegeben (" + (err.message || err.code) +
                  ") — bitte Postleitzahl eingeben oder Punkt auf der Karte wählen.");
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }

  function ausPlz() {
    var wert = (ui.plz.value || "").trim();
    if (wert.length < 3) {
      zeigeFehler("Bitte Postleitzahl oder Ortsnamen eingeben (mindestens 3 Zeichen).");
      return;
    }
    setzeInfo("Suche Mittelpunkt zu „" + wert + "“ …", "ok");
    fetch("/api/plz/" + encodeURIComponent(wert))
      .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, d: d }; });
      })
      .then(function (res) {
        if (!res.ok) {
          var f = res.d && res.d.detail;
          if (f && f.fehler) f = f.fehler.join(" ");
          zeigeFehler("Nicht gefunden: " + (f || "keine Termine mit Position") +
                      " — anderen Ort versuchen oder Punkt auf der Karte wählen.");
          return;
        }
        setze(res.d.lat, res.d.lon, ui.km ? ui.km.value : STD_KM);
        setzeInfo("Mittelpunkt aus " + res.d.termine + " Terminen mit Position gesetzt.", "ok");
      })
      .catch(function (e) { zeigeFehler("Suche fehlgeschlagen: " + e.message); });
  }

  /* ---------- Start ---------- */

  function start() {
    ausUrl();
    if (!baueUi()) return;
    haengeEin();
    haengeRenderEin();
    syncUi();
    if (merker.lat) load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
