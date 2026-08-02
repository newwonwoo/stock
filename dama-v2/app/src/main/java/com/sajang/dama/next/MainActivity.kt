package com.sajang.dama.next

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.io.File

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val sharedText = if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        } else {
            ""
        }
        setContent {
            DamaV2App(initialInput = sharedText)
        }
    }
}

private sealed interface ResolveUiState {
    data object Idle : ResolveUiState
    data class Working(val stage: PipelineStage) : ResolveUiState
    data class Ready(val result: ExtractionResult.Success) : ResolveUiState
    data class Failed(val detail: FailureDetail) : ResolveUiState
}

@Composable
private fun DamaV2App(initialInput: String) {
    val context = LocalContext.current
    val appContext = context.applicationContext
    val pipeline = remember(appContext) {
        ExtractionPipeline(
            extractors = listOf(
                DirectUrlExtractor(),
                YtDlpExtractor(appContext)
            )
        )
    }
    val scope = rememberCoroutineScope()
    var input by rememberSaveable { mutableStateOf(initialInput) }
    var uiState by remember { mutableStateOf<ResolveUiState>(ResolveUiState.Idle) }
    var diagnosticFile by remember { mutableStateOf<File?>(null) }

    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Text(
                    text = "담아 v2 개발판",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "직접 미디어 주소는 즉시 판별하고, 일반 페이지는 yt-dlp로 형식을 추출합니다.",
                    style = MaterialTheme.typography.bodyMedium
                )

                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("urlInput"),
                    label = { Text("영상 주소") },
                    minLines = 3,
                    enabled = uiState !is ResolveUiState.Working
                )

                Button(
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("analyzeButton"),
                    enabled = input.isNotBlank() && uiState !is ResolveUiState.Working,
                    onClick = {
                        val diagnostics = DiagnosticSession()
                        diagnostics.record(
                            category = "INPUT",
                            message = "analysis requested",
                            detail = input
                        )
                        diagnosticFile = null

                        scope.launch {
                            uiState = ResolveUiState.Working(PipelineStage.VALIDATING_URL)
                            val result = pipeline.resolve(
                                input = input,
                                reporter = StageReporter { stage ->
                                    diagnostics.record("STAGE", stage.name)
                                    uiState = ResolveUiState.Working(stage)
                                }
                            )

                            when (result) {
                                is ExtractionResult.Success -> {
                                    diagnostics.record(
                                        category = "SUCCESS",
                                        message = "extractor=${result.extractorId}",
                                        detail = "mediaCount=${result.media.size}; kinds=${result.media.joinToString { it.kind.name }}"
                                    )
                                    uiState = ResolveUiState.Ready(result)
                                }

                                is ExtractionResult.Failure -> {
                                    val fallback = decideBrowserFallback(result.detail)
                                    diagnostics.record(
                                        category = "FAILURE",
                                        message = "${result.detail.stage}/${result.detail.code}",
                                        detail = result.detail.technicalDetail
                                    )
                                    diagnostics.record(
                                        category = "FALLBACK",
                                        message = "eligible=${fallback.eligible}; reason=${fallback.reason}",
                                        detail = fallback.explanation
                                    )
                                    uiState = ResolveUiState.Failed(result.detail)
                                }

                                is ExtractionResult.Unsupported -> {
                                    val detail = FailureDetail(
                                        stage = PipelineStage.EXTRACTING,
                                        code = FailureCode.EXTRACTOR_UNSUPPORTED,
                                        message = result.reason
                                    )
                                    val fallback = decideBrowserFallback(detail)
                                    diagnostics.record(
                                        category = "FAILURE",
                                        message = "${detail.stage}/${detail.code}",
                                        detail = result.reason
                                    )
                                    diagnostics.record(
                                        category = "FALLBACK",
                                        message = "eligible=${fallback.eligible}; reason=${fallback.reason}",
                                        detail = fallback.explanation
                                    )
                                    uiState = ResolveUiState.Failed(detail)
                                }
                            }

                            diagnosticFile = runCatching {
                                diagnostics.writeToCache(context)
                            }.getOrNull()
                        }
                    }
                ) {
                    Text("주소 분석")
                }

                when (val state = uiState) {
                    ResolveUiState.Idle -> StatusCard(
                        title = "대기",
                        body = "주소를 입력하거나 브라우저에서 담아 v2로 공유하세요."
                    )

                    is ResolveUiState.Working -> Card(
                        modifier = Modifier.testTag("workingCard"),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.secondaryContainer
                        )
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            CircularProgressIndicator()
                            Text(
                                text = stageLabel(state.stage),
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    is ResolveUiState.Ready -> {
                        StatusCard(
                            title = "추출 성공 · ${state.result.extractorId}",
                            body = buildString {
                                appendLine("후보: ${state.result.media.size}개")
                                state.result.media.take(8).forEachIndexed { index, media ->
                                    append(index + 1)
                                    append(". ")
                                    append(media.qualityLabel ?: media.formatId ?: media.kind.name)
                                    append(" · ")
                                    append(media.trackRole)
                                    append(" · ")
                                    appendLine(media.kind)
                                }
                                if (state.result.media.size > 8) {
                                    append("외 ${state.result.media.size - 8}개")
                                }
                            }
                        )
                        Text(
                            text = "이번 단계는 추출 형식 검증용입니다. 다운로드 엔진은 다음 수직 기능에서 연결합니다.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }

                    is ResolveUiState.Failed -> {
                        val fallback = decideBrowserFallback(state.detail)
                        StatusCard(
                            title = "분석 실패 · ${state.detail.code}",
                            body = buildString {
                                appendLine("단계: ${state.detail.stage}")
                                appendLine(state.detail.message)
                                appendLine(
                                    if (fallback.eligible) {
                                        "다음 경로: 브라우저 폴백 (${fallback.reason})"
                                    } else {
                                        "다음 경로: 브라우저 폴백 안 함"
                                    }
                                )
                                appendLine(fallback.explanation)
                                state.detail.technicalDetail?.takeIf { it.isNotBlank() }?.let {
                                    append("상세: $it")
                                }
                            },
                            isError = true
                        )
                    }
                }

                diagnosticFile?.let { file ->
                    OutlinedButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("shareDiagnosticsButton"),
                        onClick = { shareDiagnosticFile(context, file) }
                    ) {
                        Text("진단 로그 공유")
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))
            }
        }
    }
}

@Composable
private fun StatusCard(
    title: String,
    body: String,
    isError: Boolean = false
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("statusCard"),
        colors = CardDefaults.cardColors(
            containerColor = if (isError) {
                MaterialTheme.colorScheme.errorContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = title,
                modifier = Modifier.testTag("statusTitle"),
                fontWeight = FontWeight.Bold
            )
            Text(body)
        }
    }
}

private fun stageLabel(stage: PipelineStage): String = when (stage) {
    PipelineStage.IDLE -> "대기"
    PipelineStage.VALIDATING_URL -> "주소 검증 중"
    PipelineStage.INITIALIZING_ENGINE -> "yt-dlp 엔진 준비 중"
    PipelineStage.EXTRACTING -> "영상 정보 추출 중"
    PipelineStage.PARSING_FORMATS -> "화질·트랙 분석 중"
    PipelineStage.FORMATS_FOUND -> "미디어 형식 확인"
    PipelineStage.READY_TO_DOWNLOAD -> "다운로드 준비"
    PipelineStage.FAILED -> "실패"
}
