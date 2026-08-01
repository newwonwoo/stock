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
import androidx.compose.foundation.layout.weight
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
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.InsertLink
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Troubleshoot
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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
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
import kotlinx.coroutines.flow.update
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
    error = Color(0xFFB3261E),
    errorContainer = Color(0xFFFFE9E6),
    onErrorContainer = Color(0xFF5C1712),
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
                if (
                    Build.VERSION.SDK_INT >= 33 &&
                    ContextCompat.checkSelfPermission(
                        this@MainActivity,
                        Manifest.permission.POST_NOTIFICATIONS,
                    ) != PackageManager.PERMISSION_GRANTED
                ) {
                    permission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
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
        if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)
        } else {
            null
        }
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
    val phase: String = "대기",
    val phaseProgress: Int = 0,
    val logs: List<String> = listOf("영상 주소를 넣거나 브라우저에서 공유하세요."),
    val failure: FailureReport? = null,
    val workId: UUID? = null,
    val workTitle: String = "",
    val workState: WorkInfo.State? = null,
)

class DamaController {
    private val analyzer = MediaAnalyzer()
    private val mutable = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = mutable

    fun setUrl(value: String) {
        mutable.update {
            it.copy(
                url = value,
                failure = null,
            )
        }
    }

    fun acceptShared(value: String) {
        val url = Regex("https?://\\S+", RegexOption.IGNORE_CASE).find(value)?.value ?: value
        setUrl(url)
        analyze()
    }

    fun analyze() {
        val url = mutable.value.url.trim()
        if (url.isBlank()) {
            val report = FailureAnalyzer.fromMessage("영상 주소가 비어 있습니다.", IllegalArgumentException())
            mutable.update {
                withLog(
                    it.copy(
                        phase = "분석 실패",
                        phaseProgress = 100,
                        failure = report,
                    ),
                    report.title,
                )
            }
            return
        }

        mutable.update {
            it.copy(
                analyzing = true,
                items = emptyList(),
                selected = 0,
                phase = "주소 확인 중",
                phaseProgress = 3,
                failure = null,
                workId = null,
                workState = null,
                logs = listOf("주소 형식을 확인하고 있습니다."),
            )
        }

        AppScope.launch {
            runCatching {
                analyzer.analyze(url) { stage, progress ->
                    mutable.update {
                        withLog(
                            it.copy(
                                phase = stage,
                                phaseProgress = progress,
                            ),
                            stage,
                        )
                    }
                }
            }.onSuccess { result ->
                mutable.update {
                    withLog(
                        it.copy(
                            analyzing = false,
                            items = result,
                            selected = result.indexOfFirst { item -> item.blocked == null }.coerceAtLeast(0),
                            phase = "분석 완료",
                            phaseProgress = 100,
                        ),
                        "저장 가능한 영상 ${result.count { item -> item.blocked == null }}개를 찾았습니다.",
                    )
                }
            }.onFailure { error ->
                val report = FailureAnalyzer.analyze(error)
                mutable.update {
                    withLog(
                        it.copy(
                            analyzing = false,
                            phase = "분석 실패",
                            phaseProgress = 100,
                            failure = report,
                        ),
                        "실패 원인 분석 완료 · ${report.code}",
                    )
                }
            }
        }
    }

    fun select(index: Int) {
        mutable.update { it.copy(selected = index, failure = null) }
    }

