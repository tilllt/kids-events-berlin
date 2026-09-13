/* Change 018 — „In meiner Nähe": Umkreissuche, Kalender-Abo, Standort-Karte.
 *
 * Der Block sitzt ÜBER der Karte und ist zugeklappt eine Zeile. Aufbau:
 *
 *   [📍 In meiner Nähe                          2 km  ✕]
 *      ( 📍 Mein Standort )  ( Kartenmitte )
 *      [ Postleitzahl oder Ortsteil…   ][ Suchen ]
 *      Umkreis  ( 1 km | 2 km | 5 km | 10 km )
 *
 * Ergänzt die Filter der App, ohne deren Logik anzufassen: Mittelpunkt und
 * Umkreis reisen als Parameter (lat, lon, umkreis_km) in der URL — dadurch
 * bleiben alle anderen Filter wirksam und die Auswahl ist als Link teilbar.
 *
 * Datenschutz: Der Mittelpunkt wird VOR dem Senden gerundet — Gerätestandort
 * auf drei Nachkommastellen (rund 110 m), PLZ/Kartenpunkt auf zwei (rund 1 km).
 * Kein genauer Aufenthaltsort in den Server-Logs, nichts wird gespeichert.
 * Der Standort wird nie ungefragt abgefragt: nur auf Klick — oder wenn der
 * Browser die Freigabe bereits erteilt hat, um die Karte zu zentrieren.
 */
