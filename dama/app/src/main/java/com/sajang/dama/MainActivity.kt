package com.sajang.dama

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Cancel
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.InsertLink
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.getWorkInfoByIdFlow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.net.URI
import java.util.UUID
import java.util.concurrent.TimeUnit

private val Mint = Color(0xFF20B486)
private val LightColors = androidx.compose.material3.lightColorScheme(
    primary = Mint,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE5F7EF),
    onPrimaryContainer = Color(0xFF084C36),
    background = Color.White,
    onBackground = Color(0xFF17201D),
    surface = Color.White,
    onSurface = Color(0xFF17201D),
    surfaceVariant = Color(0xFFF1F5F3),
    onSurfaceVariant = Color(0xFF5D6964),
    outline = Color(0xFFD5DDD9),
)

class MainActivity : ComponentActivity() {
    private val controller = DamaController()
    private var incoming by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        incoming = extractSharedText(intent)
        setContent {
            val permission = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestPermission()
            ) { }
            LaunchedEffect(Unit) {
                if (Build.VERSION.SDK_INT >= 33 &&
                    ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.POST_NOTIFICATIONS
                    ) != PackageManager.PERMISSION_GRANTED
                ) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            LaunchedEffect(incoming) {
                incoming?.let { controller.acceptShared(it) }
                incoming = null
            }
            MaterialTheme(colorScheme = LightColors) {
                DamaScreen(controller)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        incoming = extractSharedText(intent)
    }

    private fun extractSharedText(intent: Intent?): String? =
        if (intent?.action == Intent.ACTION_SEND) intent.getStringExtra(Intent.EXTRA_TEXT) else null
}

data class MediaItem(
    val url: String,
    val title: String,
    val quality: String,
    val type: String,
    val sourcePage: String,
    val blocked: String? = null,
)

data class UiState(
    val url: String = "",
    val analyzing: Boolean = false,
    val items: List<MediaItem> = emptyList(),
    val selected: Int = 0,
    val error: String? = null,
    val workId: UUID? = null,
    val workTitle: String = "",
    val workProgress: Int = 0,
    val workState: WorkInfo.State? = null,
    val workMessage: String = "",
)

class DamaController {
    private val analyzer = MediaAnalyzer()
    private val mutable = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = mutable

    fun setUrl(value: String) {
        mutable.value = mutable.value.copy(url = value, error = null)
    }

    fun acceptShared(value: String) {
        val url = Regex("https?://\\S+", RegexOption.IGNORE_CASE).find(value)?.value ?: value
        setUrl(url)
        analyze()
    }

    fun analyze() {
        val url = mutable.value.url.trim()
        if (url.isBlank()) {
            mutable.value = mutable.value.copy(error = "영상 주소를 넣어주세요.")
            return
        }
        AppScope.launch {
            mutable.value = mutable.value.copy(analyzing = true, items = emptyList(), error = null)
            runCatching { analyzer.analyze(url) }
                .onSuccess { result ->
                    mutable.value = mutable.value.copy(
                        analyzing = false,
                        items = result,
                        selected = result.indexOfFirst { it.blocked == null }.coerceAtLeast(0)
                    )
                }
                .onFailure {
                    mutable.value = mutable.value.copy(
                        analyzing = false,
                        error = it.message ?: "영상을 찾지 못했습니다."
                    )
                }
        }
    }

    fun select(index: Int) {
        mutable.value = mutable.value.copy(selected = index, error = null)
    }

    fun consumeError() {
        mutable.value = mutable.value.copy(error = null)
    }

