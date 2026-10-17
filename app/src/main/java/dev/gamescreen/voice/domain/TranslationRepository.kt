package dev.gamescreen.voice.domain

interface TranslationRepository {
    suspend fun translate(text: String, sourceLanguage: String, targetLanguage: String): String
}
