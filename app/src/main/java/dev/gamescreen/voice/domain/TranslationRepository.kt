package dev.gamescreen.voice.domain

interface TranslationRepository {
    /** [onStatus] reports long steps (e.g. a one-time language model download) to the UI. */
    suspend fun translate(
        text: String,
        sourceLanguage: String,
        targetLanguage: String,
        onStatus: (String) -> Unit = {}
    ): String

    /** Short provider name shown next to the result, e.g. "DeepL" or "офлайн". */
    fun label(): String = ""
}