    fun startDownload(context: Context) {
        val item = mutable.value.items.getOrNull(mutable.value.selected) ?: return
        if (item.blocked != null) {
            val report = FailureAnalyzer.fromMessage(item.blocked)
            mutable.update {
                withLog(
                    it.copy(
                        phase = "다운로드 불가",
                        phaseProgress = 100,
                        failure = report,
                    ),
                    "실패 원인 분석 완료 · ${report.code}",
                )
            }
            return
        }

        val input = Data.Builder()
            .putString(DownloadWorker.KEY_URL, item.url)
            .putString(DownloadWorker.KEY_TITLE, item.title)
            .putString(DownloadWorker.KEY_TYPE, item.type)
            .putString(DownloadWorker.KEY_REFERER, item.sourcePage)
            .build()
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setInputData(input)
            .build()
        val manager = WorkManager.getInstance(context)
        manager.enqueueUniqueWork(
            "dama_${item.url.hashCode()}",
            ExistingWorkPolicy.REPLACE,
            request,
        )

        mutable.update {
            withLog(
                it.copy(
                    workId = request.id,
                    workTitle = item.title,
                    workState = WorkInfo.State.ENQUEUED,
                    phase = "다운로드 대기 중",
                    phaseProgress = 0,
                    failure = null,
                ),
                "다운로드 작업을 등록했습니다.",
            )
        }

        AppScope.launch {
            manager.getWorkInfoByIdFlow(request.id).collect { infoOrNull ->
                val info = infoOrNull ?: return@collect
                when (info.state) {
                    WorkInfo.State.ENQUEUED -> updateWork("다운로드 대기 중", 0, info.state)
                    WorkInfo.State.BLOCKED -> updateWork("네트워크 연결 대기 중", 0, info.state)
                    WorkInfo.State.RUNNING -> {
                        val message = info.progress.getString(DownloadWorker.KEY_MESSAGE)
                            ?: "다운로드 중"
                        val progress = info.progress.getInt(DownloadWorker.KEY_PROGRESS, 0)
                        updateWork(message, progress, info.state)
                    }
                    WorkInfo.State.SUCCEEDED -> {
                        updateWork("저장 완료", 100, info.state)
                    }
                    WorkInfo.State.FAILED -> {
                        val report = failureFromData(info.outputData)
                        mutable.update {
                            withLog(
                                it.copy(
                                    workState = info.state,
                                    phase = "저장 실패",
                                    phaseProgress = 100,
                                    failure = report,
                                ),
                                "실패 원인 분석 완료 · ${report.code}",
                            )
                        }
                    }
                    WorkInfo.State.CANCELLED -> {
                        val report = FailureAnalyzer.fromMessage("다운로드가 취소되었습니다.")
                        mutable.update {
                            withLog(
                                it.copy(
                                    workState = info.state,
                                    phase = "다운로드 취소됨",
                                    failure = report,
                                ),
                                "다운로드가 취소되었습니다.",
                            )
                        }
                    }
                }
            }
        }
    }

    fun cancel(context: Context) {
        mutable.value.workId?.let {
            WorkManager.getInstance(context).cancelWorkById(it)
            mutable.update { state ->
                withLog(state.copy(phase = "취소 요청 중"), "다운로드 취소를 요청했습니다.")
            }
        }
    }

    private fun updateWork(message: String, progress: Int, state: WorkInfo.State) {
        mutable.update {
            withLog(
                it.copy(
                    workState = state,
                    phase = message,
                    phaseProgress = progress,
                ),
                message,
            )
        }
    }

    private fun failureFromData(data: Data): FailureReport {
        val technical = data.getString(DownloadWorker.KEY_FAILURE_TECHNICAL)
            ?: data.getString(DownloadWorker.KEY_MESSAGE)
            ?: "기술 상세 없음"
        return FailureReport(
            code = data.getString(DownloadWorker.KEY_FAILURE_CODE) ?: "UNKNOWN",
            title = data.getString(DownloadWorker.KEY_FAILURE_TITLE) ?: "저장 실패",
            detail = data.getString(DownloadWorker.KEY_FAILURE_DETAIL)
                ?: "다운로드 과정에서 오류가 발생했습니다.",
            action = data.getString(DownloadWorker.KEY_FAILURE_ACTION)
                ?: "주소를 다시 분석한 뒤 재시도하세요.",
            technical = technical,
        )
    }

    private fun withLog(state: UiState, message: String): UiState {
        if (message.isBlank() || state.logs.lastOrNull() == message) return state
        return state.copy(logs = (state.logs + message).takeLast(7))
    }
}

private object AppScope {
    private val scope = kotlinx.coroutines.CoroutineScope(
        kotlinx.coroutines.SupervisorJob() + Dispatchers.Main.immediate
    )

