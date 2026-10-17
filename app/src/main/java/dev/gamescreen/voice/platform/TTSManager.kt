package dev.gamescreen.voice.platform

import android.content.Context
import android.speech.tts.TextToSpeech
import dev.gamescreen.voice.data.SettingsStore
import java.util.Locale

class TTSManager(context: Context, private val settings: SettingsStore) : TextToSpeech.OnInitListener {
    @Volatile private var ready = false
    private val engine = TextToSpeech(context.applicationContext, this)
    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (ready) configure()
    }
    private fun configure(): Boolean {
        if (!ready) return false
        val s = settings.load()
        val locale = Locale.forLanguageTag(s.targetLang.lowercase())
        val languageResult = engine.setLanguage(locale)
        if (languageResult == TextToSpeech.LANG_MISSING_DATA ||
            languageResult == TextToSpeech.LANG_NOT_SUPPORTED) return false
        engine.setSpeechRate(s.speechSpeed.coerceIn(.5f, 1.7f))
        if (s.voiceName.isNotBlank()) {
            engine.voices?.firstOrNull { it.name == s.voiceName && it.locale.language == locale.language }
                ?.let { engine.voice = it }
        }
        return true
    }
    fun speak(text: String): Boolean {
        if (text.isBlank() || !configure()) return false
        return engine.speak(text.take(3000), TextToSpeech.QUEUE_FLUSH, null, "translated_speech") == TextToSpeech.SUCCESS
    }
    fun stop() { if (ready) engine.stop() }
    fun release() { engine.stop(); engine.shutdown(); ready = false }
}
