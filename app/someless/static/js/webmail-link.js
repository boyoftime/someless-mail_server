// Mailboxes page, Webmail link (mailboxes.html): the webmail's login link to copy or share. The
// address chosen fills in the link, and what its copy button copies (copy-button.js); Share
// hands it to the phone's (or the computer's) share sheet, where there is one.
(function () {
  var dialog = document.getElementById("webmail-link-dialog");
  if (!dialog) return;
  var choice = dialog.querySelector("[data-webmail-link-for]");
  var shown = dialog.querySelector("[data-webmail-link] .copy-box-text");
  var copy = dialog.querySelector("[data-webmail-link] .copy-button");
  var share = dialog.querySelector("[data-webmail-share]");

  choice.addEventListener("change", function () {
    shown.textContent = choice.value;
    copy.dataset.copy = choice.value;
  });

  if (!navigator.share) return;
  share.hidden = false;
  share.addEventListener("click", function () {
    navigator.share({ title: "Someless Webmail", text: "Log in to your mailbox:", url: choice.value })
      .catch(function () {});   // closed without sharing
  });
})();
