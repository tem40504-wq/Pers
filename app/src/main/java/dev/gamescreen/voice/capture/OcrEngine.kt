package dev.gamescreen.voice.capture

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions

/** Bundled ML Kit Latin OCR model. Screenshot bitmaps stay on the device. */
class OcrEngine : AutoCloseable {
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    /** One recognition at a time is enforced by the caller. Bitmap ownership stays with caller. */
    fun recognize(bitmap: Bitmap, onResult: (Result<String>) -> Unit) {
        try {
            recognizer.process(InputImage.fromBitmap(bitmap, 0))
                .addOnCompleteListener { task ->
                    if (task.isSuccessful) {
                        val text = task.result?.textBlocks
                            ?.joinToString("\n") { it.text }
                            ?.trim().orEmpty()
                        onResult(Result.success(text))
                    } else {
                        onResult(Result.failure(task.exception ?: IllegalStateException("OCR failed")))
                    }
                }
        } catch (e: Exception) {
            onResult(Result.failure(e))
        }
    }

    override fun close() { recognizer.close() }
}