(function () {
  "use strict";

  var STD_KM = 2;
  var KM_WAHL = [1, 2, 5, 10];
  var merker = { lat: null, lon: null, km: null };
  var letzteGj = null;      // letzte GeoJSON-Antwort
  var kreis = null;
  var standortPunkt = null;
  var ui = {};

  function runde(v, stellen) {
    var f = Math.pow(10, stellen);
    return Math.round(Number(v) * f) / f;
  }

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    });
    if (text != null) e.textContent = text;
    return e;
  }

  /* ---------- Zustand ---------- */

  function ausUrl() {
    var p = new URLSearchParams(location.search);
    var lat = p.get("lat"), lon = p.get("lon"), km = p.get("umkreis_km");
    merker = (lat && lon)
      ? { lat: lat, lon: lon, km: km || String(STD_KM) }
      : { lat: null, lon: null, km: null };
  }

  function setze(lat, lon, km) {
    merker = (lat == null || lon == null)
      ? { lat: null, lon: null, km: null }
      : { lat: String(lat), lon: String(lon), km: String(km || STD_KM) };
    syncUi();
    if (typeof load === "function") load();
  }

  function kmJetzt() { return Number(merker.km || STD_KM); }
  function aktiv() { return !!(merker.lat && merker.lon); }

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
      p.set("umkreis_km", merker.km || String(STD_KM));
      var voll = p.toString();
      history.replaceState(null, "", voll ? "?" + voll : location.pathname);
      return voll;
    };
  }

  // renderGeo() der App zeichnet Karte und Liste. Wir ergänzen Kreis und
  // Entfernungen, ohne die Darstellung der App zu verändern.
  function haengeRenderEin() {
    if (typeof window.renderGeo !== "function") return;
    var orig = window.renderGeo;
    window.renderGeo = function (gj) {
      letzteGj = gj;
      var r = orig.apply(this, arguments);
      try { nachbereiten(gj); } catch (e) { zeigeFehler("Nähe-Anzeige: " + e.message); }
      return r;
    };
  }

  /* ---------- Nachbereitung ---------- */

  function nachbereiten(gj) {
    // Gilt für alle Filter, nicht nur für den Umkreis — und braucht Nachläufe:
    // die App füllt die Liste NACH der Karte und leert dabei die Zeile über
    // ihr (renderList setzt sie neu). Deshalb hier, VOR dem Umkreis-Zweig.
    setzeAboLink();
    [400, 1500, 3000].forEach(function (ms) {
      setTimeout(function () {
        try { setzeAboLink(); } catch (e) { /* egal */ }
      }, ms);
    });
    if (!aktiv()) { infoLeeren(); kreisEntfernen(); syncUi(); return; }

    setzeEntfernungen(gj);
    [400, 1500, 3000].forEach(function (ms) {
      setTimeout(function () {
        try { setzeEntfernungen(gj); } catch (e) { /* egal */ }
      }, ms);
    });
    zeichneKreis();
    syncUi();
  }

  // Entfernung an die Listeneinträge schreiben. Die <li> der App tragen keine
  // Kennung (nur class/title) — verbunden wird über den Titel. Gesetzt wird nur
  // bei eindeutiger Zuordnung: entweder liegen alle Einträge dieses Titels
  // gleich weit, oder Titel und Einträge sind 1:1 (dann in Startreihenfolge,
  // wie die Liste sortiert ist). Lieber kein Wert als ein falscher.
  function setzeEntfernungen(gj) {
    var liProTitel = {};
    Array.prototype.forEach.call(document.querySelectorAll("#eventlist li"), function (li) {
      var h = li.querySelector("h3");
      if (!h) return;
      var t = (h.textContent || "").trim();
      (liProTitel[t] = liProTitel[t] || []).push(li);
    });
    var jeTitel = {};
    (gj.features || []).forEach(function (f) {
      var p = f.properties || {};
      if (p.entfernung_km == null || !p.titel) return;
      var t = String(p.titel).trim();
      (jeTitel[t] = jeTitel[t] || []).push({ km: p.entfernung_km, start: String(p.start_local || "") });
    });
    Object.keys(jeTitel).forEach(function (t) {
      var lis = liProTitel[t];
      if (!lis || !lis.length) return;
      var eintraege = jeTitel[t];
      var werte = {};
      eintraege.forEach(function (e) { werte[e.km] = true; });
      var eindeutig = Object.keys(werte).length === 1;
      var gleichViele = lis.length === eintraege.length;
      if (!eindeutig && !gleichViele) return;
      if (!eindeutig) {
        eintraege.sort(function (a, b) { return a.start.localeCompare(b.start); });
      }
      lis.forEach(function (li, i) {
        var km = eindeutig ? Object.keys(werte)[0] : (eintraege[i] || {}).km;
        if (km == null) return;
        var s = li.querySelector(".naehe-km");
        if (!s) {
          s = el("span", { class: "naehe-km" }, "");
          (li.querySelector(".li-meta") || li).appendChild(s);
        }
        s.textContent = String(km).replace(".", ",") + " km";
      });
    });
  }

  function zeichneKreis() {
    if (typeof map === "undefined" || !map) return;
    kreisEntfernen();
    if (!aktiv()) return;
    var c = [Number(merker.lat), Number(merker.lon)];
    kreis = L.circle(c, {
      radius: kmJetzt() * 1000,
      color: "#2ea043", weight: 2, fillOpacity: 0.08,
    }).addTo(map);
    L.circleMarker(c, { radius: 5, color: "#2ea043", fillOpacity: 1 }).addTo(map);
    try { map.fitBounds(kreis.getBounds(), { maxZoom: 14 }); } catch (e) { /* egal */ }
  }

  function kreisEntfernen() {
    if (kreis && typeof map !== "undefined" && map) map.removeLayer(kreis);
    kreis = null;
  }

  /* ---------- Kalender-Abo (gehört zur ganzen Auswahl) ---------- */

  function setzeAboLink() {
    var box = document.getElementById("liststate");
    if (!box) return;
    var p = new URLSearchParams(location.search);
    if (aktiv()) {
      p.set("lat", merker.lat); p.set("lon", merker.lon);
      p.set("umkreis_km", merker.km || String(STD_KM));
    }
    var pfad = "/api/kalender.ics?" + p.toString();
    var gruppe = document.getElementById("naehe-abo");
    if (!gruppe) {
      box.appendChild(document.createTextNode(" · "));
      gruppe = el("span", { id: "naehe-abo", class: "naehe-abo" });
      // Rückmeldung: Ein normaler Link lädt die Datei nur EINMAL herunter — kein
      // Abonnement. Deshalb zwei Wege: webcal:// öffnet auf iPhone/Android den
      // Abo-Dialog, und die Adresse lässt sich für jede Kalender-App kopieren.
      gruppe.appendChild(el("a", { class: "naehe-abo-link",
        title: "In der Kalender-App abonnieren — die Adresse bleibt gültig und " +
               "aktualisiert sich dort selbst." }, "Kalender abonnieren"));
      var kopie = el("button", { type: "button", class: "ghost naehe-abo-kopie",
        title: "Adresse kopieren und in der Kalender-App als Abonnement einfügen" },
        "Adresse kopieren");
      kopie.addEventListener("click", function () {
        var url = location.origin + pfad;
        var b = this;
        var fertig = function () {
          b.textContent = "kopiert";
          setTimeout(function () { b.textContent = "Adresse kopieren"; }, 2000);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(fertig, function () {
            window.prompt("Adresse zum Abonnieren:", url);
          });
        } else {
          window.prompt("Adresse zum Abonnieren:", url);
        }
      });
      gruppe.appendChild(kopie);
      box.appendChild(gruppe);
    }
    gruppe.querySelector(".naehe-abo-link").href = "webcal://" + location.host + pfad;
  }

  /* ---------- Oberfläche ---------- */

  function baueUi() {
    var karte = document.getElementById("map");
    if (!karte) return false;

    var style = el("style");
    style.textContent =
      // Rahmen und Kopf
      ".naehe{border:1px solid var(--border,#2a2f36);border-radius:10px;" +
      "background:var(--panel,#161b21);margin:0 0 6px;overflow:hidden}" +
      ".naehe>summary{display:flex;align-items:center;gap:8px;cursor:pointer;" +
      "padding:9px 12px;font-size:13px;color:#e6edf3;list-style:none;" +
      "-webkit-tap-highlight-color:transparent}" +
      ".naehe>summary::-webkit-details-marker{display:none}" +
      ".naehe>summary:hover{background:rgba(255,255,255,.03)}" +
      ".naehe-pfeil{color:#2ea043;font-size:11px;width:10px}" +
      ".naehe[open] .naehe-pfeil{transform:rotate(90deg)}" +
      ".naehe-titel{flex:1 1 auto;font-weight:600;letter-spacing:.01em}" +
      ".naehe-chip{font-size:11.5px;padding:2px 8px;border-radius:999px;" +
      "background:rgba(46,160,67,.16);color:#4ac26b;border:1px solid rgba(46,160,67,.35);" +
      "white-space:nowrap}" +
      ".naehe-aus{background:none;border:none;color:#9aa4b2;font-size:14px;cursor:pointer;" +
      "padding:2px 6px;line-height:1;border-radius:6px}" +
      ".naehe-aus:hover{background:rgba(248,81,73,.15);color:#f85149}" +
      // Inhalt
      ".naehe-body{padding:2px 12px 12px}" +
      ".naehe-zeile{display:flex;gap:8px;margin-top:8px}" +
      ".naehe-zeile>*{min-width:0}" +
      ".naehe-body button{min-height:38px;border-radius:8px;cursor:pointer;" +
      "font-size:13px;border:1px solid var(--border,#2a2f36);background:#1c222a;" +
      "color:#e6edf3;padding:0 12px;transition:background .12s,border-color .12s}" +
      ".naehe-body button:hover{background:#232b34}" +
      ".naehe-haupt{flex:1 1 auto;border-color:rgba(46,160,67,.5)!important;" +
      "background:rgba(46,160,67,.14)!important;color:#4ac26b!important;font-weight:600}" +
      ".naehe-haupt:hover{background:rgba(46,160,67,.24)!important}" +
      ".naehe-zweit{flex:0 1 auto;color:#9aa4b2!important}" +
      ".naehe-suche input{flex:1 1 auto;min-height:38px;border-radius:8px;padding:0 10px;" +
      "border:1px solid var(--border,#2a2f36);background:#12161b;color:#e6edf3;font-size:13px}" +
      ".naehe-suche input::placeholder{color:#6e7681}" +
      ".naehe-suche input:focus{outline:none;border-color:rgba(46,160,67,.6)}" +
      ".naehe-seg-wrap{display:flex;align-items:center;gap:8px;margin-top:10px;flex-wrap:wrap}" +
      ".naehe-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9aa4b2}" +
      ".naehe-seg{display:flex;border:1px solid var(--border,#2a2f36);border-radius:8px;overflow:hidden}" +
      ".naehe-seg button{min-height:34px;border:none;border-radius:0;background:transparent;" +
      "padding:0 12px;font-size:12.5px;color:#9aa4b2}" +
      ".naehe-seg button+button{border-left:1px solid var(--border,#2a2f36)}" +
      ".naehe-seg button[aria-pressed=true]{background:rgba(46,160,67,.18);color:#4ac26b;font-weight:600}" +
      ".naehe-info{margin:9px 0 0;font-size:12px;color:#9aa4b2;line-height:1.45}" +
      ".naehe-info.fehler{color:#f85149;font-weight:600}" +
      ".naehe-abo{white-space:nowrap}" +
      ".naehe-km{margin-left:6px;color:#4ac26b;font-weight:600;white-space:nowrap}";
    document.head.appendChild(style);

    var details = el("details", { class: "naehe" });
    var summary = el("summary", {});
    summary.appendChild(el("span", { class: "naehe-pfeil" }, "▸"));
    summary.appendChild(el("span", { class: "naehe-titel" }, "📍 In meiner Nähe"));
    ui.chip = el("span", { class: "naehe-chip" });
    ui.chip.style.display = "none";
    summary.appendChild(ui.chip);
    ui.aus = el("button", { class: "naehe-aus", type: "button", title: "Umkreis aufheben",
                            "aria-label": "Umkreis aufheben" }, "✕");
    ui.aus.style.display = "none";
    summary.appendChild(ui.aus);
    details.appendChild(summary);

    var body = el("div", { class: "naehe-body" });

    var z1 = el("div", { class: "naehe-zeile" });
    ui.standort = el("button", { class: "naehe-haupt", type: "button" }, "📍 Mein Standort");
    ui.standort.title = "Standort einmalig abfragen — wird auf ~110 m gerundet übertragen, " +
                        "nicht gespeichert";
    ui.mitte = el("button", { class: "naehe-zweit", type: "button" }, "Kartenmitte");
    ui.mitte.title = "Mittelpunkt auf die Mitte der sichtbaren Karte setzen";
    z1.appendChild(ui.standort);
    z1.appendChild(ui.mitte);
    body.appendChild(z1);

    var z2 = el("div", { class: "naehe-zeile naehe-suche" });
    ui.plz = el("input", { type: "search", placeholder: "Postleitzahl oder Ortsteil…",
                           autocomplete: "off", "aria-label": "Postleitzahl oder Ortsteil" });
    ui.plzBtn = el("button", { class: "naehe-zweit", type: "button" }, "Suchen");
    z2.appendChild(ui.plz);
    z2.appendChild(ui.plzBtn);
    body.appendChild(z2);

    var z3 = el("div", { class: "naehe-seg-wrap" });
    z3.appendChild(el("span", { class: "naehe-label" }, "Umkreis"));
    var seg = el("div", { class: "naehe-seg", role: "group", "aria-label": "Umkreis wählen" });
    ui.segmente = [];
    KM_WAHL.forEach(function (k) {
      var b = el("button", { type: "button", "data-km": String(k),
                             "aria-pressed": "false" }, k + " km");
      b.addEventListener("click", function () { waehleUmkreis(k); });
      seg.appendChild(b);
      ui.segmente.push(b);
    });
    z3.appendChild(seg);
    body.appendChild(z3);

    ui.info = el("p", { class: "naehe-info" });
    body.appendChild(ui.info);

    details.appendChild(body);
    ui.details = details;
    ui.summary = summary;

    // Über der Karte einhängen — als Geschwister des Karten-Containers, damit
    // die Höhe der Karte unangetastet bleibt.
    var anker = karte.parentElement || karte;
    var eltern = (anker.parentElement && anker.parentElement !== document.body)
      ? anker.parentElement : anker;
    eltern.insertBefore(details, anker);

    ui.standort.addEventListener("click", holeStandort);
    ui.mitte.addEventListener("click", ausKartenmitte);
    ui.plzBtn.addEventListener("click", ausPlz);
    ui.plz.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); ausPlz(); }
    });
    // Das ✕ im Kopf darf den Block nicht mit auf-/zuklappen.
    ui.aus.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      setze(null, null, null);
    });
    karteKlickbar();
    return true;
  }

  function waehleUmkreis(k) {
    if (aktiv()) {
      setze(merker.lat, merker.lon, k);
      return;
    }
    merker.km = String(k);
    if (ui.details) ui.details.open = true;   // Auswahl ohne Mittelpunkt: erst Ort wählen
    syncUi();
    setzeInfo("Umkreis " + k + " km gewählt — jetzt Standort, Postleitzahl oder " +
              "Kartenmitte wählen.", "ok");
  }

  function karteKlickbar() {
    if (typeof map === "undefined" || !map) return;
    // Immer aktiv: der Klick auf die Karte ist der einfachste Weg zum Mittelpunkt.
    map.on("click", function (ev) {
      setze(runde(ev.latlng.lat, 2), runde(ev.latlng.lng, 2), kmJetzt());
    });
    // Zweiter Weg auf dem Handy: Wer eine Marke oder einen Pulk trifft, bekommt
    // das Fenster des Termins — dort setzt dieser Knopf den Umkreis dorthin.
    map.on("popupopen", function (ev) {
      try {
        var ll = ev.popup.getLatLng();
        var box = ev.popup.getElement();
        if (!ll || !box || box.querySelector(".naehe-hier")) return;
        var b = el("button", { type: "button", class: "naehe-hier naehe-zweit" },
                   "Umkreis hier setzen");
        b.addEventListener("click", function () {
          setze(runde(ll.lat, 2), runde(ll.lng, 2), kmJetzt());
        });
        (box.querySelector(".leaflet-popup-content") || box).appendChild(b);
      } catch (e) { /* Fenster bleibt wie es ist */ }
    });
  }

  function syncUi() {
    if (!ui.chip) return;
    var an = aktiv();
    ui.aus.style.display = an ? "" : "none";
    if (an) {
      ui.chip.style.display = "";
      ui.chip.textContent = (merker.km || STD_KM) + " km";
    } else {
      ui.chip.style.display = "none";
    }
    (ui.segmente || []).forEach(function (b) {
      b.setAttribute("aria-pressed", String(Number(b.getAttribute("data-km")) === kmJetzt()));
    });
    setzeAboLink();
  }

  function setzeInfo(text, art) {
    if (!ui.info) return;
    ui.info.className = "naehe-info" + (art === "fehler" ? " fehler" : "");
    ui.info.textContent = text || "";
  }

  function infoLeeren() { setzeInfo("", "ok"); }
  function zeigeFehler(text) { setzeInfo(text, "fehler"); }

  /* ---------- Eingaben ---------- */

  function holeStandort() {
    if (!navigator.geolocation) {
      zeigeFehler("Dieser Browser kann keinen Standort liefern — bitte Postleitzahl " +
                  "eingeben oder Kartenmitte nehmen.");
      return;
    }
    setzeInfo("Standort wird einmalig abgefragt…", "ok");
    navigator.geolocation.getCurrentPosition(function (pos) {
      // Drei Nachkommastellen (rund 110 m): genau genug für 1 km Umkreis,
      // kein genauer Aufenthaltsort in den Server-Logs.
      setze(runde(pos.coords.latitude, 3), runde(pos.coords.longitude, 3), kmJetzt());
    }, function (err) {
      zeigeFehler("Standort nicht freigegeben (" + (err.message || err.code) + ") — bitte " +
                  "Postleitzahl eingeben oder Kartenmitte nehmen.");
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }

  function ausKartenmitte() {
    if (typeof map === "undefined" || !map) {
      zeigeFehler("Die Karte ist noch nicht bereit — bitte kurz warten.");
      return;
    }
    var c = map.getCenter();
    setze(runde(c.lat, 2), runde(c.lng, 2), kmJetzt());
  }

  function ausPlz() {
    var wert = (ui.plz.value || "").trim();
    if (wert.length < 3) {
      zeigeFehler("Bitte Postleitzahl oder Ortsnamen eingeben (mindestens 3 Zeichen).");
      return;
    }
    setzeInfo("Suche Mittelpunkt zu „" + wert + "“ …", "ok");
    fetch("/api/plz/" + encodeURIComponent(wert))
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          var f = res.d && res.d.detail;
          if (f && f.fehler) f = f.fehler.join(" ");
          zeigeFehler("Nicht gefunden: " + (f || "keine Termine mit Position") +
                      " — anderen Ort versuchen oder Kartenmitte nehmen.");
          return;
        }
        setze(res.d.lat, res.d.lon, kmJetzt());
        setzeInfo("Mittelpunkt gesetzt.", "ok");
      })
      .catch(function (e) { zeigeFehler("Suche fehlgeschlagen: " + e.message); });
  }

  /* ---------- Karte am Standort starten, wenn schon erlaubt ---------- */

  function standortWennErlaubt() {
    if (!navigator.geolocation || !navigator.permissions ||
        typeof navigator.permissions.query !== "function") return;
    navigator.permissions.query({ name: "geolocation" }).then(function (st) {
      if (st.state !== "granted") return;   // nie ungefragt nachfragen
      navigator.geolocation.getCurrentPosition(function (pos) {
        if (typeof map === "undefined" || !map) return;
        var c = [pos.coords.latitude, pos.coords.longitude];
        try {
          map.setView(c, 14);
          if (standortPunkt) map.removeLayer(standortPunkt);
          standortPunkt = L.circleMarker(c, { radius: 6, color: "#58a6ff",
                                              fillOpacity: 0.9, fillColor: "#58a6ff" })
            .addTo(map)
            .bindPopup("Ihr Standort (nur in Ihrem Browser)");
        } catch (e) { /* Karte noch nicht bereit */ }
        if (!aktiv()) setzeInfo("Karte auf Ihren Standort gesetzt.", "ok");
      }, function () { /* still: keine Freigabe */ },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 });
    }).catch(function () { /* Browser ohne Permissions-API */ });
  }

  /* ---------- Start ---------- */

  function start() {
    if (!baueUi()) return;
    syncUi();
    if (letzteGj) { try { nachbereiten(letzteGj); } catch (e) { /* egal */ } }
    setTimeout(standortWennErlaubt, 800);
  }

  // WICHTIG: Zustand aus der URL lesen und die Funktionen der App SOFORT beim
  // Laden dieses Skripts einhängen — nicht erst bei DOMContentLoaded. Die App
  // startet ihre erste Abfrage in ihrem eigenen DOMContentLoaded-Handler, der
  // vor unserem läuft. Ohne diese Reihenfolge fehlte der ersten Abfrage der
  // Umkreis (die Liste zeigte alle Termine statt der nahen).
  ausUrl();
  haengeEin();
  haengeRenderEin();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
