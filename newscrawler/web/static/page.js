// Tanya Berita: the few behaviours htmx does not cover. No reader text lives here; every
// label comes from the server's copy table (core/web_copy.py, SYS-101).
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function ask(question) {
    var input = $("query-input");
    input.value = question;
    $("search-form").requestSubmit();
  }

  function resetFilter(field) {
    if (field === "topic") { $("filter-topic").value = ""; }
    if (field === "source") { $("filter-source").value = ""; }
    if (field === "rentang") {
      document.querySelector('input[name="rentang"][value=""]').checked = true;
      $("filter-from").value = "";
      $("filter-to").value = "";
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target.closest("button");
    if (!target) { return; }

    // An example question is asked as it stands.
    if (target.classList.contains("example")) {
      ask(target.dataset.question);
      return;
    }
    // "Hapus filter" under an empty result: drop every filter and ask the same question again.
    if (target.hasAttribute("data-clear-filters")) {
      ["topic", "source", "rentang"].forEach(resetFilter);
      ask(target.dataset.question);
      return;
    }
    // A removable chip under the search: the filter no longer applies to the next question.
    if (target.dataset.removeFilter) {
      resetFilter(target.dataset.removeFilter);
      target.closest("li").remove();
      $("query-input").focus();
      return;
    }
    // "Pertanyaan baru" (SYS-97): the thread and its session are gone; the next question
    // is sent with no history (the search form has no session id, the follow-up form is removed).
    if (target.id === "new-question") {
      $("thread").innerHTML = "";
      var followup = $("followup");
      var empty = document.createElement("div");
      empty.id = "followup";
      followup.replaceWith(empty);
      $("active-filters").innerHTML = "";
      var input = $("query-input");
      input.value = "";
      input.focus();
    }
  });

  // After a turn is added, move focus to its question so the reader (and a screen reader)
  // lands on the new answer.
  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id !== "thread") { return; }
    var headings = event.detail.target.querySelectorAll(".turn-q");
    var last = headings[headings.length - 1];
    if (last) {
      last.focus({ preventScroll: true });
      last.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  });
})();
