// A message's page to print (webmail-print.html): the browser's print dialog opens once its
// pictures have loaded, and the tab closes itself when printing is done or cancelled.
(function () {
  window.addEventListener("load", function () {
    window.print();
  });
  window.addEventListener("afterprint", function () {
    window.close();
  });
})();