    fun launch(block: suspend kotlinx.coroutines.CoroutineScope.() -> Unit) =
        scope.launch(block = block)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DamaScreen(controller: DamaController) {
    val state by controller.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val workActive = state.workState?.isFinished == false
    val showProgress = state.analyzing || state.workState != null || state.phase != "대기"

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier
                                .size(36.dp)
                                .clip(RoundedCornerShape(11.dp))
                                .background(MaterialTheme.colorScheme.primary),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Outlined.Download, null, tint = Color.White)
                        }
                        Spacer(Modifier.width(10.dp))
                        Text("담아", fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                ),
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        "보고 있는 영상을\n간단히 저장하세요",
                        fontSize = 29.sp,
                        lineHeight = 36.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                    Text(
                        "브라우저에서 공유하거나 영상 주소를 붙여넣으세요.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                            IconButton(
                                onClick = {
                                    val clipboard = context.getSystemService(
                                        Context.CLIPBOARD_SERVICE
                                    ) as ClipboardManager
                                    val text = clipboard.primaryClip?.getItemAt(0)
                                        ?.coerceToText(context)?.toString().orEmpty()
                                    if (text.isNotBlank()) controller.setUrl(text)
                                }
                            ) {
                                Icon(Icons.Outlined.ContentPaste, "붙여넣기")
                            }
                        },
                        singleLine = true,
                        shape = RoundedCornerShape(15.dp),
                    )
                    Button(
                        onClick = controller::analyze,
                        enabled = !state.analyzing && !workActive && state.url.isNotBlank(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(54.dp),
                        shape = RoundedCornerShape(15.dp),
                    ) {
                        Icon(Icons.Outlined.Search, null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (state.analyzing) "분석 중..." else "영상 찾기",
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }

            if (showProgress) {
                item {
                    ProgressPanel(
                        state = state,
                        workActive = workActive,
                        onCancel = { controller.cancel(context) },
                    )
                }
            }

            state.failure?.let { failure ->
                item {
                    FailurePanel(failure)
                }
            }

            if (state.items.isNotEmpty()) {
                item {
                    Text("찾은 영상", fontSize = 21.sp, fontWeight = FontWeight.Bold)
                }
                item {
                    val selected = state.items.getOrNull(state.selected) ?: state.items.first()
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant
                        ),
                        shape = RoundedCornerShape(20.dp),
                    ) {
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .padding(17.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                Modifier
                                    .size(58.dp)
                                    .clip(RoundedCornerShape(16.dp))
                                    .background(Color(0xFF202724)),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Outlined.Movie,
                                    null,
                                    tint = Color.White,
                                    modifier = Modifier.size(30.dp),
                                )
                            }
                            Spacer(Modifier.width(14.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    selected.title,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    "${selected.quality} · ${if (selected.type == "HLS") "HLS" else "직접 영상"}",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    fontSize = 13.sp,
                                )
                            }
                        }
                    }
                }
                item {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        state.items.forEachIndexed { index, item ->
                            FilterChip(
                                selected = index == state.selected,
                                onClick = { controller.select(index) },
                                enabled = item.blocked == null && !workActive,
                                label = { Text(item.quality) },
                            )
                        }
                    }
                }
                item {
                    val item = state.items.getOrNull(state.selected)
                    Button(
                        onClick = { controller.startDownload(context) },
                        enabled = item?.blocked == null && !workActive,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(56.dp),
                        shape = RoundedCornerShape(15.dp),
                    ) {
                        Icon(Icons.Outlined.Download, null)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            when {
                                workActive -> "다운로드 중"
                                item?.blocked != null -> "다운로드 불가"
                                else -> "다운로드"
                            },
                            fontWeight = FontWeight.ExtraBold,
                        )
                    }
                }
            }

            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                    shape = RoundedCornerShape(18.dp),
                ) {
                    Text(
                        "저장 위치  ·  내 파일 > 동영상 > 담아\nMP4 · WebM · 비암호화 HLS 지원",
                        modifier = Modifier.padding(16.dp),
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun ProgressPanel(
    state: UiState,
    workActive: Boolean,
    onCancel: () -> Unit,
) {
    val failed = state.failure != null
    val completed = state.phase == "저장 완료" || state.phase == "분석 완료"
    val container = if (failed) {
        MaterialTheme.colorScheme.errorContainer
    } else {
        MaterialTheme.colorScheme.primaryContainer
    }
    val content = if (failed) {
        MaterialTheme.colorScheme.onErrorContainer
    } else {
        MaterialTheme.colorScheme.onPrimaryContainer
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = container),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            Modifier.padding(17.dp),
            verticalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        when {
                            failed -> Icons.Outlined.ErrorOutline
                            completed -> Icons.Outlined.CheckCircle
                            else -> Icons.Outlined.Troubleshoot
                        },
                        null,
                        tint = Color.White,
                    )
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        state.phase,
                        fontWeight = FontWeight.ExtraBold,
                        color = content,
                    )
                    Text(
                        if (state.phaseProgress > 0) "진행률 ${state.phaseProgress}%" else "작업을 준비하고 있습니다.",
                        fontSize = 13.sp,
                        color = content.copy(alpha = 0.72f),
                    )
                }
                if (workActive) {
                    IconButton(onClick = onCancel) {
                        Icon(Icons.Outlined.Cancel, "취소", tint = content)
                    }
                }
            }

            if (state.phaseProgress > 0) {
                LinearProgressIndicator(
                    progress = { state.phaseProgress.coerceIn(0, 100) / 100f },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(CircleShape),
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(CircleShape),
                )
            }

            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                state.logs.takeLast(5).forEach { log ->
                    Row(verticalAlignment = Alignment.Top) {
                        Box(
                            Modifier
                                .padding(top = 6.dp)
                                .size(7.dp)
                                .clip(CircleShape)
                                .background(if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
                        )
                        Spacer(Modifier.width(9.dp))
                        Text(
                            log,
                            fontSize = 13.sp,
                            lineHeight = 18.sp,
                            color = content,
                        )
                    }
                }
            }

            if (workActive) {
                TextButton(onClick = onCancel, modifier = Modifier.align(Alignment.End)) {
                    Text("다운로드 취소")
                }
            }
        }
    }
}

