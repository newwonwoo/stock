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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

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
    val pipeline = remember {
        ExtractionPipeline(
            extractors = listOf(DirectUrlExtractor())
        )
    }
    val scope = rememberCoroutineScope()
    var input by rememberSaveable { mutableStateOf(initialInput) }
    var uiState by remember { mutableStateOf<ResolveUiState>(ResolveUiState.Idle) }

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
                    text = "새 파이프라인의 첫 수직 기능입니다. 직접 MP4·HLS·DASH 주소만 판별합니다.",
                    style = MaterialTheme.typography.bodyMedium
                )

                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("영상 주소") },
                    minLines = 3,
                    enabled = uiState !is ResolveUiState.Working
                )

                Button(
                    modifier = Modifier.fillMaxWidth(),
                    enabled = input.isNotBlank() && uiState !is ResolveUiState.Working,
                    onClick = {
                        scope.launch {
                            uiState = ResolveUiState.Working(PipelineStage.VALIDATING_URL)
                            when (val result = pipeline.resolve(
                                input = input,
                                reporter = StageReporter { stage ->
                                    uiState = ResolveUiState.Working(stage)
                                }
                            )) {
                                is ExtractionResult.Success -> {
                                    uiState = ResolveUiState.Ready(result)
                                }

                                is ExtractionResult.Failure -> {
                                    uiState = ResolveUiState.Failed(result.detail)
                                }

                                is ExtractionResult.Unsupported -> {
                                    uiState = ResolveUiState.Failed(
                                        FailureDetail(
                                            stage = PipelineStage.EXTRACTING,
                                            code = FailureCode.EXTRACTOR_UNSUPPORTED,
                                            message = result.reason
                                        )
                                    )
                                }
                            }
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
                        val media = state.result.media.first()
                        StatusCard(
                            title = "추출 성공 · ${state.result.extractorId}",
                            body = buildString {
                                appendLine("유형: ${media.kind}")
                                appendLine("제목: ${media.title}")
                                appendLine("MIME: ${media.mimeType ?: "확인 필요"}")
                                append("주소: ${media.sourceUrl}")
                            }
                        )
                        Text(
                            text = "다운로드 엔진은 이 계약을 유지한 채 다음 단계에서 연결합니다.",
                            style = MaterialTheme.typography.bodySmall
                        )
                    }

                    is ResolveUiState.Failed -> StatusCard(
                        title = "분석 실패 · ${state.detail.code}",
                        body = buildString {
                            appendLine("단계: ${state.detail.stage}")
                            appendLine(state.detail.message)
                            state.detail.technicalDetail?.takeIf { it.isNotBlank() }?.let {
                                append("상세: $it")
                            }
                        },
                        isError = true
                    )
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
        modifier = Modifier.fillMaxWidth(),
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
            Text(title, fontWeight = FontWeight.Bold)
            Text(body)
        }
    }
}

private fun stageLabel(stage: PipelineStage): String = when (stage) {
    PipelineStage.IDLE -> "대기"
    PipelineStage.VALIDATING_URL -> "주소 검증 중"
    PipelineStage.EXTRACTING -> "추출기 실행 중"
    PipelineStage.FORMATS_FOUND -> "미디어 형식 확인"
    PipelineStage.READY_TO_DOWNLOAD -> "다운로드 준비"
    PipelineStage.FAILED -> "실패"
}
