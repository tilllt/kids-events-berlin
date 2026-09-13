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
    var pfad = aboPfad(p);
    var gruppe = document.getElementById("naehe-abo");
    if (!gruppe) {
      box.appendChild(document.createTextNode(" · "));
      gruppe = el("span", { id: "naehe-abo", class: "naehe-abo" });
      var oeffnen = el("button", { type: "button", class: "naehe-abo-knopf",
        title: "Zeigt, was abonniert wird — mit der Adresse zum Einfügen" },
        "Kalender abonnieren");
      oeffnen.addEventListener("click", function () { zeigeAboDialog(pfad); });
      gruppe.appendChild(oeffnen);
      box.appendChild(gruppe);
    }
  }

  /* ---------- Kalender-Abo ---------- */

  /* Beschriftungen für die Anzeige im Fenster — die Schlüssel sind die der App.
     `zeitstufe` heißt in der Oberfläche „Uhrzeit". */
  var ANZEIGE = { bezirk: "Bezirk", altersband: "Altersgruppe", uhrzeit: "Uhrzeit",
                  zeitstufe: "Uhrzeit",
                  kostenlos: "Nur kostenlose Termine", quelle: "Quelle", q: "Suche",
                  ort: "Ort", umkreis_km: "Umkreis", wochen: "Zeitraum" };

  /* Zeitraum-Filter gehören nicht ins Abo: Heute/Morgen/Demnächst sind
     Ansichtssache, das Abo deckt immer die nächsten 21 Tage ab. */
  var NICHT_IM_ABO = ["zeitraum", "von", "bis", "limit", "seite", "lat", "lon", "umkreis_km"];

  /* Die App nennt den Uhrzeit-Filter in ihrer Adresse `zeitstufe`, die
     Kalender-Schnittstelle liest `uhrzeit`. Ohne diese Übersetzung kam der
     Filter im Abo nie an (gemessen: 579 statt 222 Termine). */
  var ABO_UMBENENNEN = { zeitstufe: "uhrzeit" };

  /* Abo-Adresse aus der Adresse der aktuellen Ansicht — mit AUSSCHLUSSliste,
     nicht mit Positivliste: Eine feste Liste hat hier zuletzt stillschweigend
     den Uhrzeit-Filter (zeitstufe) verschluckt. So kommt jeder Filter mit, auch
     künftige. */
  function aboPfad(p) {
    var abo = new URLSearchParams();
    p.forEach(function (wert, key) {
      if (!wert || NICHT_IM_ABO.indexOf(key) !== -1) return;
      abo.set(ABO_UMBENENNEN[key] || key, wert);
    });
    if (aktiv()) {
      abo.set("lat", merker.lat); abo.set("lon", merker.lon);
      abo.set("umkreis_km", merker.km || String(STD_KM));
    }
    abo.set("wochen", "3");                       // 3 Wochen = 21 Tage
    return "/api/kalender.ics?" + abo.toString();
  }

  function kopiere(text, knopf, zurueck) {
    var fertig = function () {
      knopf.textContent = "kopiert";
      setTimeout(function () { knopf.textContent = zurueck || "Adresse kopieren"; }, 2000);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(fertig, function () {
        window.prompt("Adresse zum Abonnieren:", text);
      });
    } else {
      window.prompt("Adresse zum Abonnieren:", text);
    }
  }

  function zeigeAboDialog(pfad) {
    var alt = document.getElementById("naehe-abo-dialog");
    if (alt) alt.remove();
    var p = new URLSearchParams(pfad.split("?")[1] || "");
    var adresse = location.origin + pfad;
    var huelle = el("div", { id: "naehe-abo-dialog", class: "naehe-modal-huelle" });
    var kasten = el("div", { class: "naehe-modal", role: "dialog", "aria-modal": "true",
                             "aria-label": "Kalender abonnieren" });
    kasten.appendChild(el("h3", {}, "Kalender abonnieren"));
    kasten.appendChild(el("p", {},
      "Abonniert wird genau diese Auswahl — unabhängig davon, welcher Zeitraum gerade " +
      "in der Ansicht gewählt ist. Das Abo umfasst immer die nächsten 21 Tage und " +
      "aktualisiert sich danach von selbst; die Termine kommen ohne Ihr Zutun nach."));

    var liste = el("ul", { class: "naehe-modal-filter" });
    liste.appendChild(el("li", {}, "Zeitraum: die nächsten 21 Tage (fest)"));
    // Jeden Filter zeigen, der in der Adresse steht — nichts stillschweigend
    // weglassen. Unbekannte Schlüssel werden mit ihrem Namen genannt.
    p.forEach(function (wert, key) {
      if (!wert || key === "wochen" || key === "lat" || key === "lon") return;
      if (key === "umkreis_km") {
        liste.appendChild(el("li", {}, "Umkreis: " + wert + " km um den gewählten Punkt"));
        return;
      }
      liste.appendChild(el("li", {}, (ANZEIGE[key] || key) + ": " + wert));
    });
    kasten.appendChild(liste);

    var feld = el("input", { type: "text", readonly: "readonly", class: "naehe-modal-url",
                             value: adresse, "aria-label": "Abo-Adresse" });
    feld.addEventListener("focus", function () { this.select(); });
    kasten.appendChild(feld);

    var knopfreihe = el("div", { class: "naehe-modal-knoepfe" });
    var kopie = el("button", { type: "button", class: "btn primary" }, "Abo-Adresse kopieren");
    kopie.addEventListener("click", function () { kopiere(adresse, this, "Abo-Adresse kopieren"); });
    knopfreihe.appendChild(kopie);
    // Für iPhone/iPad: dort öffnet webcal:// den Abo-Dialog. Auf Android gibt es
    // dafür keinen Handler — dort ist der Kopier-Weg der richtige, deshalb steht
    // er als eigener Hinweis darunter statt als toter Knopf daneben.
    knopfreihe.appendChild(el("a", { class: "btn",
      href: "webcal://" + location.host + pfad }, "Auf iPhone/iPad öffnen"));
    var zu = el("button", { type: "button", class: "btn" }, "Schließen");
    zu.addEventListener("click", function () { huelle.remove(); });
    knopfreihe.appendChild(zu);
    kasten.appendChild(knopfreihe);

    kasten.appendChild(el("p", { class: "naehe-modal-hinweis" },
      "Android-Kalender: „Adresse kopieren“ und in der Kalender-App unter " +
      "„Kalender abonnieren“ bzw. „Per URL hinzufügen“ einfügen."));

    huelle.appendChild(kasten);
    huelle.addEventListener("click", function (ev) { if (ev.target === huelle) huelle.remove(); });
    document.addEventListener("keydown", function esc(ev) {
      if (ev.key === "Escape") { huelle.remove(); document.removeEventListener("keydown", esc); }
    });
    document.body.appendChild(huelle);
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
      ".naehe-slider-wrap{display:flex;align-items:center;gap:10px;margin-top:10px}" +
      ".naehe-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9aa4b2}" +
      // Schieberegler statt fester km-Schaltflächen: die Knöpfe waren in der
      // Höhe angeschnitten (Rückmeldung), außerdem sind Zwischenwerte möglich.
      ".naehe-slider{flex:1 1 auto;-webkit-appearance:none;appearance:none;height:22px;" +
      "border-radius:3px;outline:none;" +
      // Die Spur wird als 6px hohes Band mittig gezeichnet, das Element bleibt
      // 22px hoch — sonst schneidet das Feld den 20px-Griff ab (gemessen).
      "background:linear-gradient(90deg,rgba(46,160,67,.55),rgba(46,160,67,.18)) center/100% 6px no-repeat}" +
      ".naehe-slider::-webkit-slider-thumb{-webkit-appearance:none;width:20px;height:20px;border-radius:50%;" +
      "background:#4ac26b;border:2px solid #0d1117;cursor:pointer}" +
      ".naehe-slider::-moz-range-thumb{width:18px;height:18px;border-radius:50%;background:#4ac26b;" +
      "border:2px solid #0d1117;cursor:pointer}" +
      ".naehe-slider:focus-visible{outline:2px solid rgba(46,160,67,.6);outline-offset:3px}" +
      ".naehe-kmwert{min-width:52px;text-align:right;color:#4ac26b;font-weight:600;font-size:12.5px}" +
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

    var z3 = el("div", { class: "naehe-slider-wrap" });
    z3.appendChild(el("span", { class: "naehe-label" }, "Umkreis"));
    ui.km = el("input", { type: "range", class: "naehe-slider", min: "1", max: "20",
                          step: "1", value: String(STD_KM),
                          "aria-label": "Umkreis in Kilometern" });
    ui.kmWert = el("span", { class: "naehe-kmwert" }, STD_KM + " km");
    // Beim Ziehen nur die Anzeige mitführen, erst beim Loslassen laden — sonst
    // löste jede Zwischenstufe einen Abruf aus.
    ui.km.addEventListener("input", function () {
      ui.kmWert.textContent = this.value + " km";
    });
    ui.km.addEventListener("change", function () {
      waehleUmkreis(Number(this.value));
    });
    z3.appendChild(ui.km);
    z3.appendChild(ui.kmWert);
    body.appendChild(z3);

    ui.info = el("p", { class: "naehe-info" });
    body.appendChild(ui.info);

    details.appendChild(body);
    ui.details = details;
    ui.summary = summary;

    // Platz je Bildschirmgröße (Nutzerwunsch):
    //   Handy   -> direkt über der Karte
    //   Desktop -> in der linken Spalte unter den übrigen Filtern
    var MOBIL = window.matchMedia("(max-width: 820px)");
    function platzieren() {
      var eltern, ziel;
      if (MOBIL.matches) {
        eltern = document.getElementById("content") || document.body;
        ziel = document.getElementById("mapwrap");
      } else {
        eltern = document.getElementById("filters") || document.body;
        ziel = null;
      }
      if (details.parentNode !== eltern || (ziel && details.nextSibling !== ziel)) {
        if (ziel) eltern.insertBefore(details, ziel);
        else eltern.appendChild(details);
      }
    }
    platzieren();
    if (MOBIL.addEventListener) MOBIL.addEventListener("change", platzieren);

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
      if (ui.km) ui.km.value = merker.km || STD_KM;
      if (ui.kmWert) ui.kmWert.textContent = (merker.km || STD_KM) + " km";
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
