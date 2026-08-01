package com.sajang.dama

import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

data class FailureReport(
    val code: String,
    val title: String,
    val detail: String,
    val action: String,
    val technical: String,
)

object FailureAnalyzer {
    fun analyze(error: Throwable): FailureReport = fromMessage(error.message.orEmpty(), error)

    fun fromMessage(message: String, error: Throwable? = null): FailureReport {
        val raw = message.ifBlank { error?.javaClass?.simpleName ?: "알 수 없는 오류" }
        val lower = raw.lowercase()

        return when {
            error is UnknownHostException || error is ConnectException ||
                lower.contains("unable to resolve host") || lower.contains("failed to connect") -> report(
                "NETWORK_CONNECT",
                "네트워크 연결 실패",
                "영상 서버에 연결하지 못했습니다.",
                "인터넷 연결을 확인하고 잠시 뒤 다시 시도하세요.",
                raw,
            )

            error is SocketTimeoutException || lower.contains("timeout") || lower.contains("timed out") -> report(
                "NETWORK_TIMEOUT",
                "서버 응답 지연",
                "영상 서버가 제한 시간 안에 응답하지 않았습니다.",
                "네트워크를 바꾸거나 잠시 뒤 다시 시도하세요.",
                raw,
            )

            error is SSLException || lower.contains("ssl") || lower.contains("certificate") -> report(
                "TLS_ERROR",
                "보안 연결 실패",
                "서버 인증서 또는 HTTPS 연결 과정에서 오류가 발생했습니다.",
                "휴대폰 날짜·시간을 자동으로 맞춘 뒤 다시 시도하세요.",
                raw,
            )

            lower.contains("http 401") || lower.contains("로그인") -> report(
                "LOGIN_REQUIRED",
                "로그인 정보 필요",
                "영상 주소가 로그인 세션을 요구합니다.",
                "원래 앱이나 브라우저의 공식 저장 기능을 사용하세요.",
                raw,
            )

            lower.contains("http 403") || lower.contains("access denied") || lower.contains("forbidden") -> report(
                "ACCESS_BLOCKED",
                "서버가 접근을 차단함",
                "영상 서버가 외부 앱의 요청을 거부했습니다.",
                "브라우저에서 페이지를 다시 연 뒤 공유하거나 공식 다운로드 기능을 확인하세요.",
                raw,
            )

            lower.contains("http 404") -> report(
                "MEDIA_NOT_FOUND",
                "영상 주소가 만료됨",
                "요청한 영상 또는 영상 조각을 서버에서 찾지 못했습니다.",
                "페이지를 새로고침하고 새 주소로 다시 분석하세요.",
                raw,
            )

            lower.contains("http 429") -> report(
                "RATE_LIMITED",
                "요청이 너무 많음",
                "서버가 일시적으로 요청 횟수를 제한했습니다.",
                "잠시 뒤 다시 시도하세요.",
                raw,
            )

            Regex("http 5\\d\\d").containsMatchIn(lower) -> report(
                "SERVER_ERROR",
                "영상 서버 오류",
                "영상 제공 서버에서 일시적인 오류가 발생했습니다.",
                "잠시 뒤 다시 시도하세요.",
                raw,
            )

            lower.contains("암호화된 hls") || lower.contains("drm") || lower.contains("widevine") -> report(
                "ENCRYPTED_STREAM",
                "암호화된 영상",
                "재생목록에 암호화 키가 적용되어 일반 파일로 저장할 수 없습니다.",
                "해당 서비스의 공식 오프라인 저장 기능을 사용하세요.",
                raw,
            )

            lower.contains("바이트 범위 hls") || lower.contains("byterange") -> report(
                "HLS_BYTERANGE",
                "지원하지 않는 HLS 형식",
                "영상이 바이트 범위 방식으로 구성되어 있습니다.",
                "다른 화질을 선택하거나 직접 MP4 주소가 있는지 확인하세요.",
                raw,
            )

            lower.contains("영상 조각") -> report(
                "SEGMENT_DOWNLOAD",
                "영상 조각 저장 실패",
                "HLS 영상의 일부 조각을 내려받지 못했습니다.",
                "페이지를 새로고침한 뒤 다시 분석하거나 낮은 화질을 선택하세요.",
                raw,
            )

            lower.contains("재생목록") || lower.contains("m3u8") -> report(
                "PLAYLIST_ERROR",
                "재생목록 분석 실패",
                "HLS 재생목록을 읽거나 해석하지 못했습니다.",
                "페이지를 새로고침한 뒤 다시 공유하세요.",
                raw,
            )

            lower.contains("직접 재생 주소") || lower.contains("영상을 찾지 못") ||
                lower.contains("영상 주소를 찾지 못") -> report(
                "MEDIA_DETECTION",
                "영상 주소 미탐지",
                "페이지 안에서 저장 가능한 MP4·WebM·비암호화 HLS 주소를 찾지 못했습니다.",
                "영상을 실제로 재생한 뒤 다시 공유하거나 직접 영상 주소를 붙여넣으세요.",
                raw,
            )

            lower.contains("저장 공간") || lower.contains("enospc") || lower.contains("no space") -> report(
                "STORAGE_FULL",
                "저장 공간 부족",
                "동영상 파일을 만들 저장 공간이 부족하거나 저장소를 열지 못했습니다.",
                "휴대폰 저장 공간을 확보한 뒤 다시 시도하세요.",
                raw,
            )

            error is SecurityException || lower.contains("permission denied") || lower.contains("권한") -> report(
                "PERMISSION",
                "저장 권한 문제",
                "앱이 동영상 저장소에 접근하지 못했습니다.",
                "설정에서 담아 앱의 사진·동영상 권한을 허용하세요.",
                raw,
            )

            error is IllegalArgumentException || lower.contains("http 또는 https") || lower.contains("invalid url") -> report(
                "INVALID_URL",
                "주소 형식 오류",
                "입력한 값이 올바른 웹 주소가 아닙니다.",
                "http:// 또는 https://로 시작하는 주소를 넣으세요.",
                raw,
            )

            lower.contains("취소") || lower.contains("cancel") -> report(
                "CANCELLED",
                "사용자가 취소함",
                "다운로드가 완료되기 전에 취소되었습니다.",
                "필요하면 다시 다운로드하세요.",
                raw,
            )

            else -> report(
                "UNKNOWN",
                "원인을 특정하지 못함",
                "예상하지 못한 오류가 발생했습니다.",
                "주소를 다시 분석해 보고 같은 오류가 반복되면 기술 상세를 확인하세요.",
                raw,
            )
        }
    }

    private fun report(
        code: String,
        title: String,
        detail: String,
        action: String,
        technical: String,
    ) = FailureReport(code, title, detail, action, technical.take(500))
}
