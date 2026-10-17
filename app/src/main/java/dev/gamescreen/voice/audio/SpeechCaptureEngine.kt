package dev.gamescreen.voice.audio

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.projection.MediaProjection
import android.os.Process
import android.os.SystemClock
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer

/**
 * Captures what other apps play (media/game audio, Android 10+ AudioPlaybackCapture),
 * recognises speech offline with Vosk and reports partial / finished phrases.
 * Our own TTS (USAGE_ASSISTANT, own UID) is excluded, so the translation is never re-captured.
 */
class SpeechCaptureEngine(
    private val context: Context,
    private val projection: MediaProjection,
    private val language: String,
    private val onStatus: (String) -> Unit,
    private val onPartial: (String) -> Unit,
    private val onPhrase: (String) -> Unit
) {
    companion object {
        private const val RATE = 16000
        /** Music/background without pauses: force a phrase out after this long. */
        private const val MAX_PHRASE_MS = 9_000L
    }

    @Volatile private var running = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun start() {
        running = true
        scope.launch {
            try {
                val dir = VoskModels.ensure(context, language, onStatus)
                if (!running) return@launch
                onStatus("Загрузка модели речи в память…")
                val model = Model(dir.absolutePath)
                try { capture(model) } finally { model.close() }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                if (running) onStatus("Ошибка захвата звука: ${e.message.orEmpty().take(110)}")
            }
        }
    }

    @SuppressLint("MissingPermission") // RECORD_AUDIO is requested by MainActivity before start.
    private fun capture(model: Model) {
        val config = AudioPlaybackCaptureConfiguration.Builder(projection)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
            .excludeUid(Process.myUid())
            .build()
        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(RATE)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
            .build()
        val minBuffer = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord.Builder()
            .setAudioFormat(format)
            .setBufferSizeInBytes(maxOf(minBuffer * 4, RATE * 2))
            .setAudioPlaybackCaptureConfig(config)
            .build()
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw IllegalStateException("AudioRecord не инициализирован (нет разрешения на запись?)")
        }
        val recognizer = Recognizer(model, RATE.toFloat())
        try {
            record.startRecording()
            onStatus("Слушаю звук… Включите видео или игру")
            val buffer = ShortArray(RATE / 4) // 250 ms
            var lastPartial = ""
            var phraseStarted = 0L
            while (running) {
                val n = record.read(buffer, 0, buffer.size)
                if (n < 0) throw IllegalStateException("Ошибка чтения звука ($n)")
                if (n == 0) continue
                if (recognizer.acceptWaveForm(buffer, n)) {
                    emitPhrase(field(recognizer.result, "text"))
                    lastPartial = ""
                    phraseStarted = 0L
                } else {
                    val partial = field(recognizer.partialResult, "partial")
                    if (partial.isNotEmpty() && phraseStarted == 0L) phraseStarted = SystemClock.elapsedRealtime()
                    if (partial != lastPartial) {
                        lastPartial = partial
                        if (partial.isNotEmpty()) onPartial(partial)
                    }
                    if (phraseStarted != 0L && SystemClock.elapsedRealtime() - phraseStarted > MAX_PHRASE_MS) {
                        emitPhrase(field(recognizer.finalResult, "text"))
                        lastPartial = ""
                        phraseStarted = 0L
                    }
                }
            }
        } finally {
            try { record.stop() } catch (_: Exception) { }
            record.release()
            recognizer.close()
        }
    }

    private fun emitPhrase(text: String) {
        // Single filler words ("the", "huh") are noise from music and effects.
        if (text.split(' ').count { it.isNotBlank() } >= 2 || text.length >= 6) onPhrase(text)
    }

    private fun field(json: String?, key: String): String =
        try { JSONObject(json ?: "{}").optString(key).trim() } catch (_: Exception) { "" }

    fun stop() {
        running = false
        scope.cancel()
    }
}
