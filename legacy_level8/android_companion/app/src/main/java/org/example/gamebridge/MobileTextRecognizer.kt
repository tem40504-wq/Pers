package org.example.gamebridge

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions

object MobileTextRecognizer {
    private val engine by lazy {TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)}
    fun process(bitmap:Bitmap) {
        // Создаём безопасную копию: исходный bitmap освобождает capture поток.
        val copy=bitmap.copy(Bitmap.Config.ARGB_8888,false)
        engine.process(InputImage.fromBitmap(copy,0))
            .addOnSuccessListener { result ->
                AppState.ocrTexts=result.textBlocks.map { it.text.take(250) }.take(20)
            }.addOnCompleteListener {copy.recycle()}
    }
}
