package com.sajang.dama

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URI
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

class BrowserDownloadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    companion object {
        const val KEY_URL = "url"
        const val KEY_TITLE = "title"
        const val KEY_TYPE = "type"
        const val KEY_REFERER = "referer"
        const val KEY_ORIGIN = "origin"
        const val KEY_COOKIE = "cookie"
        const val KEY_USER_AGENT = "user_agent"
        const val KEY_PROGRESS = "progress"
        const val KEY_MESSAGE = "message"
        const val KEY_FAILURE_CODE = "failure_code"
        const val KEY_FAILURE_TITLE = "failure_title"
        const val KEY_FAILURE_DETAIL = "failure_detail"
        const val KEY_FAILURE_ACTION = "failure_action"
        private const val CHANNEL_ID = "dama_browser_downloads"
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(50, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val url = inputData.getString(KEY_URL) ?: return@withContext failure(IllegalArgumentException("주소 없음"))
        val title = inputData.getString(KEY_TITLE).orEmpty().ifBlank { "영상" }
        runCatching {
            setForeground(foreground(title, 1, true))
            val saved = if (inputData.getString(KEY_TYPE) == "HLS") downloadHls(url, title) else downloadDirect(url, title)
            setProgress(workDataOf(KEY_PROGRESS to 100, KEY_MESSAGE to "저장 완료"))
            notifyComplete(title, saved.uri, saved.mime)
            Result.success()
        }.getOrElse { failure(it) }
    }

