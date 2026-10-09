package org.example.gamebridge

import android.os.SystemClock
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.atomic.AtomicReference

object AppState {
    // Секрет действует только в текущем процессе и показывается владельцу в приложении.
    val token: String = ByteArray(32).also { SecureRandom().nextBytes(it) }
        .let { Base64.getUrlEncoder().withoutPadding().encodeToString(it) }
    @Volatile var armedUntilMs: Long = 0
    @Volatile var panic: Boolean = true
    @Volatile var safeRect: IntArray? = null
    val frame = AtomicReference<ByteArray?>(null)
    @Volatile var width = 1080
    @Volatile var height = 2400
    @Volatile var batteryTempC: Double? = null
    @Volatile var ocrTexts: List<String> = emptyList()

    fun arm(box: IntArray) {
        require(box.size == 4 && box[0] < box[2] && box[1] < box[3])
        safeRect=box.copyOf()
        panic=false
        armedUntilMs=SystemClock.elapsedRealtime()+300_000L
    }
    fun stop() { panic=true; armedUntilMs=0 }
    fun canGesture(points: List<Pair<Int,Int>>): Boolean {
        val r=safeRect ?: return false
        if (panic || SystemClock.elapsedRealtime()>armedUntilMs) return false
        return points.all { (x,y)-> x>=r[0] && y>=r[1] && x<=r[2] && y<=r[3] && x<width && y<height }
    }
}
