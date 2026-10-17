package dev.gamescreen.voice.platform

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import dev.gamescreen.voice.data.SettingsStore
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

class TTSManager(
    context: Context,
    private val settings: SettingsStore,
    private val onStatus: (String) -> Unit = {}
) : TextToSpeech.OnInitListener {
    @Volatile private var ready = false
    private val engine = TextToSpeech(context.applicationContext, this)
    private val audioManager = context.getSystemService(AudioManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private var counter = 0L

    /** Utterances queued or playing. The original is ducked while this set is non-empty. */
    private val active: MutableSet<String> = ConcurrentHashMap.newKeySet()
    @Volatile private var ducked = false

    // USAGE_ASSISTANT: our own voice is NOT picked up by audio capture (it only takes media/game audio),
    // so the translation is never re-recognised and translated again.
    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANT)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()
    private val focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(attributes)
        .setWillPauseWhenDucked(false)
        .setOnAudioFocusChangeListener({ }, main)
        .build()

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (!ready) return
        engine.setAudioAttributes(attributes)
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = finished(utteranceId)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finished(utteranceId)
            override fun onError(utteranceId: String?, errorCode: Int) = finished(utteranceId)
            override fun onStop(utteranceId: String?, interrupted: Boolean) = finished(utteranceId)
        })
        configure()
    }

    /**
     * Only the utterance that actually ended is removed. Before 0.2.1 a counter was used and the
     * "stopped" event of an interrupted phrase released the ducking while the new phrase was playing.
     */
    private fun finished(id: String?) {
        if (id != null) active.remove(id)
        // Small delay: the next queued phrase usually starts right away; avoid volume "pumping".
        main.postDelayed({ if (active.isEmpty()) releaseDuck() }, 350)
    }

    private fun duck() {
        if (!settings.load().duckOriginal) { releaseDuck(); return }
        val result = audioManager?.requestAudioFocus(focusRequest) ?: AudioManager.AUDIOFOCUS_REQUEST_FAILED
        if (result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            ducked = true
        } else if (!ducked) {
            onStatus("Android не разрешил приглушить оригинал (код $result)")
        }
    }

    private fun releaseDuck() {
        if (!ducked) return
        ducked = false
        audioManager?.abandonAudioFocusRequest(focusRequest)
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
        val id = "gsv_${counter++}"
        if (!queue) active.clear()
        active.add(id)
        duck()
        val result = engine.speak(
            text.take(3000),
            if (queue) TextToSpeech.QUEUE_ADD else TextToSpeech.QUEUE_FLUSH,
            null,
            id
        )
        if (result != TextToSpeech.SUCCESS) finished(id)
        return result == TextToSpeech.SUCCESS
    }

    fun stop() {
        if (ready) engine.stop()
        active.clear()
        releaseDuck()
    }

    fun release() {
        engine.stop(); engine.shutdown(); ready = false
        active.clear()
        releaseDuck()
    }
}
