// 키보드 단축키: 숫자 1·2·3 → 추천 행동 버튼, Enter 또는 / → 입력창으로.
// 입력창에 글을 쓰는 중에는 가로채지 않는다.
(function () {
  function typing(el) {
    return el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.isContentEditable);
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || typing(document.activeElement)) return;
    if (e.key >= "1" && e.key <= "3") {
      var buttons = Array.prototype.filter.call(
        document.querySelectorAll("#actions button"),
        function (b) { return b.offsetParent !== null && !b.disabled; });
      var b = buttons[Number(e.key) - 1];
      if (!b) return;
      e.preventDefault();
      b.classList.add("pressed");
      setTimeout(function () { b.classList.remove("pressed"); }, 300);
      b.click();
    } else if (e.key === "/" || (e.key === "Enter" && (!document.activeElement || document.activeElement === document.body))) {
      var box = document.querySelector("#msg textarea");
      if (box && !box.disabled) { e.preventDefault(); box.focus(); }
    }
  });
})();
