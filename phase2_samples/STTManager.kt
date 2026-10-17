// PHASE 3 SAMPLE — NOT INCLUDED IN MVP BUILD.
// Requires RECORD_AUDIO runtime permission. Recognizes microphone speech, NOT playback PCM.
package dev.gamescreen.voice.phase2

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

class STTManager(context: Context, private val onText: (String) -> Unit) : RecognitionListener {
    private val speech = SpeechRecognizer.createSpeechRecognizer(context)
    init { speech.setRecognitionListener(this) }
    // Call from the main thread after foreground permission request.
    fun start(language: String = "en-US") {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        }
        speech.startListening(intent)
    }
    fun stop() = speech.stopListening()
    fun destroy() = speech.destroy()
    override fun onPartialResults(partialResults: Bundle?) {
        partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()?.let(onText)
    }
    override fun onResults(results: Bundle?) = onPartialResults(results)
    override fun onReadyForSpeech(params: Bundle?) {}
    override fun onBeginningOfSpeech() {}
    override fun onRmsChanged(rmsdB: Float) {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech() {}
    override fun onError(error: Int) {}
    override fun onEvent(eventType: Int, params: Bundle?) {}
}
