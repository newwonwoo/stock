package com.sajang.dama

import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URI
import java.util.concurrent.TimeUnit

object SourceProbe {
    data class Media(
        val url: String,
        val type: String,
        val quality: String,
    )

    data class Result(
        val media: List<Media>,
        val code: String,
        val detail: String,
    )

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    fun probe(pageUrl: String, userAgent: String, cookie: String): Result {
        val first = fetch(pageUrl, pageUrl, userAgent, cookie, false)
        if (first.code == 401) return Result(emptyList(), "AUTH_REQUIRED", "로그인 또는 연령 확인이 필요합니다.")
        if (first.code == 403) return Result(emptyList(), "WEBVIEW_OR_BOT_BLOCKED", "사이트가 내장 브라우저 또는 자동 요청을 차단했습니다.")
        if (first.code == 404) return Result(emptyList(), "PAGE_NOT_FOUND", "페이지가 없거나 주소가 만료됐습니다.")
        if (first.code !in 200..299) return Result(emptyList(), "PAGE_HTTP_${first.code}", "페이지 요청이 HTTP ${first.code}로 실패했습니다.")

        val normalized = normalize(first.body)
        if (normalized.contains("cf-chl-", true) || normalized.contains("Just a moment", true)) {
            return Result(emptyList(), "CHALLENGE_REQUIRED", "브라우저 보안 확인 화면을 통과해야 합니다.")
        }

        val found = linkedMapOf<String, Media>()
        collect(pageUrl, normalized, found)

        val endpoints = extractUrls(pageUrl, normalized)
            .filter {
                val lower = it.lowercase()
                lower.contains("media_definition") ||
                    lower.contains("get_media_definition") ||
                    lower.contains("get_media_definitions") ||
                    lower.contains("video/get_media")
            }
            .distinct()
            .take(8)

        endpoints.forEach { endpoint ->
            val get = fetch(endpoint, pageUrl, userAgent, cookie, false)
            if (get.code in 200..299) collect(endpoint, normalize(get.body), found)
            if (get.code == 405 || found.isEmpty()) {
                val post = fetch(endpoint, pageUrl, userAgent, cookie, true)
                if (post.code in 200..299) collect(endpoint, normalize(post.body), found)
            }
        }

        return if (found.isNotEmpty()) {
            Result(
                found.values.sortedWith(compareByDescending<Media> { qualityNumber(it.quality) }.thenBy { it.type }),
                "SOURCE_MEDIA_FOUND",
                "페이지 소스에서 영상 주소 ${found.size}개를 찾았습니다.",
            )
        } else {
            val code = when {
                normalized.contains("mediaDefinitions", true) || normalized.contains("flashvars", true) -> "MEDIA_DEFINITION_UNRESOLVED"
                normalized.contains("drm", true) || normalized.contains("widevine", true) -> "DRM_OR_ENCRYPTED"
                else -> "NO_MEDIA_IN_SOURCE"
            }
            val detail = when (code) {
                "MEDIA_DEFINITION_UNRESOLVED" -> "영상 메타데이터는 있으나 실제 재생 주소를 발급받지 못했습니다."
                "DRM_OR_ENCRYPTED" -> "DRM 또는 암호화 재생 방식이 감지됐습니다."
                else -> "초기 HTML과 연결된 미디어 정의에서 저장 가능한 주소를 찾지 못했습니다."
            }
            Result(emptyList(), code, detail)
        }
    }

    private fun fetch(
        url: String,
        referer: String,
        userAgent: String,
        cookie: String,
        post: Boolean,
    ): Response {
        return runCatching {
            val builder = Request.Builder()
                .url(url)
                .header("User-Agent", userAgent.ifBlank { DownloadWorker.USER_AGENT })
                .header("Accept", "text/html,application/json,application/xhtml+xml,*/*")
                .header("Referer", referer)
            if (cookie.isNotBlank()) builder.header("Cookie", cookie)
            val uri = URI(referer)
            if (!uri.scheme.isNullOrBlank() && !uri.authority.isNullOrBlank()) {
                builder.header("Origin", "${uri.scheme}://${uri.authority}")
            }
            if (post) builder.post(FormBody.Builder().build())
            client.newCall(builder.build()).execute().use { response ->
                Response(response.code, response.body?.string().orEmpty())
            }
        }.getOrElse { Response(0, it.message.orEmpty()) }
    }

    private fun collect(base: String, text: String, out: MutableMap<String, Media>) {
        extractUrls(base, text).forEach { url ->
            classify(url)?.let { media -> out.putIfAbsent(media.url, media) }
        }
    }

    private fun extractUrls(base: String, text: String): List<String> {
        val results = linkedSetOf<String>()
        Regex("https?://[^\\s\\\"'<>]+", RegexOption.IGNORE_CASE)
            .findAll(text)
            .map { cleanUrl(it.value) }
            .filter { it.startsWith("http://") || it.startsWith("https://") }
            .forEach(results::add)

        Regex("[\\\"'](/[^\\\"'<>\\s]+(?:\\.m3u8|\\.mp4|\\.webm|media_definition|get_media)[^\\\"'<>\\s]*)", RegexOption.IGNORE_CASE)
            .findAll(text)
            .mapNotNull { match -> resolve(base, cleanUrl(match.groupValues[1])) }
            .forEach(results::add)
        return results.toList()
    }

    private fun classify(url: String): Media? {
        val lower = url.lowercase()
        if (lower.startsWith("blob:") || lower.startsWith("data:")) return null
        if (Regex("(?i)\\.(m4s|ts|aac|jpg|jpeg|png|gif|webp)(?:$|[?#])").containsMatchIn(url)) return null
        val hls = lower.contains(".m3u8") ||
            lower.contains("format=m3u8") ||
            lower.contains("type=m3u8") ||
            (lower.contains("manifest") && lower.contains("hls")) ||
            lower.contains("master.m3u")
        val direct = Regex("(?i)\\.(mp4|webm|mov|m4v)(?:$|[?#])").containsMatchIn(url)
        if (!hls && !direct) return null
        val quality = Regex("(?i)(2160|1440|1080|720|480|360|240)p").find(url)?.groupValues?.getOrNull(1)?.plus("p")
            ?: Regex("(?i)(2160|1440|1080|720|480|360|240)(?:_|-|x)").find(url)?.groupValues?.getOrNull(1)?.plus("p")
            ?: if (hls) "자동" else "원본"
        return Media(url, if (hls) "HLS" else "DIRECT", quality)
    }

    private fun normalize(value: String): String = value
        .replace("\\/", "/")
        .replace("\\u0026", "&", true)
        .replace("\\u003d", "=", true)
        .replace("\\x2f", "/", true)
        .replace("&amp;", "&", true)
        .replace("\\\"", "\"")

    private fun cleanUrl(value: String): String = value
        .trim()
        .trimEnd(',', ';', ')', ']', '}', '\\')
        .replace("&amp;", "&", true)

    private fun resolve(base: String, value: String): String? = runCatching {
        URI(base).resolve(value).toString()
    }.getOrNull()?.takeIf { it.startsWith("http://") || it.startsWith("https://") }

    private fun qualityNumber(value: String): Int = value.removeSuffix("p").toIntOrNull() ?: 0

    private data class Response(val code: Int, val body: String)
}
