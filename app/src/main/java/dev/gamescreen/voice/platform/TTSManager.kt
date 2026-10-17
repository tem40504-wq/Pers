package dev.gamescreen.voice.platform

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import dev.gamescreen.voice.data.SettingsStore
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger

class TTSManager(context: Context, private val settings: SettingsStore) : TextToSpeech.OnInitListener {
    @Volatile private var ready = false
    private val engine = TextToSpeech(context.applicationContext, this)
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val pending = AtomicInteger(0)
    private var counter = 0L

    // USAGE_ASSISTANT: our own voice is NOT picked up by audio capture (it only takes media/game audio),
    // so the translation is never re-recognised and translated again.
    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANT)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()
    private val focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(attributes)
        .build()

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (!ready) return
        engine.setAudioAttributes(attributes)
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = finished()
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finished()
            override fun onError(utteranceId: String?, errorCode: Int) = finished()
            override fun onStop(utteranceId: String?, interrupted: Boolean) = finished()
        })
        configure()
    }

    private fun finished() {
        if (pending.decrementAndGet() <= 0) {
            pending.set(0)
            audioManager?.abandonAudioFocusRequest(focusRequest)
        }
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

    /** [queue] = true appends after the current phrase (speech mode), false interrupts it (screen text). */
    fun speak(text: String, queue: Boolean = false): Boolean {
        if (text.isBlank() || !configure()) return false
        if (settings.load().duckOriginal) audioManager?.requestAudioFocus(focusRequest)
        if (queue) pending.incrementAndGet() else pending.set(1)
        val result = engine.speak(
            text.take(3000),
            if (queue) TextToSpeech.QUEUE_ADD else TextToSpeech.QUEUE_FLUSH,
            null,
            "gsv_${counter++}"
        )
        if (result != TextToSpeech.SUCCESS) finished()
        return result == TextToSpeech.SUCCESS
    }

    fun stop() { if (ready) engine.stop() }
    fun release() {
        engine.stop(); engine.shutdown(); ready = false
        audioManager?.abandonAudioFocusRequest(focusRequest)
    }
}
