package org.example.gamebridge

import java.io.File

/** Модель по умолчанию отключена, пока владелец не подготовит проверенные веса.
 * TFLite/MediaPipe загрузка зависит от ABI и сборки. Не запускаем неизвестный бинарник.
 */
interface GameObjectDetector {
    fun detect(jpeg:ByteArray):List<DetectedObject>
}
data class DetectedObject(val label:String,val confidence:Float,
    val left:Int,val top:Int,val right:Int,val bottom:Int)

class DisabledYoloNano:GameObjectDetector {
    override fun detect(jpeg:ByteArray)= emptyList<DetectedObject>()
}

/** Подготовка YAMNet: нужен пользовательский PCM источник.
 * Готовая модель YAMNet имеет AudioSet классы, а не метки игровых событий:
 * enemy_attack и victory необходимо обучить/откалибровать отдельно.
 */
interface AudioClassifier {
    fun classify(pcmFloat32:FloatArray,sampleRate:Int=16000):Map<String,Float>
}
class DisabledYamNet:AudioClassifier {
    override fun classify(pcmFloat32:FloatArray,sampleRate:Int)=emptyMap<String,Float>()
}
