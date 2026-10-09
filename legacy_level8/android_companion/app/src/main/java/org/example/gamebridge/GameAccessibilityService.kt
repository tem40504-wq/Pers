package org.example.gamebridge

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent

class GameAccessibilityService: AccessibilityService() {
    companion object { @Volatile var current: GameAccessibilityService? = null }
    override fun onServiceConnected() { super.onServiceConnected(); current=this }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) { /* Не собираем пользовательский текст. */ }
    override fun onInterrupt() { AppState.stop() }
    override fun onDestroy() { AppState.stop(); current=null; super.onDestroy() }

    fun gesture(kind:String,x:Int,y:Int,x2:Int,y2:Int,duration:Long): Boolean {
        val points = if(kind=="tap") listOf(Pair(x,y)) else listOf(Pair(x,y),Pair(x2,y2))
        if (!AppState.canGesture(points)) return false
        val p=Path().apply { moveTo(x.toFloat(),y.toFloat())
            if(kind=="swipe") lineTo(x2.toFloat(),y2.toFloat()) }
        val stroke=GestureDescription.StrokeDescription(p,0L,if(kind=="tap") 80L else duration.coerceIn(100L,1000L))
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(),null,null)
    }
}
