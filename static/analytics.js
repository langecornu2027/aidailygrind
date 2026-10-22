// Google Analytics 4, only with consent (Québec Law 25, GDPR).
// Nothing loads and no cookie is set until the visitor clicks "Accept".
// The choice is kept in this browser; "Cookie settings" in the footer reopens the banner.
// Other scripts send events with window.grindTrack(name, params); it does nothing without consent.
(function () {
  var GA_ID = "G-BWGDWH0G16";
  var KEY = "grind-consent"; // "granted" | "denied"
  var page = document.body.dataset;
  var loaded = false;
  var queue = [];

  function getChoice() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function setChoice(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }

  function load() {
    if (loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { dataLayer.push(arguments); };
    gtag("consent", "default", {
      ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
      analytics_storage: "granted",
    });
    gtag("js", new Date());
    gtag("config", GA_ID, {
      content_group: page.pageType || "page",          // edition | token | page
      edition_date: page.edition || undefined,
      token_number: page.token || undefined,
      token_tag: page.tag || undefined,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
    });
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + GA_ID;
    document.head.appendChild(s);
    queue.forEach(function (e) { gtag("event", e[0], e[1]); });
    queue = [];
  }

  window.grindTrack = function (name, params) {
    params = params || {};
    params.content_group = page.pageType || "page";
    if (page.edition) params.edition_date = page.edition;
    if (loaded) window.gtag("event", name, params);
    else if (getChoice() === "granted") queue.push([name, params]);
  };

  function removeGaCookies() {
    document.cookie.split(";").forEach(function (c) {
      var name = c.split("=")[0].trim();
      if (/^_ga/.test(name)) {
        ["", "." + location.hostname, location.hostname].forEach(function (d) {
          document.cookie = name + "=; Max-Age=0; path=/" + (d ? "; domain=" + d : "");
        });
      }
    });
  }

  function banner() {
    if (document.querySelector(".consent-banner")) return;
    var box = document.createElement("div");
    box.className = "consent-banner";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Cookie choice");
    box.innerHTML =
      '<p><strong>🍪 Can we count visits?</strong> We use Google Analytics cookies to see which stories ' +
      'people read, listen to and share. No ads, no selling. ' +
      '<a href="privacy.html#analytics">Privacy Policy</a></p>' +
      '<div class="consent-actions">' +
      '<button type="button" class="consent-no">Decline</button>' +
      '<button type="button" class="consent-yes button">Accept</button></div>';
    document.body.appendChild(box);
    box.querySelector(".consent-yes").addEventListener("click", function () {
      setChoice("granted");
      box.remove();
      load();
    });
    box.querySelector(".consent-no").addEventListener("click", function () {
      setChoice("denied");
      box.remove();
      removeGaCookies();
      if (loaded) location.reload(); // stop GA that was running (cookies are cleaned again on load)
    });
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest(".cookie-settings");
    if (link) { e.preventDefault(); banner(); }
  });

  var choice = getChoice();
  if (choice === "granted") load();
  else if (choice === "denied") removeGaCookies(); // clean up anything left from before
  else banner();

  document.addEventListener("submit", function (e) {
    if (e.target.matches("form.subscribe")) window.grindTrack("sign_up", { method: "email" });
  });

  // Confirmed subscription lands on subscribed.html
  if (page.pageType === "subscribed") window.grindTrack("subscribe_confirmed", { method: "email" });
})();
