/* Change 018 — „In meiner Nähe": Umkreissuche, Kalender-Abo, Standort-Karte.
 *
 * Der Block sitzt ÜBER der Karte (nicht in der Filterseite), damit klar ist,
 * dass man den Mittelpunkt auch per Klick auf die Karte setzen kann. Er ist
 * ausklappbar (<details>); die Zusammenfassung zeigt den aktuellen Zustand.
 *
 * Ergänzt die Filter der App, ohne deren Logik anzufassen: Mittelpunkt und
 * Umkreis reisen als Parameter (lat, lon, km) in der URL — dadurch bleiben alle
 * anderen Filter wirksam und die Auswahl ist als Link teilbar.
 *
 * Datenschutz: Der Mittelpunkt wird VOR dem Senden gerundet — Gerätestandort
 * auf drei Nachkommastellen (rund 110 m), PLZ/Karte auf zwei (rund 1 km). So
 * steht in den Server-Logs kein genauer Aufenthaltsort. Nichts wird gespeichert.
 * Der Standort wird nie automatisch abgefragt: nur auf Klick — oder wenn der
 * Browser die Freigabe bereits erteilt hat, um die Karte zu zentrieren.
 */
(function () {
  "use strict";

  var STD_KM = 2;
  var KM_WAHL = [1, 2, 5, 10];
  var merker = { lat: null, lon: null, km: null };
  var letzteGj = null;   // letzte GeoJSON-Antwort (für Nachbereitung nach dem Aufbau)
  var kreis = null;
  var standortPunkt = null;

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
      letzteGj = gj;
      var r = orig.apply(this, arguments);
      try { nachbereiten(gj); } catch (e) { zeigeFehler("Nähe-Anzeige: " + e.message); }
      return r;
    };
  }

  /* ---------- Nachbereitung der Anzeige ---------- */

  function nachbereiten(gj) {
    if (!merker.lat || !merker.lon) { infoLeeren(); kreisEntfernen(); syncUi(); return; }
    var km = Number(merker.km || STD_KM);
    var drin = (gj.features || []).length;
    var ohne = (gj.ohne_position || []).length;
    var draussen = gj.ausserhalb_umkreis || 0;

    var teile = [drin + (drin === 1 ? " Termin" : " Termine") +
                 " im Umkreis von " + km + " km"];
    if (ohne) teile.push(ohne + " ohne Kartenposition können hier nicht erscheinen");
    if (draussen) teile.push(draussen + " liegen außerhalb");
    setzeInfo(teile.join(" · "), "ok");

    // Entfernung an die Listeneinträge schreiben. Die <li> der App tragen KEINE
    // Kennung (nur class/title) — verbunden wird deshalb über den Titel. Bei
    // gleichen Titeln bekommen beide Einträge dieselbe Entfernung; das ist
    // vertretbar, weil der Abstand praktisch derselbe Ort ist.
    var liProTitel = {};
    Array.prototype.forEach.call(document.querySelectorAll("#eventlist li"), function (li) {
      var h = li.querySelector("h3");
      if (h) liProTitel[(h.textContent || "").trim()] = li;
    });
    var setzeEntfernungen = function () {
      (gj.features || []).forEach(function (f) {
        var p = f.properties || {};
        if (p.entfernung_km == null || !p.titel) return;
        var li = liProTitel[String(p.titel).trim()];
        if (!li) return;
        var s = li.querySelector(".naehe-km");
        if (!s) {
          s = el("span", { class: "naehe-km" }, "");
          (li.querySelector(".li-meta") || li).appendChild(s);
        }
        s.textContent = String(p.entfernung_km).replace(".", ",") + " km";
      });
    };
    setzeEntfernungen();
    // Die App füllt die Liste erst nach der Karte — deshalb kurz danach noch
    // einmal (doppelte Einträge verhindert die Prüfung oben).
    setTimeout(function () { try { setzeEntfernungen(); } catch (e) { /* egal */ } }, 400);

    zeichneKreis();
    syncUi();
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
    var karte = document.getElementById("map");
    if (!karte) return false;

    var style = el("style");
    style.textContent =
      ".naehe-block{border:1px solid #2a2f36;border-radius:10px;background:#14181d;" +
      "margin:0 0 .5rem;padding:0}" +
      ".naehe-block>summary{cursor:pointer;padding:.55rem .7rem;font-size:.85rem;" +
      "letter-spacing:.02em;text-transform:uppercase;color:#9aa4b2;list-style:none}" +
      ".naehe-block>summary::-webkit-details-marker{display:none}" +
      ".naehe-block>summary::before{content:'▸ ';color:#2ea043}" +
      ".naehe-block[open]>summary::before{content:'▾ '}" +
      ".naehe-innen{padding:0 .7rem .7rem}" +
      ".naehe-zeile{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin:.35rem 0}" +
      ".naehe-block button{cursor:pointer}" +
      ".naehe-km{margin-left:.4rem;color:#2ea043;font-weight:600;white-space:nowrap}" +
      ".naehe-info{margin:.35rem 0 0;font-size:.82rem;color:#9aa4b2}" +
      ".naehe-info.fehler{color:#f85149;font-weight:600}" +
      ".naehe-abo{font-size:.8rem;color:#9aa4b2;margin:.35rem 0 0}" +
      ".naehe-tipp{font-size:.78rem;color:#9aa4b2}";
    document.head.appendChild(style);

    var details = el("details", { class: "naehe-block" });
    ui.summary = el("summary", {}, "In meiner Nähe");
    details.appendChild(ui.summary);

    var innen = el("div", { class: "naehe-innen" });
    var zeile1 = el("div", { class: "naehe-zeile" });
    ui.standort = el("button", { type: "button", class: "ghost" }, "📍 Mein Standort");
    ui.standort.title = "Standort einmalig abfragen — wird auf ~110 m gerundet " +
                        "übertragen, nicht gespeichert";
    zeile1.appendChild(ui.standort);
    ui.aus = el("button", { type: "button", class: "ghost" }, "✕ Nähe aus");
    ui.aus.style.display = "none";
    zeile1.appendChild(ui.aus);
    innen.appendChild(zeile1);

    var zeile2 = el("div", { class: "naehe-zeile" });
    ui.plz = el("input", { type: "search", placeholder: "Postleitzahl oder Ortsteil…",
                           autocomplete: "off", style: "flex:1 1 10rem" });
    ui.plzBtn = el("button", { type: "button", class: "ghost" }, "Übernehmen");
    zeile2.appendChild(ui.plz);
    zeile2.appendChild(ui.plzBtn);
    innen.appendChild(zeile2);

    var zeile3 = el("div", { class: "naehe-zeile" });
    zeile3.appendChild(el("label", { for: "naehe-km", style: "font-size:.85rem" }, "Umkreis"));
    ui.km = el("select", { id: "naehe-km" });
    KM_WAHL.forEach(function (k) {
      var o = el("option", { value: String(k) }, k + " km");
      if (k === STD_KM) o.setAttribute("selected", "selected");
      ui.km.appendChild(o);
    });
    zeile3.appendChild(ui.km);
    innen.appendChild(zeile3);

    innen.appendChild(el("p", { class: "naehe-tipp" },
      "Tipp: Ein Klick auf die Karte setzt den Mittelpunkt — die Liste zeigt dann " +
      "alle Termine in diesem Umkreis, mit den Filtern, die gerade gesetzt sind."));

    ui.info = el("p", { class: "naehe-info" });
    innen.appendChild(ui.info);

    var abo = el("div", { class: "naehe-abo" });
    ui.aboLink = el("a", { href: "#", target: "_blank", rel: "noopener" },
                    "Diese Auswahl als Kalender abonnieren");
    abo.appendChild(ui.aboLink);
    innen.appendChild(abo);

    details.appendChild(innen);
    ui.details = details;

    // Über der Karte einhängen — als Geschwister des Karten-Containers, damit
    // Layout und Größe der Karte unangetastet bleiben.
    var anker = karte.parentElement || karte;
    var eltern = (anker.parentElement && anker.parentElement !== document.body)
      ? anker.parentElement : anker;
    eltern.insertBefore(details, anker);

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
    // Immer aktiv: der Klick auf die Karte ist der einfachste Weg zum Mittelpunkt.
    map.on("click", function (ev) {
      setze(runde(ev.latlng.lat, 2), runde(ev.latlng.lng, 2),
            (ui.km && ui.km.value) || STD_KM);
    });
  }

  function syncUi() {
    if (!ui.km) return;
    var aktiv = !!(merker.lat && merker.lon);
    ui.aus.style.display = aktiv ? "" : "none";
    if (merker.km) ui.km.value = merker.km;
    if (aktiv) {
      ui.details.setAttribute("open", "open");
      ui.summary.textContent = "In meiner Nähe — " + (merker.km || STD_KM) + " km";
    } else {
      ui.summary.textContent = "In meiner Nähe — Standort, Postleitzahl oder Kartenpunkt";
    }
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
      zeigeFehler("Dieser Browser kann keinen Standort liefern — bitte " +
                  "Postleitzahl eingeben oder Punkt auf der Karte wählen.");
      return;
    }
    setzeInfo("Standort wird einmalig abgefragt…", "ok");
    navigator.geolocation.getCurrentPosition(function (pos) {
      // Drei Nachkommastellen (rund 110 m): genau genug für 1 km Umkreis,
      // kein genauer Aufenthaltsort in den Server-Logs.
      setze(runde(pos.coords.latitude, 3), runde(pos.coords.longitude, 3),
            (ui.km && ui.km.value) || STD_KM);
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
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          var f = res.d && res.d.detail;
          if (f && f.fehler) f = f.fehler.join(" ");
          zeigeFehler("Nicht gefunden: " + (f || "keine Termine mit Position") +
                      " — anderen Ort versuchen oder Punkt auf der Karte wählen.");
          return;
        }
        setze(res.d.lat, res.d.lon, (ui.km && ui.km.value) || STD_KM);
        setzeInfo("Mittelpunkt aus " + res.d.termine + " Terminen mit Position gesetzt.", "ok");
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
        if (!merker.lat && ui.details) {
          ui.details.setAttribute("open", "open");
          setzeInfo("Karte auf Ihren Standort gesetzt. Mit „Mein Standort“ oder einem " +
                    "Klick auf die Karte die Umkreissuche starten.", "ok");
        }
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
  // Umkreis (die Liste zeigte alle Termine statt der nahen), und ein zweiter
  // Ladeaufruf überholte sich mit dem ersten.
  ausUrl();
  haengeEin();
  haengeRenderEin();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