    fun startDownload(context: Context) {
        val item = mutable.value.items.getOrNull(mutable.value.selected) ?: return
        if (item.blocked != null) {
            mutable.value = mutable.value.copy(error = item.blocked)
            return
        }
        val input = Data.Builder()
            .putString(DownloadWorker.KEY_URL, item.url)
            .putString(DownloadWorker.KEY_TITLE, item.title)
            .putString(DownloadWorker.KEY_TYPE, item.type)
            .putString(DownloadWorker.KEY_REFERER, item.sourcePage)
            .build()
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(input)
            .build()
        val manager = WorkManager.getInstance(context)
        manager.enqueueUniqueWork("dama_${item.url.hashCode()}", ExistingWorkPolicy.REPLACE, request)
        mutable.value = mutable.value.copy(
            workId = request.id,
            workTitle = item.title,
            workProgress = 0,
            workState = WorkInfo.State.ENQUEUED,
            workMessage = "대기 중"
        )
        AppScope.launch {
            manager.getWorkInfoByIdFlow(request.id).collect { info ->
                val message = when (info.state) {
                    WorkInfo.State.SUCCEEDED -> "저장 완료"
                    WorkInfo.State.FAILED -> info.outputData.getString(DownloadWorker.KEY_MESSAGE) ?: "저장 실패"
                    WorkInfo.State.CANCELLED -> "취소됨"
                    WorkInfo.State.RUNNING -> info.progress.getString(DownloadWorker.KEY_MESSAGE) ?: "다운로드 중"
                    WorkInfo.State.BLOCKED -> "네트워크 대기"
                    WorkInfo.State.ENQUEUED -> "대기 중"
                }
                mutable.value = mutable.value.copy(
                    workProgress = info.progress.getInt(DownloadWorker.KEY_PROGRESS, 0),
                    workState = info.state,
                    workMessage = message,
                    error = if (info.state == WorkInfo.State.FAILED) message else mutable.value.error,
                )
            }
        }
    }

    fun cancel(context: Context) {
        mutable.value.workId?.let { WorkManager.getInstance(context).cancelWorkById(it) }
    }
}

