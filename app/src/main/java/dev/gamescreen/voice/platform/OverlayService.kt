package dev.gamescreen.voice.platform

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.Context
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.IBinder
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import dev.gamescreen.voice.GameVoiceApp
import dev.gamescreen.voice.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

class OverlayService : Service() {
    companion object { const val ACTION_STOP = "dev.gamescreen.voice.STOP" }
    private val app get() = application as GameVoiceApp
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var wm: WindowManager
    private var panel: LinearLayout? = null
    private var content: LinearLayout? = null
    private lateinit var params: WindowManager.LayoutParams
    private lateinit var original: TextView
    private lateinit var translated: TextView
    private lateinit var status: TextView
    private lateinit var tts: TTSManager
    private var collectJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        tts = TTSManager(this, app.settings)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        // startForeground() MUST come first: after startForegroundService(), stopping the service
        // without it crashes the app ("did not then call Service.startForeground()").
        try {
            // specialUse exists only since API 34; API 29-33 use the 2-argument method.
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(33, createNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            } else {
                startForeground(33, createNotification())
            }
        } catch (_: Exception) {
            // e.g. ForegroundServiceStartNotAllowedException on Android 12+.
            stopSelf()
            return START_NOT_STICKY
        }
        if (!Settings.canDrawOverlays(this)) { stopSelf(); return START_NOT_STICKY }
        app.pipeline.start()
        if (panel == null) {
            try {
                createOverlay()
            } catch (_: Exception) {
                stopSelf()
                return START_NOT_STICKY
            }
        } else {
            // «Запустить» pressed again while running: apply new size/opacity without a restart.
            applyOptions()
        }
        if (collectJob?.isActive != true) {
            collectJob = scope.launch {
                app.pipeline.state.collectLatest { ui ->
                    original.text = ui.original.ifEmpty { "Нет текста" }
                    translated.text = ui.translated.ifEmpty { "Ожидание перевода" }
                    status.text = ui.status
                }
            }
        }
        return START_NOT_STICKY
    }

    private fun overlayWidth(scale: Float): Int {
        val desired = dp((330 * scale.coerceIn(.7f, 1.2f)).roundToInt())
        return desired.coerceAtMost((resources.displayMetrics.widthPixels - dp(16)).coerceAtLeast(dp(120)))
    }

    /** Keeps the window inside the screen (after drag, rotation or a size change). */
    private fun clampPosition() {
        val screen = resources.displayMetrics
        val maxX = (screen.widthPixels - params.width).coerceAtLeast(0)
        val maxY = (screen.heightPixels - dp(45)).coerceAtLeast(0)
        params.x = params.x.coerceIn(0, maxX)
        params.y = params.y.coerceIn(0, maxY)
    }

    private fun applyOptions() {
        val root = panel ?: return
        val options = app.settings.load()
        root.alpha = options.overlayAlpha.coerceIn(.6f, 1f)
        params.width = overlayWidth(options.sizeScale)
        clampPosition()
        try { wm.updateViewLayout(root, params) } catch (_: Exception) { }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        // Rotation: the window could end up off-screen and become impossible to drag back.
        applyOptions()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()
    private fun label(text: String, size: Float): TextView = TextView(this).apply {
        this.text = text; textSize = size; setTextColor(Color.WHITE)
        setPadding(dp(7), dp(5), dp(7), dp(5))
    }
    private fun button(text: String, listener: () -> Unit): Button = Button(this).apply {
        this.text = text
        this.textSize = 11f
        setOnClickListener { listener() }
        minWidth = 0; minimumWidth = 0
        setPadding(dp(2), 0, dp(2), 0)
    }

    private fun createOverlay() {
        val options = app.settings.load()
        params = WindowManager.LayoutParams(
            overlayWidth(options.sizeScale), WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.START; x = dp(15); y = dp(90) }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            alpha = options.overlayAlpha.coerceIn(.6f, 1f)
            background = GradientDrawable().apply {
                setColor(Color.rgb(25, 31, 39))
                cornerRadius = dp(12).toFloat()
                setStroke(dp(1), Color.rgb(93, 111, 130))
            }
        }
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val title = label("☰  GameScreen Voice", 13f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        }
        header.addView(title, LinearLayout.LayoutParams(0, dp(42), 1f))
        header.addView(button("−") {
            content?.visibility = if (content?.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            try { wm.updateViewLayout(root, params) } catch (_: Exception) { }
        })
        header.addView(button("×") { stopSelf() })
        root.addView(header)

        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        original = label("Нет текста", 12f)
        translated = label("Ожидание перевода", 15f)
        translated.setTextColor(Color.rgb(142, 233, 192))
        status = label("Ожидание", 10f)
        box.addView(original); box.addView(translated); box.addView(status)
        val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        actions.addView(button("Озвучить") {
            if (!tts.speak(app.pipeline.state.value.translated))
                status.text = "Голос пока недоступен или перевод пуст"
        }, LinearLayout.LayoutParams(0, dp(46), 1f))
        actions.addView(button("Копировать") {
            val value = app.pipeline.state.value.translated
            if (value.isNotBlank()) {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("translation", value))
                status.text = "Скопировано"
            }
        }, LinearLayout.LayoutParams(0, dp(46), 1f))
        actions.addView(button("Стоп") { tts.stop() }, LinearLayout.LayoutParams(0, dp(46), 1f))
        box.addView(actions)
        content = box
        root.addView(box)
        title.setOnTouchListener(object : View.OnTouchListener {
            private var x0 = 0
            private var y0 = 0
            private var rawX0 = 0f
            private var rawY0 = 0f
            override fun onTouch(v: View, event: MotionEvent): Boolean {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        x0 = params.x; y0 = params.y
                        rawX0 = event.rawX; rawY0 = event.rawY
                        return true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        val screen = resources.displayMetrics
                        val maxX = (screen.widthPixels - params.width).coerceAtLeast(0)
                        val maxY = (screen.heightPixels - dp(45)).coerceAtLeast(0)
                        params.x = (x0 + (event.rawX - rawX0).roundToInt()).coerceIn(0, maxX)
                        params.y = (y0 + (event.rawY - rawY0).roundToInt()).coerceIn(0, maxY)
                        try { wm.updateViewLayout(root, params) } catch (_: Exception) { stopSelf() }
                        return true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> return true
                }
                return false
            }
        })
        wm.addView(root, params)
        panel = root
    }

    private fun createNotification(): Notification {
        val channelId = "active_translation"
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(
            NotificationChannel(channelId, "Перевод экрана", NotificationManager.IMPORTANCE_LOW)
        )
        val stopIntent = PendingIntent.getService(this, 0,
            Intent(this, OverlayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_voice)
            .setContentTitle("GameScreen Voice работает")
            .setContentText("Перевод экрана активен. Остановить можно в уведомлении.")
            .setContentIntent(PendingIntent.getActivity(this, 0,
                Intent(this, dev.gamescreen.voice.ui.MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
            .setOngoing(true)
            .addAction(android.R.drawable.ic_media_pause, "Остановить", stopIntent)
            .build()
    }
    override fun onDestroy() {
        collectJob?.cancel(); scope.cancel()
        app.pipeline.stop()
        tts.release()
        try { stopForeground(STOP_FOREGROUND_REMOVE) } catch (_: Exception) { }
        panel?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        panel = null
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}