@Composable
private fun FailurePanel(failure: FailureReport) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer
        ),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            Modifier.padding(17.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Outlined.ErrorOutline,
                    null,
                    tint = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.width(9.dp))
                Text(
                    "실패 원인 분석",
                    fontSize = 19.sp,
                    fontWeight = FontWeight.ExtraBold,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }

            Text(
                failure.title,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Text(
                "분류 · ${failure.code}",
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.72f),
            )

            DiagnosticRow("판단", failure.detail)
            DiagnosticRow("조치", failure.action)

            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "기술 상세",
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.7f),
                )
                Text(
                    failure.technical,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onErrorContainer.copy(alpha = 0.72f),
                )
            }
        }
    }
}

@Composable
private fun DiagnosticRow(label: String, value: String) {
    Row(verticalAlignment = Alignment.Top) {
        Text(
            label,
            modifier = Modifier.width(42.dp),
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
        Text(
            value,
            modifier = Modifier.weight(1f),
            fontSize = 13.sp,
            lineHeight = 19.sp,
            color = MaterialTheme.colorScheme.onErrorContainer,
        )
    }
}

private class MediaAnalyzer {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    suspend fun analyze(
        raw: String,
        onProgress: (String, Int) -> Unit,
    ): List<MediaItem> = withContext(Dispatchers.IO) {
        onProgress("주소 형식 확인 중", 5)
        val input = Regex("https?://\\S+", RegexOption.IGNORE_CASE)
            .find(raw.trim())?.value
            ?.trimEnd('.', ',', ')', ']', '}', '>', '"', '\'')
            ?: raw.trim()
        require(input.startsWith("http://") || input.startsWith("https://")) {
            "http 또는 https 주소를 넣어주세요."
        }

        onProgress("페이지 연결 중", 15)
        val request = Request.Builder()
            .url(input)
            .header("User-Agent", DownloadWorker.USER_AGENT)
            .header(
                "Accept",
                "text/html,application/xhtml+xml,application/vnd.apple.mpegurl,video/*,*/*",
            )
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                error("페이지 요청 실패: HTTP ${response.code}")
            }
            onProgress("페이지 응답 확인 중", 30)
            val finalUrl = response.request.url.toString()
            val type = response.header("Content-Type").orEmpty().lowercase()

            if (type.startsWith("video/") || isDirect(finalUrl)) {
                onProgress("직접 영상 주소 확인", 100)
                return@withContext listOf(
                    MediaItem(
                        finalUrl,
                        titleFromUrl(finalUrl),
                        quality(finalUrl),
                        "DIRECT",
                        finalUrl,
                    )
                )
            }

            val body = response.body?.byteStream()?.readNBytes(3_000_000) ?: ByteArray(0)
            val text = body.toString(Charsets.UTF_8)
            if (
                type.contains("mpegurl") ||
                finalUrl.contains(".m3u8", true) ||
                text.trimStart().startsWith("#EXTM3U")
            ) {
                onProgress("HLS 재생목록 분석 중", 75)
                val result = parseHls(finalUrl, text, titleFromUrl(finalUrl), finalUrl)
                onProgress("분석 완료", 100)
                return@withContext result
            }

            onProgress("페이지 구조 분석 중", 50)
            val doc = Jsoup.parse(text, finalUrl)
            val title = doc.selectFirst("meta[property=og:title]")?.attr("content")
                ?.takeIf { it.isNotBlank() }
                ?: doc.title().ifBlank { titleFromUrl(finalUrl) }
            val urls = linkedSetOf<String>()

            doc.select("video[src],source[src]").forEach {
                it.absUrl("src").takeIf(String::isNotBlank)?.let(urls::add)
            }
            doc.select(
                "meta[property=og:video],meta[property=og:video:url],meta[name=twitter:player:stream]"
            ).forEach { element ->
                resolve(finalUrl, element.attr("content"))?.let(urls::add)
            }
            Regex(
                "https?://[^\\s\\\"'<>]+?\\.(?:mp4|webm|mov|m4v|m3u8)(?:\\?[^\\s\\\"'<>]*)?",
                RegexOption.IGNORE_CASE,
            ).findAll(text)
                .map { it.value.replace("\\/", "/") }
                .forEach(urls::add)

            onProgress("영상 주소 탐색 중", 70)
            val out = mutableListOf<MediaItem>()
            urls.take(24).forEachIndexed { index, url ->
                val progress = 70 + (((index + 1) * 25.0) / urls.take(24).size.coerceAtLeast(1)).toInt()
                when {
                    url.contains(".m3u8", true) -> {
                        onProgress("HLS 재생목록 ${index + 1}개째 분석 중", progress.coerceAtMost(95))
                        val hls = fetchText(url, finalUrl)
                        out += parseHls(url, hls, title, finalUrl)
                    }
                    isDirect(url) -> {
                        out += MediaItem(url, title, quality(url), "DIRECT", finalUrl)
                    }
                }
            }

            val result = out
                .distinctBy { it.url }
                .sortedByDescending { qualityNumber(it.quality) }
                .ifEmpty {
                    error("페이지에서 직접 재생 주소를 찾지 못했습니다.")
                }
            onProgress("분석 완료", 100)
            result
        }
    }

    private fun parseHls(
        url: String,
        text: String,
        title: String,
        source: String,
    ): List<MediaItem> {
        val lines = text.lines().map(String::trim).filter(String::isNotEmpty)
        val encrypted = lines.any {
            it.startsWith("#EXT-X-KEY", true) && !it.contains("METHOD=NONE", true)
        }
        val variants = mutableListOf<MediaItem>()
        lines.forEachIndexed { index, line ->
            if (line.startsWith("#EXT-X-STREAM-INF", true)) {
                val next = lines.drop(index + 1).firstOrNull { !it.startsWith("#") }
                    ?: return@forEachIndexed
                val child = resolve(url, next) ?: return@forEachIndexed
                val height = Regex("RESOLUTION=\\d+x(\\d+)", RegexOption.IGNORE_CASE)
                    .find(line)?.groupValues?.getOrNull(1)
                variants += MediaItem(
                    child,
                    title,
                    height?.let { "${it}p" } ?: "자동",
                    "HLS",
                    source,
                    if (encrypted) "암호화된 HLS는 저장할 수 없습니다." else null,
                )
            }
        }
        return variants.ifEmpty {
            listOf(
                MediaItem(
                    url,
                    title,
                    "원본",
                    "HLS",
                    source,
                    if (encrypted) "암호화된 HLS는 저장할 수 없습니다." else null,
                )
            )
        }
    }

    private fun fetchText(url: String, referer: String): String {
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", DownloadWorker.USER_AGENT)
            .header("Referer", referer)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                error("재생목록 요청 실패: HTTP ${response.code}")
            }
            return response.body?.string().orEmpty()
        }
    }

    private fun isDirect(url: String) =
        Regex("(?i)\\.(mp4|webm|mov|m4v)(?:$|[?#])").containsMatchIn(url)

    private fun quality(url: String) =
        Regex("(?i)(2160|1440|1080|720|480|360)p")
            .find(url)?.groupValues?.get(1)?.plus("p") ?: "원본"

    private fun qualityNumber(label: String) =
        label.removeSuffix("p").toIntOrNull() ?: 0

    private fun titleFromUrl(url: String) = runCatching {
        URI(url).path.substringAfterLast('/').ifBlank { "영상" }
    }.getOrDefault("영상")

    private fun resolve(base: String, value: String): String? = runCatching {
        URI(base).resolve(value.trim()).toString()
    }.getOrNull()?.takeIf {
        it.startsWith("http://") || it.startsWith("https://")
    }
}