private object AppScope {
    private val scope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + Dispatchers.Main.immediate
    )
    fun launch(block: suspend kotlinx.coroutines.CoroutineScope.() -> Unit) = scope.launch(block = block)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DamaScreen(controller: DamaController) {
    val state by controller.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(state.error) {
        state.error?.let {
            snackbar.showSnackbar(it)
            controller.consumeError()
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier.size(36.dp).clip(RoundedCornerShape(11.dp))
                                .background(MaterialTheme.colorScheme.primary),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(Icons.Outlined.Download, null, tint = Color.White)
                        }
                        Spacer(Modifier.width(10.dp))
                        Text("담아", fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                )
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp)
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        "보고 있는 영상을\n간단히 저장하세요",
                        fontSize = 29.sp,
                        lineHeight = 36.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                    Text(
                        "브라우저에서 공유하거나 영상 주소를 붙여넣으세요.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = state.url,
                        onValueChange = controller::setUrl,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("영상 주소") },
                        placeholder = { Text("https://...") },
                        leadingIcon = { Icon(Icons.Outlined.InsertLink, null) },
                        trailingIcon = {
                            IconButton(onClick = {
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                val text = clipboard.primaryClip?.getItemAt(0)
                                    ?.coerceToText(context)?.toString().orEmpty()
                                if (text.isNotBlank()) controller.setUrl(text)
                            }) { Icon(Icons.Outlined.ContentPaste, "붙여넣기") }
                        },
                        singleLine = true,
                        shape = RoundedCornerShape(15.dp)
                    )
                    Button(
                        onClick = controller::analyze,
                        enabled = !state.analyzing && state.url.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().height(54.dp),
                        shape = RoundedCornerShape(15.dp)
                    ) {
                        Icon(Icons.Outlined.Search, null)
                        Spacer(Modifier.width(8.dp))
                        Text(if (state.analyzing) "찾는 중..." else "영상 찾기", fontWeight = FontWeight.Bold)
                    }
                }
            }
            if (state.items.isNotEmpty()) {
                item {
                    Text("찾은 영상", fontSize = 21.sp, fontWeight = FontWeight.Bold)
                }
                item {
                    val selected = state.items.getOrNull(state.selected) ?: state.items.first()
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                        shape = RoundedCornerShape(20.dp)
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(17.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box(
                                Modifier.size(58.dp).clip(RoundedCornerShape(16.dp))
                                    .background(Color(0xFF202724)),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(Icons.Outlined.Movie, null, tint = Color.White, modifier = Modifier.size(30.dp))
                            }
                            Spacer(Modifier.width(14.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    selected.title,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    "${selected.quality} · ${if (selected.type == "HLS") "HLS" else "직접 영상"}",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    fontSize = 13.sp
                                )
                            }
                        }
                    }
                }
                item {
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        state.items.forEachIndexed { index, item ->
                            FilterChip(
                                selected = index == state.selected,
                                onClick = { controller.select(index) },
                                enabled = item.blocked == null,
                                label = { Text(item.quality) }
                            )
                        }
                    }
                }
                item {
                    val item = state.items.getOrNull(state.selected)
                    Button(
                        onClick = { controller.startDownload(context) },
                        enabled = item?.blocked == null,
                        modifier = Modifier.fillMaxWidth().height(56.dp),
                        shape = RoundedCornerShape(15.dp)
                    ) {
                        Icon(Icons.Outlined.Download, null)
                        Spacer(Modifier.width(8.dp))
                        Text(item?.blocked ?: "다운로드", fontWeight = FontWeight.ExtraBold)
                    }
                }
            }
            if (state.workId != null && state.workState != null) {
                item {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
                        shape = RoundedCornerShape(20.dp)
                    ) {
                        Column(Modifier.padding(17.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    Modifier.size(44.dp).clip(CircleShape)
                                        .background(MaterialTheme.colorScheme.primary),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(
                                        if (state.workState == WorkInfo.State.SUCCEEDED) Icons.Outlined.CheckCircle else Icons.Outlined.Download,
                                        null,
                                        tint = Color.White
                                    )
                                }
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(state.workTitle, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(state.workMessage, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                if (state.workState?.isFinished == false) {
                                    IconButton(onClick = { controller.cancel(context) }) {
                                        Icon(Icons.Outlined.Cancel, "취소")
                                    }
                                }
                            }
                            if (state.workState?.isFinished == false) {
                                LinearProgressIndicator(
                                    progress = { state.workProgress / 100f },
                                    modifier = Modifier.fillMaxWidth().height(7.dp).clip(CircleShape)
                                )
                            }
                        }
                    }
                }
            }
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                    shape = RoundedCornerShape(18.dp)
                ) {
                    Text(
                        "저장 위치  ·  내 파일 > 동영상 > 담아\nMP4 · WebM · 비암호화 HLS 지원",
                        modifier = Modifier.padding(16.dp),
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

private class MediaAnalyzer {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    suspend fun analyze(raw: String): List<MediaItem> = withContext(Dispatchers.IO) {
        val input = Regex("https?://\\S+", RegexOption.IGNORE_CASE).find(raw.trim())?.value
            ?.trimEnd('.', ',', ')', ']', '}', '>', '"', '\'') ?: raw.trim()
        require(input.startsWith("http://") || input.startsWith("https://")) {
            "http 또는 https 주소를 넣어주세요."
        }
        val request = Request.Builder().url(input)
            .header("User-Agent", DownloadWorker.USER_AGENT)
            .header("Accept", "text/html,application/xhtml+xml,application/vnd.apple.mpegurl,video/*,*/*")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("페이지를 열 수 없습니다. HTTP ${response.code}")
            val finalUrl = response.request.url.toString()
            val type = response.header("Content-Type").orEmpty().lowercase()
            if (type.startsWith("video/") || isDirect(finalUrl)) {
                return@withContext listOf(
                    MediaItem(finalUrl, titleFromUrl(finalUrl), quality(finalUrl), "DIRECT", finalUrl)
                )
            }
            val body = response.body?.byteStream()?.readNBytes(3_000_000) ?: ByteArray(0)
            val text = body.toString(Charsets.UTF_8)
            if (type.contains("mpegurl") || finalUrl.contains(".m3u8", true) || text.trimStart().startsWith("#EXTM3U")) {
                return@withContext parseHls(finalUrl, text, titleFromUrl(finalUrl), finalUrl)
            }
            val doc = Jsoup.parse(text, finalUrl)
            val title = doc.selectFirst("meta[property=og:title]")?.attr("content")
                ?.takeIf { it.isNotBlank() } ?: doc.title().ifBlank { titleFromUrl(finalUrl) }
            val urls = linkedSetOf<String>()
            doc.select("video[src],source[src]").forEach { it.absUrl("src").takeIf(String::isNotBlank)?.let(urls::add) }
            doc.select("meta[property=og:video],meta[property=og:video:url],meta[name=twitter:player:stream]")
                .forEach { element -> resolve(finalUrl, element.attr("content"))?.let(urls::add) }
            Regex("https?://[^\\s\\\"'<>]+?\\.(?:mp4|webm|mov|m4v|m3u8)(?:\\?[^\\s\\\"'<>]*)?", RegexOption.IGNORE_CASE)
                .findAll(text).map { it.value.replace("\\/", "/") }.forEach(urls::add)
            val out = mutableListOf<MediaItem>()
            urls.take(24).forEach { url ->
                when {
                    url.contains(".m3u8", true) -> {
                        val hls = fetchText(url, finalUrl)
                        out += parseHls(url, hls, title, finalUrl)
                    }
                    isDirect(url) -> out += MediaItem(url, title, quality(url), "DIRECT", finalUrl)
                }
            }
            out.distinctBy { it.url }.sortedByDescending { qualityNumber(it.quality) }
                .ifEmpty { error("페이지에서 직접 재생 주소를 찾지 못했습니다.") }
        }
    }

    private fun parseHls(url: String, text: String, title: String, source: String): List<MediaItem> {
        val lines = text.lines().map(String::trim).filter(String::isNotEmpty)
        val encrypted = lines.any { it.startsWith("#EXT-X-KEY", true) && !it.contains("METHOD=NONE", true) }
        val variants = mutableListOf<MediaItem>()
        lines.forEachIndexed { index, line ->
            if (line.startsWith("#EXT-X-STREAM-INF", true)) {
                val next = lines.drop(index + 1).firstOrNull { !it.startsWith("#") } ?: return@forEachIndexed
                val child = resolve(url, next) ?: return@forEachIndexed
                val height = Regex("RESOLUTION=\\d+x(\\d+)", RegexOption.IGNORE_CASE)
                    .find(line)?.groupValues?.getOrNull(1)
                variants += MediaItem(
                    child,
                    title,
                    height?.let { "${it}p" } ?: "자동",
                    "HLS",
                    source,
                    if (encrypted) "암호화된 HLS는 저장할 수 없습니다." else null
                )
            }
        }
        return variants.ifEmpty {
            listOf(MediaItem(url, title, "원본", "HLS", source, if (encrypted) "암호화된 HLS는 저장할 수 없습니다." else null))
        }
    }

    private fun fetchText(url: String, referer: String): String {
        val request = Request.Builder().url(url).header("User-Agent", DownloadWorker.USER_AGENT)
            .header("Referer", referer).build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("재생목록 요청 실패: HTTP ${response.code}")
            return response.body?.string().orEmpty()
        }
    }

    private fun isDirect(url: String) = Regex("(?i)\\.(mp4|webm|mov|m4v)(?:$|[?#])").containsMatchIn(url)
    private fun quality(url: String) = Regex("(?i)(2160|1440|1080|720|480|360)p").find(url)?.groupValues?.get(1)?.plus("p") ?: "원본"
    private fun qualityNumber(label: String) = label.removeSuffix("p").toIntOrNull() ?: 0
    private fun titleFromUrl(url: String) = runCatching { URI(url).path.substringAfterLast('/').ifBlank { "영상" } }.getOrDefault("영상")
    private fun resolve(base: String, value: String): String? = runCatching { URI(base).resolve(value.trim()).toString() }
        .getOrNull()?.takeIf { it.startsWith("http://") || it.startsWith("https://") }
}
