package com.sajang.dama.next

import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import java.net.URI
import java.time.Instant
import java.util.UUID

class DiagnosticSession(
    private val sessionId: String = UUID.randomUUID().toString(),
    private val startedAtMillis: Long = System.currentTimeMillis()
) {
    private val events = mutableListOf<DiagnosticEvent>()

    @Synchronized
    fun record(
        category: String,
        message: String,
        detail: String? = null
    ) {
        events += DiagnosticEvent(
            elapsedMillis = System.currentTimeMillis() - startedAtMillis,
            category = category.take(80),
            message = redactDiagnosticText(message).take(600),
            detail = detail
                ?.let(::redactDiagnosticText)
                ?.take(2_000)
        )
    }

    @Synchronized
    fun writeToCache(context: Context): File {
        val directory = File(context.cacheDir, "diagnostics").apply { mkdirs() }
        val file = File(directory, "dama-$sessionId.txt")
        file.writeText(render())
        return file
    }

    @Synchronized
    internal fun render(): String = buildString {
        appendLine("DAMA_DIAGNOSTIC_V1")
        appendLine("session=$sessionId")
        appendLine("startedAt=${Instant.ofEpochMilli(startedAtMillis)}")
        appendLine("eventCount=${events.size}")
        appendLine()
        events.forEachIndexed { index, event ->
            append(index + 1)
            append(". +")
            append(event.elapsedMillis)
            append("ms [")
            append(event.category)
            append("] ")
            appendLine(event.message)
            event.detail?.let {
                appendLine("   detail=$it")
            }
        }
    }
}

private data class DiagnosticEvent(
    val elapsedMillis: Long,
    val category: String,
    val message: String,
    val detail: String?
)

internal fun redactDiagnosticText(input: String): String {
    val urlPattern = Regex("https?://[^\\s<>()]+", RegexOption.IGNORE_CASE)
    val urlsRedacted = urlPattern.replace(input) { match ->
        sanitizeUrlForDiagnostics(match.value)
    }

    return urlsRedacted
        .replace(
            Regex("(?i)(cookie|authorization|token|signature|sig|key)=([^\\s&;]+)"),
            "$1=<redacted>"
        )
        .replace(
            Regex("(?i)(cookie|authorization):\\s*[^\\r\\n]+"),
            "$1: <redacted>"
        )
}

internal fun sanitizeUrlForDiagnostics(raw: String): String {
    return runCatching {
        val uri = URI(raw.trimEnd('.', ',', ')', ']', '}', '>', '\"', '\''))
        URI(
            uri.scheme,
            null,
            uri.host,
            uri.port,
            uri.path,
            null,
            null
        ).toString()
    }.getOrElse {
        raw.substringBefore('?').substringBefore('#')
    }
}

fun shareDiagnosticFile(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        file
    )
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, "담아 진단 로그")
        putExtra(Intent.EXTRA_STREAM, uri)
        clipData = ClipData.newRawUri("담아 진단 로그", uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(intent, "진단 로그 공유"))
}
