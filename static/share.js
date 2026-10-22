// Share buttons.
// "Post on LinkedIn" in one click:
//   - phone: opens the share sheet with the image AND the text (pick LinkedIn, post)
//   - computer: opens LinkedIn with the text already written, and downloads the image
//     (LinkedIn does not let a website attach an image for you, so you add it with 🖼️)
// The text is also copied, in case the app drops it.
(function () {
  var isPhone = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  var cards = {}; // card url -> File, fetched ahead so the share sheet opens right away

  function loadCard(url) {
    if (!url || cards[url]) return;
    cards[url] = "loading";
    fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
      cards[url] = new File([blob], "ai-daily-grind.jpg", { type: "image/jpeg" });
    }).catch(function () { delete cards[url]; });
  }

  function copy(text) {
    if (navigator.clipboard) return navigator.clipboard.writeText(text).catch(function () {});
    return Promise.resolve();
  }

  function flash(button, text, label) {
    button.textContent = text;
    setTimeout(function () { button.textContent = label; }, 2500);
  }

  function note(box, text) {
    var n = box.querySelector(".share-note");
    if (!n) {
      n = document.createElement("p");
      n.className = "share-note";
      box.appendChild(n);
    }
    n.textContent = text;
  }

  document.querySelectorAll(".share").forEach(function (box) {
    var url = box.dataset.url;
    var post = box.dataset.post || box.dataset.text;
    var fullPost = post + "\n\n" + url;
    var card = box.dataset.card;

    // Get the image ready before the click (phones need it at once for the share sheet)
    if (isPhone && card) {
      box.addEventListener("touchstart", function () { loadCard(card); }, { passive: true, once: true });
      if (box.closest(".hero")) loadCard(card);
    }

    var li = box.querySelector(".post-linkedin");
    if (li) {
      li.addEventListener("click", function (event) {
        copy(fullPost);
        var file = cards[card];
        if (isPhone && file instanceof File && navigator.canShare && navigator.canShare({ files: [file] })) {
          event.preventDefault();
          navigator.share({ files: [file], text: fullPost, title: box.dataset.text }).catch(function () {});
          return;
        }
        // Computer: the link opens LinkedIn with the text written; we also download the image
        if (card) {
          var a = document.createElement("a");
          a.href = card;
          a.download = "ai-daily-grind.jpg";
          document.body.appendChild(a);
          a.click();
          a.remove();
          note(box, "✓ LinkedIn opened with your text. The image is downloaded: add it with the 🖼️ button in LinkedIn, then Post.");
        }
      });
    }

    var copyPost = box.querySelector(".copy-post");
    if (copyPost) copyPost.addEventListener("click", function () {
      copy(fullPost).then(function () { flash(copyPost, "Copied ✓", "Copy post"); });
    });

    var copyLink = box.querySelector(".copy-link");
    if (copyLink) {
      if (navigator.share) copyLink.textContent = "More…";
      copyLink.addEventListener("click", function () {
        if (navigator.share) {
          navigator.share({ title: box.dataset.text, text: box.dataset.text, url: url }).catch(function () {});
        } else {
          copy(url).then(function () { flash(copyLink, "Copied ✓", "Copy link"); });
        }
      });
    }
  });
})();
