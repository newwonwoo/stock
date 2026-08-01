const sent = new Set();
const requestHeaders = new Map();

function headersToObject(headers) {
  const out = {};
  (headers || []).forEach((h) => {
    if (!h || !h.name) return;
    out[h.name.toLowerCase()] = h.value || "";
  });
  return out;
}

function mediaByUrl(url) {
  return /(?:\.m3u8|\.mp4|\.webm|\.mov|\.m4v)(?:$|[?#])/i.test(url || "");
}

function mediaByType(headers) {
  const type = (headersToObject(headers)["content-type"] || "").toLowerCase();
  return type.includes("application/vnd.apple.mpegurl") ||
    type.includes("application/x-mpegurl") ||
    type.includes("audio/mpegurl") ||
    type.startsWith("video/mp4") ||
    type.startsWith("video/webm") ||
    type.startsWith("video/quicktime");
}

function publish(data) {
  if (!data || !data.url || !/^https?:/i.test(data.url)) return;
  const key = data.url;
  if (sent.has(key)) return;
  sent.add(key);
  browser.runtime.sendNativeMessage("dama.capture", JSON.stringify(data)).catch(() => {});
}

browser.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    requestHeaders.set(details.requestId, headersToObject(details.requestHeaders));
    if (mediaByUrl(details.url)) {
      const h = requestHeaders.get(details.requestId) || {};
      publish({
        url: details.url,
        pageUrl: details.documentUrl || details.originUrl || "",
        title: "",
        requestType: details.type || "",
        cookie: h["cookie"] || "",
        referer: h["referer"] || details.documentUrl || details.originUrl || "",
        origin: h["origin"] || "",
        userAgent: h["user-agent"] || ""
      });
    }
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders"]
);

browser.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (!mediaByUrl(details.url) && !mediaByType(details.responseHeaders)) return;
    const h = requestHeaders.get(details.requestId) || {};
    publish({
      url: details.url,
      pageUrl: details.documentUrl || details.originUrl || "",
      title: "",
      requestType: details.type || "",
      cookie: h["cookie"] || "",
      referer: h["referer"] || details.documentUrl || details.originUrl || "",
      origin: h["origin"] || "",
      userAgent: h["user-agent"] || ""
    });
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

browser.webRequest.onCompleted.addListener(
  (details) => requestHeaders.delete(details.requestId),
  { urls: ["<all_urls>"] }
);

browser.webRequest.onErrorOccurred.addListener(
  (details) => requestHeaders.delete(details.requestId),
  { urls: ["<all_urls>"] }
);

browser.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.kind !== "dama-media") return;
  publish({
    url: message.url || "",
    pageUrl: message.pageUrl || (sender.tab && sender.tab.url) || "",
    title: message.title || "",
    requestType: "dom",
    cookie: "",
    referer: message.pageUrl || "",
    origin: "",
    userAgent: message.userAgent || ""
  });
});
