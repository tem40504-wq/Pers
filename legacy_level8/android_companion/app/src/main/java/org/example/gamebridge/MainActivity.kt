package org.example.gamebridge

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.content.Context

class MainActivity: Activity() {
    private val projectionCode=42
    private val projectionManager by lazy { getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager }
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        val layout=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL;setPadding(18,30,18,10)}
        val headline=TextView(this).apply {text="Game Agent Companion — только локальная связь"}
        val tokenText=TextView(this).apply {text="GAME_BRIDGE_TOKEN:\n${AppState.token}\nПорт 8766 (127.0.0.1)";setTextIsSelectable(true)}
        val coords=EditText(this).apply {hint="Безопасная зона: x1,y1,x2,y2";setSingleLine(true)}
        val capture=Button(this).apply {text="1. Разрешить захват экрана";setOnClickListener {
            startActivityForResult(projectionManager.createScreenCaptureIntent(),projectionCode)
        }}
        val arm=Button(this).apply {text="2. ARM жесты на 5 минут";setOnClickListener {
            try {
                val values=coords.text.toString().split(',').map { it.trim().toInt() }.toIntArray()
                AppState.arm(values)
                headline.text="Жесты разрешены ТОЛЬКО внутри зоны на 5 минут"
            } catch(ex:Exception) { headline.text="Ошибка безопасной зоны: ${ex.message}" }
        }}
        val stop=Button(this).apply {text="PANIC STOP";setOnClickListener {
            AppState.stop();headline.text="STOP: жесты заблокированы"
        }}
        layout.addView(headline);layout.addView(tokenText);layout.addView(coords)
        layout.addView(capture);layout.addView(arm);layout.addView(stop)
        layout.addView(TextView(this).apply {text="Включите службу в Настройки → Специальные возможности → Установленные приложения. Никогда не включайте для чужого ПК."})
        setContentView(layout)
    }
    @Deprecated("Activity Result API can be used in later release")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==projectionCode && resultCode==RESULT_OK && data!=null) {
            val svc=Intent(this,ProjectionService::class.java)
                .putExtra("resultCode",resultCode).putExtra("projectionData",data)
            startForegroundService(svc)
        }
    }
}
