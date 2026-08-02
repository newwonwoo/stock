package com.sajang.dama.next

enum class BrowserFallbackReason {
    TRANSPORT_RESET,
    GENERIC_UNSUPPORTED,
    SESSION_REQUIRED,
    REQUEST_FORBIDDEN
}

data class BrowserFallbackDecision(
    val eligible: Boolean,
    val reason: BrowserFallbackReason? = null,
    val explanation: String
)

fun decideBrowserFallback(detail: FailureDetail): BrowserFallbackDecision {
    return when (detail.code) {
        FailureCode.NETWORK_RESET -> BrowserFallbackDecision(
            eligible = true,
            reason = BrowserFallbackReason.TRANSPORT_RESET,
            explanation = "일반 HTTP 연결이 차단되어 실제 브라우저 세션에서만 재검증합니다."
        )

        FailureCode.EXTRACTOR_UNSUPPORTED -> BrowserFallbackDecision(
            eligible = true,
            reason = BrowserFallbackReason.GENERIC_UNSUPPORTED,
            explanation = "정적 추출기가 처리하지 못해 실제 재생 요청 감지로 전환합니다."
        )

        FailureCode.COOKIE_REQUIRED,
        FailureCode.LOGIN_REQUIRED -> BrowserFallbackDecision(
            eligible = true,
            reason = BrowserFallbackReason.SESSION_REQUIRED,
            explanation = "브라우저 세션이 필요한 페이지이므로 세션 기반 폴백 대상으로 분류합니다."
        )

        FailureCode.HTTP_FORBIDDEN -> BrowserFallbackDecision(
            eligible = true,
            reason = BrowserFallbackReason.REQUEST_FORBIDDEN,
            explanation = "비브라우저 요청이 거부되어 브라우저 컨텍스트에서만 재검증합니다."
        )

        FailureCode.RATE_LIMITED -> BrowserFallbackDecision(
            eligible = false,
            explanation = "요청 제한 상태에서는 브라우저를 추가 실행하지 않고 대기해야 합니다."
        )

        FailureCode.DRM_DETECTED -> BrowserFallbackDecision(
            eligible = false,
            explanation = "DRM으로 보호된 콘텐츠는 폴백이나 저장을 시도하지 않습니다."
        )

        else -> BrowserFallbackDecision(
            eligible = false,
            explanation = "현재 실패는 브라우저 폴백으로 해결되는 유형이 아닙니다."
        )
    }
}