    private suspend fun downloadDirect(url: String, title: String): Saved {
        report(title, 5, "영상 서버 연결 중", true)
        client.newCall(request(url)).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code}")
            val body = response.body ?: error("빈 응답")
            val mime = response.header("Content-Type")?.substringBefore(';')?.takeIf { it.startsWith("video/") } ?: mimeFromUrl(url)
            val expected = body.contentLength().takeIf { it > 0 }
            val target = createTarget(fileName(title, extension(mime, url)), mime)
            var total = 0L
            try {
                applicationContext.contentResolver.openOutputStream(target, "w")!!.use { output ->
                    body.byteStream().use { input ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE * 8)
                        var last = -1
                        while (true) {
                            if (isStopped) error("다운로드 취소")
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                            total += count
                            val percent = expected?.let { (10 + total * 89.0 / it).roundToInt().coerceIn(10, 99) } ?: 20
                            if (percent >= last + 2) {
                                report(title, percent, expected?.let { "저장 중 · ${formatBytes(total)} / ${formatBytes(it)}" } ?: "저장 중 · ${formatBytes(total)}", expected == null)
                                last = percent
                            }
                        }
                    }
                }
                publish(target)
                return Saved(target, mime)
            } catch (t: Throwable) {
                applicationContext.contentResolver.delete(target, null, null)
                throw t
            }
        }
    }

    private suspend fun downloadHls(url: String, title: String): Saved {
        report(title, 4, "HLS 재생목록 확인 중", true)
        val first = fetchText(url)
        val mediaUrl: String
        val playlist: String
        if (first.contains("#EXT-X-STREAM-INF", true)) {
            mediaUrl = bestVariant(url, first)
            playlist = fetchText(mediaUrl)
        } else {
            mediaUrl = url
            playlist = first
        }
        if (playlist.lines().any { it.startsWith("#EXT-X-KEY", true) && !it.contains("METHOD=NONE", true) }) error("암호화된 HLS")
        if (playlist.contains("#EXT-X-BYTERANGE", true)) error("바이트 범위 HLS")
        val init = Regex("#EXT-X-MAP:.*URI=\"([^\"]+)\"", RegexOption.IGNORE_CASE).find(playlist)?.groupValues?.getOrNull(1)?.let { resolve(mediaUrl, it) }
        val segments = playlist.lines().map(String::trim).filter { it.isNotBlank() && !it.startsWith("#") }.mapNotNull { resolve(mediaUrl, it) }
        if (segments.isEmpty()) error("HLS 영상 조각 없음")
        val fragmented = init != null || segments.any { it.contains(".m4s", true) }
        val mime = if (fragmented) "video/mp4" else "video/mp2t"
        val target = createTarget(fileName(title, if (fragmented) "mp4" else "ts"), mime)
        val all = listOfNotNull(init) + segments
        try {
            applicationContext.contentResolver.openOutputStream(target, "w")!!.use { output ->
                all.forEachIndexed { index, segment ->
                    if (isStopped) error("다운로드 취소")
                    client.newCall(request(segment, mediaUrl)).execute().use { response ->
                        if (!response.isSuccessful) error("HLS 조각 HTTP ${response.code}")
                        response.body?.byteStream()?.use { input ->
                            val buffer = ByteArray(DEFAULT_BUFFER_SIZE * 8)
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                output.write(buffer, 0, count)
                            }
                        } ?: error("빈 HLS 조각")
                    }
                    val percent = (((index + 1) * 99.0) / all.size).roundToInt().coerceIn(1, 99)
                    report(title, percent, "영상 조각 ${index + 1}/${all.size} 저장 중", false)
                }
            }
            publish(target)
            return Saved(target, mime)
        } catch (t: Throwable) {
            applicationContext.contentResolver.delete(target, null, null)
            throw t
        }
    }

    private fun bestVariant(base: String, text: String): String {
        val lines = text.lines().map(String::trim).filter(String::isNotBlank)
        val variants = mutableListOf<Pair<Int, String>>()
        lines.forEachIndexed { index, line ->
            if (line.startsWith("#EXT-X-STREAM-INF", true)) {
                val next = lines.drop(index + 1).firstOrNull { !it.startsWith("#") } ?: return@forEachIndexed
                val score = Regex("RESOLUTION=\\d+x(\\d+)", RegexOption.IGNORE_CASE).find(line)?.groupValues?.getOrNull(1)?.toIntOrNull()
                    ?: Regex("BANDWIDTH=(\\d+)", RegexOption.IGNORE_CASE).find(line)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
                resolve(base, next)?.let { variants += score to it }
            }
        }
        return variants.maxByOrNull { it.first }?.second ?: error("HLS 화질 목록 없음")
    }

    private fun fetchText(url: String): String = client.newCall(request(url)).execute().use { response ->
        if (!response.isSuccessful) error("HTTP ${response.code}")
        response.body?.string().orEmpty()
    }

    private fun request(url: String, fallbackReferer: String? = null): Request {
        val referer = inputData.getString(KEY_REFERER).orEmpty().ifBlank { fallbackReferer.orEmpty() }
        val builder = Request.Builder().url(url)
            .header("User-Agent", inputData.getString(KEY_USER_AGENT).orEmpty().ifBlank { DownloadWorker.USER_AGENT })
            .header("Accept", "*/*")
        inputData.getString(KEY_COOKIE)?.takeIf { it.isNotBlank() }?.let { builder.header("Cookie", it) }
        inputData.getString(KEY_ORIGIN)?.takeIf { it.isNotBlank() }?.let { builder.header("Origin", it) }
        referer.takeIf { it.isNotBlank() }?.let { builder.header("Referer", it) }
        return builder.build()
    }

    private fun createTarget(name: String, mime: String): Uri {
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, name)
            put(MediaStore.Video.Media.MIME_TYPE, mime)
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/담아")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        return applicationContext.contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values) ?: error("저장 공간 열기 실패")
    }

    private fun publish(uri: Uri) {
        applicationContext.contentResolver.update(uri, ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }, null, null)
    }

    private suspend fun report(title: String, percent: Int, message: String, indeterminate: Boolean) {
        setProgress(workDataOf(KEY_PROGRESS to percent, KEY_MESSAGE to message))
        setForeground(foreground(title, percent, indeterminate))
    }

    private fun foreground(title: String, percent: Int, indeterminate: Boolean): ForegroundInfo {
        channel()
        val cancel = WorkManager.getInstance(applicationContext).createCancelPendingIntent(id)
        val open = PendingIntent.getActivity(applicationContext, id.hashCode(), Intent(applicationContext, BrowserCaptureActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)
            .setContentText(if (indeterminate) "다운로드 중" else "$percent%")
            .setProgress(100, percent, indeterminate)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "취소", cancel)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ForegroundInfo(id.hashCode(), notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else ForegroundInfo(id.hashCode(), notification)
    }

    private fun notifyComplete(title: String, uri: Uri, mime: String) {
        channel()
        val open = PendingIntent.getActivity(applicationContext, id.hashCode() + 1, Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mime)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("저장 완료")
            .setContentText(title)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        (applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(id.hashCode(), notification)
    }

    private fun channel() {
        (applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(NotificationChannel(CHANNEL_ID, "브라우저 영상 다운로드", NotificationManager.IMPORTANCE_LOW))
    }

    private fun failure(t: Throwable): Result {
        val m = t.message.orEmpty()
        val lower = m.lowercase()
        val report = when {
            "403" in lower -> Failure("ACCESS_FORBIDDEN", "접근이 거부되었습니다", "영상 서버가 브라우저 외 요청을 차단했습니다.", "페이지를 새로 열고 다시 재생한 직후 시도하세요.")
            "401" in lower -> Failure("AUTH_REQUIRED", "인증이 필요합니다", "현재 브라우저 세션으로 영상 서버 인증이 완료되지 않았습니다.", "페이지에서 로그인을 완료하고 영상을 다시 재생하세요.")
            "404" in lower -> Failure("MEDIA_URL_EXPIRED", "영상 주소가 만료됐습니다", "임시 영상 주소가 더 이상 유효하지 않습니다.", "페이지를 새로고침하고 다시 재생해 새 주소를 감지하세요.")
            "429" in lower -> Failure("RATE_LIMITED", "요청이 너무 많습니다", "영상 서버가 일시적으로 요청을 제한했습니다.", "잠시 후 페이지를 새로 열어 다시 시도하세요.")
            "암호화" in lower -> Failure("ENCRYPTED_HLS", "암호화된 영상입니다", "암호화 키가 필요한 HLS는 저장하지 않습니다.", "사이트의 공식 저장 기능을 이용하세요.")
            "바이트 범위" in lower -> Failure("HLS_BYTERANGE_UNSUPPORTED", "지원하지 않는 HLS 형식입니다", "바이트 범위 재생목록은 현재 저장할 수 없습니다.", "다른 화질 항목이 감지되면 선택해 보세요.")
            "조각" in lower -> Failure("HLS_SEGMENT_FAILED", "영상 조각 저장에 실패했습니다", "일부 HLS 조각에 접근하지 못했습니다.", "페이지에서 다시 재생해 새 주소를 감지하세요.")
            "timeout" in lower || "timed out" in lower -> Failure("NETWORK_TIMEOUT", "연결 시간이 초과됐습니다", "영상 서버 응답이 늦거나 연결이 불안정합니다.", "네트워크를 확인하고 다시 시도하세요.")
            "space" in lower || "enospc" in lower -> Failure("STORAGE_FULL", "저장 공간이 부족합니다", "휴대폰 저장 공간이 부족합니다.", "공간을 확보한 뒤 다시 시도하세요.")
            else -> Failure("DOWNLOAD_FAILED", "다운로드에 실패했습니다", m.ifBlank { "알 수 없는 오류가 발생했습니다." }, "페이지를 새로 열고 영상을 다시 재생한 뒤 시도하세요.")
        }
        return Result.failure(workDataOf(KEY_FAILURE_CODE to report.code, KEY_FAILURE_TITLE to report.title, KEY_FAILURE_DETAIL to report.detail, KEY_FAILURE_ACTION to report.action))
    }

    private fun fileName(title: String, ext: String): String {
        val clean = title.substringBeforeLast('.', title).replace(Regex("[\\/:*?\"<>|\\p{Cntrl}]"), " ").replace(Regex("\\s+"), " ").trim().take(70).ifBlank { "영상" }
        return "${clean}_${System.currentTimeMillis()}.$ext"
    }

    private fun mimeFromUrl(url: String) = when {
        url.contains(".webm", true) -> "video/webm"
        url.contains(".mov", true) -> "video/quicktime"
        else -> "video/mp4"
    }

    private fun extension(mime: String, url: String) = when {
        mime.contains("webm", true) || url.contains(".webm", true) -> "webm"
        mime.contains("quicktime", true) || url.contains(".mov", true) -> "mov"
        else -> "mp4"
    }

    private fun resolve(base: String, value: String): String? = runCatching { URI(base).resolve(value.trim()).toString() }.getOrNull()?.takeIf { it.startsWith("http://") || it.startsWith("https://") }
    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1024L * 1024 * 1024 -> "%.1f GB".format(bytes / (1024.0 * 1024 * 1024))
        bytes >= 1024L * 1024 -> "%.1f MB".format(bytes / (1024.0 * 1024))
        else -> "%.1f KB".format(bytes / 1024.0)
    }

    private data class Saved(val uri: Uri, val mime: String)
    private data class Failure(val code: String, val title: String, val detail: String, val action: String)
}
