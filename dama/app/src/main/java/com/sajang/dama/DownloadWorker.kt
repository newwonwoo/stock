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

class DownloadWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    companion object {
        const val KEY_URL = "url"
        const val KEY_TITLE = "title"
        const val KEY_TYPE = "type"
        const val KEY_REFERER = "referer"
        const val KEY_PROGRESS = "progress"
        const val KEY_MESSAGE = "message"
        const val KEY_FAILURE_CODE = "failure_code"
        const val KEY_FAILURE_TITLE = "failure_title"
        const val KEY_FAILURE_DETAIL = "failure_detail"
        const val KEY_FAILURE_ACTION = "failure_action"
        const val KEY_FAILURE_TECHNICAL = "failure_technical"
        const val USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
        private const val CHANNEL_ID = "dama_downloads"
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val url = inputData.getString(KEY_URL) ?: return@withContext Result.failure()
        val title = inputData.getString(KEY_TITLE).orEmpty().ifBlank { "영상" }
        val type = inputData.getString(KEY_TYPE).orEmpty()
        val referer = inputData.getString(KEY_REFERER)

        runCatching {
            reportProgress(title, 1, "다운로드 준비 중", true)
            val result = if (type == "HLS") {
                downloadHls(url, title, referer)
            } else {
                downloadDirect(url, title, referer)
            }
            setProgress(workDataOf(KEY_PROGRESS to 100, KEY_MESSAGE to "저장 완료"))
            completeNotification(title, result.uri, result.mime)
            Result.success(workDataOf(KEY_PROGRESS to 100, KEY_MESSAGE to "저장 완료"))
        }.getOrElse { error ->
            val report = FailureAnalyzer.analyze(error)
            Result.failure(
                workDataOf(
                    KEY_MESSAGE to report.title,
                    KEY_FAILURE_CODE to report.code,
                    KEY_FAILURE_TITLE to report.title,
                    KEY_FAILURE_DETAIL to report.detail,
                    KEY_FAILURE_ACTION to report.action,
                    KEY_FAILURE_TECHNICAL to report.technical,
                )
            )
        }
    }

    private suspend fun downloadDirect(url: String, title: String, referer: String?): Saved {
        reportProgress(title, 5, "영상 서버 연결 중", true)
        client.newCall(request(url, referer)).execute().use { response ->
            if (!response.isSuccessful) error("다운로드 실패: HTTP ${response.code}")
            val body = response.body ?: error("빈 응답입니다.")
            val mime = response.header("Content-Type")?.substringBefore(';')
                ?.takeIf { it.startsWith("video/") } ?: mimeFromUrl(url)
            val extension = extension(mime, url)
            val expected = body.contentLength().takeIf { it > 0 }
            reportProgress(
                title,
                10,
                expected?.let { "파일 크기 확인 · ${formatBytes(it)}" } ?: "파일 크기 확인 불가 · 저장 시작",
                expected == null,
            )
            val target = createTarget(fileName(title, extension), mime)
            var readTotal = 0L
            try {
                applicationContext.contentResolver.openOutputStream(target, "w")!!.use { output ->
                    body.byteStream().use { input ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE * 8)
                        var last = -1
                        while (true) {
                            if (isStopped) error("다운로드가 취소되었습니다.")
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                            readTotal += count
                            val progress = expected?.let {
                                (10 + ((readTotal * 89.0) / it)).roundToInt().coerceIn(10, 99)
                            } ?: 20
                            if (progress >= last + 2 || expected == null && readTotal % (2L * 1024 * 1024) < count) {
                                val message = expected?.let {
                                    "저장 중 · ${formatBytes(readTotal)} / ${formatBytes(it)}"
                                } ?: "저장 중 · ${formatBytes(readTotal)}"
                                reportProgress(title, progress, message, expected == null)
                                last = progress
                            }
                        }
                    }
                }
                reportProgress(title, 99, "파일 등록 중", false)
                publish(target)
                return Saved(target, mime)
            } catch (t: Throwable) {
                applicationContext.contentResolver.delete(target, null, null)
                throw t
            }
        }
    }

    private suspend fun downloadHls(url: String, title: String, referer: String?): Saved {
        reportProgress(title, 4, "HLS 재생목록 요청 중", true)
        val first = fetchText(url, referer)
        val mediaUrl: String
        val playlist: String
        if (first.contains("#EXT-X-STREAM-INF", true)) {
            reportProgress(title, 8, "HLS 화질 목록 분석 중", true)
            mediaUrl = chooseBest(url, first)
            playlist = fetchText(mediaUrl, referer ?: url)
        } else {
            mediaUrl = url
            playlist = first
        }
        if (playlist.lines().any { it.startsWith("#EXT-X-KEY", true) && !it.contains("METHOD=NONE", true) }) {
            error("암호화된 HLS는 저장할 수 없습니다.")
        }
        if (playlist.contains("#EXT-X-BYTERANGE", true)) {
            error("바이트 범위 HLS는 아직 지원하지 않습니다.")
        }

        reportProgress(title, 12, "영상 조각 목록 분석 중", true)
        val init = Regex("#EXT-X-MAP:.*URI=\"([^\"]+)\"", RegexOption.IGNORE_CASE)
            .find(playlist)?.groupValues?.getOrNull(1)?.let { resolve(mediaUrl, it) }
        val segments = playlist.lines().map(String::trim)
            .filter { it.isNotBlank() && !it.startsWith("#") }
            .mapNotNull { resolve(mediaUrl, it) }
        if (segments.isEmpty()) error("영상 조각을 찾지 못했습니다.")

        val fragmented = init != null || segments.any { it.contains(".m4s", true) }
        val mime = if (fragmented) "video/mp4" else "video/mp2t"
        val ext = if (fragmented) "mp4" else "ts"
        val target = createTarget(fileName(title, ext), mime)
        val all = listOfNotNull(init) + segments
        reportProgress(title, 15, "영상 조각 ${all.size}개 확인", false)
        try {
            applicationContext.contentResolver.openOutputStream(target, "w")!!.use { output ->
                all.forEachIndexed { index, segment ->
                    if (isStopped) error("다운로드가 취소되었습니다.")
                    client.newCall(request(segment, referer ?: mediaUrl)).execute().use { response ->
                        if (!response.isSuccessful) error("영상 조각 실패: HTTP ${response.code}")
                        val body = response.body ?: error("빈 영상 조각입니다.")
                        body.byteStream().use { input ->
                            val buffer = ByteArray(DEFAULT_BUFFER_SIZE * 8)
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                output.write(buffer, 0, count)
                            }
                        }
                    }
                    val progress = 15 + (((index + 1) * 84.0) / all.size).roundToInt().coerceIn(0, 84)
                    reportProgress(
                        title,
                        progress,
                        "영상 조각 ${index + 1} / ${all.size} 저장 중",
                        false,
                    )
                }
            }
            reportProgress(title, 99, "파일 등록 중", false)
            publish(target)
            return Saved(target, mime)
        } catch (t: Throwable) {
            applicationContext.contentResolver.delete(target, null, null)
            throw t
        }
    }

    private fun chooseBest(master: String, text: String): String {
        val lines = text.lines().map(String::trim).filter(String::isNotBlank)
        val variants = mutableListOf<Pair<Int, String>>()
        lines.forEachIndexed { index, line ->
            if (line.startsWith("#EXT-X-STREAM-INF", true)) {
                val next = lines.drop(index + 1).firstOrNull { !it.startsWith("#") } ?: return@forEachIndexed
                val height = Regex("RESOLUTION=\\d+x(\\d+)", RegexOption.IGNORE_CASE)
                    .find(line)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
                resolve(master, next)?.let { variants += height to it }
            }
        }
        return variants.maxByOrNull { it.first }?.second ?: error("HLS 화질 목록을 찾지 못했습니다.")
    }

    private fun fetchText(url: String, referer: String?): String {
        client.newCall(request(url, referer)).execute().use { response ->
            if (!response.isSuccessful) error("재생목록 요청 실패: HTTP ${response.code}")
            return response.body?.string().orEmpty()
        }
    }

    private fun request(url: String, referer: String?): Request {
        val builder = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .header("Accept", "*/*")
        referer?.takeIf(String::isNotBlank)?.let { builder.header("Referer", it) }
        return builder.build()
    }

    private fun createTarget(name: String, mime: String): Uri {
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, name)
            put(MediaStore.Video.Media.MIME_TYPE, mime)
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/담아")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        return applicationContext.contentResolver.insert(
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
            values,
        ) ?: error("저장 공간을 열 수 없습니다.")
    }

    private fun publish(uri: Uri) {
        applicationContext.contentResolver.update(
            uri,
            ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) },
            null,
            null,
        )
    }

    private suspend fun reportProgress(
        title: String,
        progress: Int,
        message: String,
        indeterminate: Boolean,
    ) {
        setProgress(workDataOf(KEY_PROGRESS to progress, KEY_MESSAGE to message))
        setForeground(foreground(title, progress, message, indeterminate))
    }

    private fun foreground(
        title: String,
        progress: Int,
        message: String,
        indeterminate: Boolean,
    ): ForegroundInfo {
        channel()
        val cancel = WorkManager.getInstance(applicationContext).createCancelPendingIntent(id)
        val open = PendingIntent.getActivity(
            applicationContext,
            id.hashCode(),
            Intent(applicationContext, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title)
            .setContentText(message)
            .setProgress(100, progress, indeterminate)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "취소", cancel)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                id.hashCode(),
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(id.hashCode(), notification)
        }
    }

    private fun completeNotification(title: String, uri: Uri, mime: String) {
        channel()
        val open = PendingIntent.getActivity(
            applicationContext,
            id.hashCode() + 1,
            Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, mime)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("저장 완료")
            .setContentText(title)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        (applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .notify(id.hashCode(), notification)
    }

    private fun channel() {
        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "영상 다운로드", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun fileName(title: String, ext: String): String {
        val clean = title.substringBeforeLast('.', title)
            .replace(Regex("[\\/:*?\"<>|\\p{Cntrl}]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
            .take(70)
            .ifBlank { "영상" }
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

    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1024L * 1024L * 1024L -> "%.2f GB".format(bytes / (1024.0 * 1024.0 * 1024.0))
        bytes >= 1024L * 1024L -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
        bytes >= 1024L -> "%.1f KB".format(bytes / 1024.0)
        else -> "$bytes B"
    }

    private fun resolve(base: String, value: String): String? = runCatching {
        URI(base).resolve(value.trim()).toString()
    }.getOrNull()?.takeIf { it.startsWith("http://") || it.startsWith("https://") }

    private data class Saved(val uri: Uri, val mime: String)
}
