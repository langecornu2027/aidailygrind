// Share buttons.
// "Post on LinkedIn" in one click:
//   - phone: opens the share sheet with the image AND the text (pick LinkedIn, post)
//   - computer: opens LinkedIn with the text already written, and copies the image,
//     so you only press ⌘V / Ctrl+V in the post box (LinkedIn does not let a website
//     attach an image for you). If copying an image is not possible, it downloads it.
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

  // Copy the card as a PNG image (the only image type browsers can put on the clipboard)
  function copyImage(url) {
    if (!navigator.clipboard || !window.ClipboardItem) return Promise.reject();
    var png = fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
      return createImageBitmap(blob);
    }).then(function (bitmap) {
      var canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d").drawImage(bitmap, 0, 0);
      return new Promise(function (resolve) { canvas.toBlob(resolve, "image/png"); });
    });
    // Give the promise to ClipboardItem right away, so it still counts as part of the click
    return navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
  }

  function download(url) {
    var a = document.createElement("a");
    a.href = url;
    a.download = "ai-daily-grind.jpg";
    document.body.appendChild(a);
    a.click();
    a.remove();
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

  function track(method, box) {
    if (window.grindTrack) window.grindTrack("share", {
      method: method,
      content_type: document.body.dataset.pageType === "token" || box.closest(".token") ? "token" : "edition",
      item_id: box.dataset.url,
    });
  }

  document.querySelectorAll(".share").forEach(function (box) {
    var url = box.dataset.url;
    box.querySelectorAll("a:not(.post-linkedin)").forEach(function (a) {
      a.addEventListener("click", function () {
        track(a.hasAttribute("download") ? "image" : a.textContent.trim().toLowerCase(), box);
      });
    });
    var post = box.dataset.post || box.dataset.text;
    // Hashtags only on manual shares (the automatic LinkedIn page post has none)
    var fullPost = post + "\n\n" + (box.dataset.shareUrl || url) + (box.dataset.hashtags ? "\n\n" + box.dataset.hashtags : "");
    var card = box.dataset.card;

    // Get the image ready before the click (phones need it at once for the share sheet)
    if (isPhone && card) {
      box.addEventListener("touchstart", function () { loadCard(card); }, { passive: true, once: true });
      if (box.closest(".hero")) loadCard(card);
    }

    var li = box.querySelector(".post-linkedin");
    if (li) {
      li.addEventListener("click", function (event) {
        track("linkedin", box);
        var file = cards[card];
        if (isPhone && file instanceof File && navigator.canShare && navigator.canShare({ files: [file] })) {
          event.preventDefault();
          copy(fullPost); // in case the app drops the text
          navigator.share({ files: [file], text: fullPost, title: box.dataset.text }).catch(function () {});
          return;
        }
        // Computer: the link opens LinkedIn with the text written; the image goes on the clipboard
        if (card) {
          copyImage(card).then(function () {
            note(box, "✓ LinkedIn opened with your text, and the image is copied. Click in the post box, press ⌘V (Mac) or Ctrl+V (Windows), then Post.");
          }).catch(function () {
            download(card);
            note(box, "✓ LinkedIn opened with your text. The image is downloaded: add it with the 🖼️ button in LinkedIn, then Post.");
          });
        }
      });
    }

    var copyPost = box.querySelector(".copy-post");
    if (copyPost) copyPost.addEventListener("click", function () {
      track("copy_post", box);
      copy(fullPost).then(function () { flash(copyPost, "Copied ✓", "Copy post"); });
    });

    var copyLink = box.querySelector(".copy-link");
    if (copyLink) {
      if (navigator.share) copyLink.textContent = "More…";
      copyLink.addEventListener("click", function () {
        track(navigator.share ? "native_share" : "copy_link", box);
        if (navigator.share) {
          navigator.share({ title: box.dataset.text, text: box.dataset.text, url: url }).catch(function () {});
        } else {
          copy(url).then(function () { flash(copyLink, "Copied ✓", "Copy link"); });
        }
      });
    }
  });
})();
