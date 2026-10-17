package dev.gamescreen.voice.platform

import kotlin.math.roundToInt

/**
 * Estimates TTS speed in words/minute from observed caption changes.
 * We cannot know the future disappearance time of a subtitle; use a smoothed
 * duration between unique on-screen phrases and a conservative rate limit.
 * TTS rate is an engine-dependent approximation, not measured audio WPM.
 */
class SpeechPacer {
    private var lastCaption = ""
    private var lastObservedAt: Long = 0L
    private var dwellEstimateMs: Double = 4_800.0
    private var smoothRateWpm: Double = 140.0

    fun reset() {
        lastCaption = ""
        lastObservedAt = 0L
        dwellEstimateMs = 4_800.0
        smoothRateWpm = 140.0
    }

    fun observeCaption(text: String, elapsedMs: Long) {
        val normalized = text.trim().replace(Regex("\\s+"), " ").lowercase()
        if (normalized.isBlank() || normalized == lastCaption) return
        if (lastObservedAt > 0L && elapsedMs > lastObservedAt) {
            val dwell = (elapsedMs - lastObservedAt).coerceIn(1_800L, 12_000L)
            dwellEstimateMs = dwellEstimateMs * .70 + dwell * .30
        }
        lastCaption = normalized
        lastObservedAt = elapsedMs
    }

    fun speedFor(text: String, isAuto: Boolean, manualWpm: Int): Int {
        if (!isAuto) return manualWpm.coerceIn(80, 220)
        // A natural subtitle chunk normally has 2-25 words. Avoid chasing OCR noise.
        val wordCount = Regex("[\\p{L}\\p{N}]+(?:[-’'][\\p{L}\\p{N}]+)?")
            .findAll(text).count().coerceIn(1, 30)
        val target = (wordCount * 60_000.0 / dwellEstimateMs).coerceIn(105.0, 195.0)
        smoothRateWpm = smoothRateWpm * .55 + target * .45
        return smoothRateWpm.roundToInt().coerceIn(105, 195)
    }
}
