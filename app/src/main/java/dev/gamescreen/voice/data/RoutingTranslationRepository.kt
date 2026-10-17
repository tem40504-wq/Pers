package dev.gamescreen.voice.data

import dev.gamescreen.voice.domain.TranslationRepository

/** DeepL when a key is saved (and offline mode is off), otherwise free on-device ML Kit. */
class RoutingTranslationRepository(
    private val deepL: DeepLTranslationRepository,
    private val offline: MlKitTranslationRepository,
    private val secrets: SecretStore,
    private val settings: SettingsStore
) : TranslationRepository {
    private fun active(): TranslationRepository =
        if (!settings.load().offlineOnly && !secrets.readApiKey().isNullOrBlank()) deepL else offline

    override fun label(): String = active().label()

    override suspend fun translate(
        text: String,
        sourceLanguage: String,
        targetLanguage: String,
        onStatus: (String) -> Unit
    ): String = active().translate(text, sourceLanguage, targetLanguage, onStatus)
}
