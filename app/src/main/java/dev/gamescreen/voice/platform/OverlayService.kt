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
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import dev.gamescreen.voice.capture.GameAccessibilityService
import dev.gamescreen.voice.audio.SpeechCaptureEngine
import dev.gamescreen.voice.audio.VoskModels
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
    companion object {
        const val ACTION_STOP = "dev.gamescreen.voice.STOP"
        /** Audio mode: MediaProjection consent result from MainActivity. */
        const val EXTRA_RESULT_CODE = "projection_result_code"
        const val EXTRA_RESULT_DATA = "projection_result_data"
        @Volatile private var active: OverlayService? = null

        /** Hide our own window while the OCR screenshot is taken (otherwise we would translate ourselves). */
        fun setCaptureHidden(hidden: Boolean) {
            active?.panel?.visibility = if (hidden) View.INVISIBLE else View.VISIBLE
        }
    }
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
    private var speakJob: Job? = null
    private var projection: MediaProjection? = null
    private var speech: SpeechCaptureEngine? = null
    // Panel state (from 0.2.2): collapsed to an edge tab, text hidden, voice paused.
    private var compact = false
    private var showText = true
    private var pausedSpeech = false
    private var panelHeader: LinearLayout? = null
    private var miniButton: Button? = null
    private val recentSpoken = LinkedHashMap<String, Long>()

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        tts = TTSManager(this, app.settings) { msg -> app.pipeline.postStatus(msg) }
        active = this
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { stopSelf(); return START_NOT_STICKY }
        // startForeground() MUST come first: after startForegroundService(), stopping the service
        // without it crashes the app ("did not then call Service.startForeground()").
        val projectionData: Intent? = if (Build.VERSION.SDK_INT >= 33) {
            intent?.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION") intent?.getParcelableExtra(EXTRA_RESULT_DATA)
        }
        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, 0) ?: 0
        val audio = projectionData != null
        try {
            // specialUse exists only since API 34; mediaProjection must be declared before getMediaProjection().
            when {
                Build.VERSION.SDK_INT >= 34 -> startForeground(33, createNotification(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE or
                        (if (audio) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0))
                audio -> startForeground(33, createNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
                else -> startForeground(33, createNotification())
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
        if (audio) startSpeechCapture(resultCode, projectionData!!) else stopSpeechCapture()
        if (speakJob?.isActive != true) {
            speakJob = scope.launch {
                app.pipeline.results.collect { item ->
                    if (pausedSpeech || !app.settings.load().autoSpeak) return@collect
                    // OCR may re-read the same subtitle after a short flicker: do not repeat it for 12 s.
                    val now = SystemClock.elapsedRealtime()
                    recentSpoken.entries.removeAll { now - it.value > 12_000L }
                    if (!item.queue && recentSpoken.containsKey(item.text)) return@collect
                    recentSpoken[item.text] = now
                    if (tts.speak(item.text, queue = item.queue) && tts.lastEstimatedWpm > 0) {
                        app.pipeline.postStatus(app.pipeline.state.value.status.substringBefore(" · ≈") +
                            " · ≈${tts.lastEstimatedWpm} сл/мин")
                    }
                }
            }
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

    private fun startSpeechCapture(resultCode: Int, data: Intent) {
        stopSpeechCapture()
        val manager = getSystemService(MediaProjectionManager::class.java)
        val mp = try { manager.getMediaProjection(resultCode, data) } catch (e: Exception) { null }
        if (mp == null) {
            app.pipeline.postStatus("Нет разрешения на захват звука")
            return
        }
        mp.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                scope.launch {
                    // Ignore the callback of an old projection we replaced ourselves.
                    if (projection !== mp) return@launch
                    stopSpeechCapture()
                    app.pipeline.postStatus("Захват звука остановлен")
                }
            }
        }, Handler(Looper.getMainLooper()))
        projection = mp
        val language = VoskModels.languageOf(app.settings.load().sourceLang)
        speech = SpeechCaptureEngine(
            context = applicationContext,
            projection = mp,
            language = language,
            onStatus = { msg -> app.pipeline.postStatus(msg) },
            onPartial = { text -> app.pipeline.postPartial(text) },
            onPhrase = { text -> app.pipeline.submitSpeech(text) }
        ).also { it.start() }
    }

    private fun stopSpeechCapture() {
        speech?.stop()
        speech = null
        projection?.let { try { it.stop() } catch (_: Exception) { } }
        projection = null
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
        params.width = if (compact) dp(74) else overlayWidth(options.sizeScale)
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
        panelHeader = header
        val title = label("☰ GSV", 13f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
            contentDescription = "Удерживайте и перетащите, чтобы передвинуть окно"
        }
        header.addView(title, LinearLayout.LayoutParams(0, dp(42), 1f))
        header.addView(button("Текст") { toggleText() })
        header.addView(button("В край") { setCompact(true) })
        header.addView(button("×") { stopSelf() }.apply {
            contentDescription = "Остановить перевод и закрыть окно"
        })
        root.addView(header)
        val mini = button("GSV ▶") { setCompact(false) }.apply {
            visibility = View.GONE
            contentDescription = "Развернуть GameScreen Voice"
        }
        miniButton = mini
        root.addView(mini)

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
        val tools = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val pause = button("Пауза озвучки") { }
        pause.setOnClickListener {
            pausedSpeech = !pausedSpeech
            if (pausedSpeech) tts.stop()
            pause.text = if (pausedSpeech) "Продолжить" else "Пауза озвучки"
            app.pipeline.postStatus(if (pausedSpeech) "Озвучка на паузе · перевод продолжается" else "Озвучка включена")
        }
        tools.addView(pause, LinearLayout.LayoutParams(0, dp(44), 1f))
        tools.addView(button("Повторить") {
            if (!tts.speak(app.pipeline.state.value.translated)) status.text = "Нет перевода или голоса"
        }, LinearLayout.LayoutParams(0, dp(44), 1f))
        tools.addView(button("Скан OCR") {
            GameAccessibilityService.requestOcrNow(this@OverlayService)
        }, LinearLayout.LayoutParams(0, dp(44), 1f))
        box.addView(tools)
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
    /** «Текст»: hide only the text block; translation and voice continue. */
    private fun toggleText() {
        showText = !showText
        content?.visibility = if (showText) View.VISIBLE else View.GONE
        panel?.let { try { wm.updateViewLayout(it, params) } catch (_: Exception) { } }
    }

    /** «В край»: collapse to a small «GSV ▶» tab at the nearest screen edge. Unlike «×», keeps working. */
    private fun setCompact(mini: Boolean) {
        compact = mini
        panelHeader?.visibility = if (mini) View.GONE else View.VISIBLE
        miniButton?.visibility = if (mini) View.VISIBLE else View.GONE
        content?.visibility = if (!mini && showText) View.VISIBLE else View.GONE
        if (mini) {
            val screenWidth = resources.displayMetrics.widthPixels
            val oldCenter = params.x + params.width / 2
            params.width = dp(74)
            params.x = if (oldCenter < screenWidth / 2) 0 else (screenWidth - params.width).coerceAtLeast(0)
        } else {
            params.width = overlayWidth(app.settings.load().sizeScale)
        }
        clampPosition()
        panel?.let { try { wm.updateViewLayout(it, params) } catch (_: Exception) { } }
    }

    override fun onDestroy() {
        if (active === this) active = null
        stopSpeechCapture()
        speakJob?.cancel()
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
