(() => {
  const sent = new Set();

  function report(value) {
    if (!value) return;
    let url;
    try {
      url = new URL(value, document.baseURI).href;
    } catch (_) {
      return;
    }
    if (!/^https?:/i.test(url)) return;
    if (!/(?:\.m3u8|\.mp4|\.webm|\.mov|\.m4v)(?:$|[?#])/i.test(url)) return;
    if (sent.has(url)) return;
    sent.add(url);
    browser.runtime.sendMessage({
      kind: "dama-media",
      url,
      pageUrl: location.href,
      title: document.title || "영상",
      userAgent: navigator.userAgent || ""
    }).catch(() => {});
  }

  function scan() {
    document.querySelectorAll("video, audio, source").forEach((node) => {
      report(node.currentSrc);
      report(node.src);
      report(node.getAttribute && node.getAttribute("src"));
    });
  }

  document.addEventListener("play", scan, true);
  document.addEventListener("loadedmetadata", scan, true);
  document.addEventListener("canplay", scan, true);
  document.addEventListener("DOMContentLoaded", scan, { once: true });
  setTimeout(scan, 800);
  setTimeout(scan, 2400);
})();
