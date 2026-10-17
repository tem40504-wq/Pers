package dev.gamescreen.voice.capture

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityService.ScreenshotResult
import android.accessibilityservice.AccessibilityService.TakeScreenshotCallback
import android.graphics.Bitmap
import android.graphics.ColorSpace
import android.os.Build
import android.view.Display
import dev.gamescreen.voice.platform.OverlayService
import kotlinx.coroutines.isActive
import java.util.concurrent.atomic.AtomicBoolean
import android.content.ComponentName
import android.content.Context
import android.content.SharedPreferences
import android.os.SystemClock
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import dev.gamescreen.voice.GameVoiceApp
import dev.gamescreen.voice.data.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.ArrayDeque

/** Only the manually selected package is eligible for extraction.
 * Never capture text from editable/password fields. Debounce to capture the final UI state.
 */
class GameAccessibilityService : AccessibilityService() {
    companion object {
        private const val DEBOUNCE_MS = 260L
        /** Upper bound for debounce: constantly animating UIs must still be read. */
        private const val MAX_WAIT_MS = 1_000L
        private const val MAX_NODES = 200
        private const val MAX_CHARS = 1400
        private val WHITESPACE = Regex("\\s+")
        @Volatile private var activeService: GameAccessibilityService? = null
        private val NOISE_WORDS = Regex("(?i)^(play|pause|subscribe|like|share|comments?|settings|skip ad|skip|next|previous|menu|options|подписаться|комментарии|назад|пропустить)$")
        private val TIMECODE = Regex("^\\d{1,2}:\\d{2}(?::\\d{2})?(?:\\s*/\\s*\\d{1,2}:\\d{2}(?::\\d{2})?)?$")

        /** «Скан OCR» in the floating window. */
        fun requestOcrNow(context: Context) {
            val active = activeService
            if (active == null) {
                (context.applicationContext as? GameVoiceApp)?.pipeline
                    ?.postStatus("OCR: включите GameScreen Voice в «Специальных возможностях»")
            } else active.requestOcr(manual = true)
        }

        fun isEnabled(context: Context): Boolean {
            val expected = ComponentName(context, GameAccessibilityService::class.java)
            val enabled = Settings.Secure.getString(
                context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            return enabled.split(':').any { ComponentName.unflattenFromString(it) == expected }
        }
    }

    private val app get() = application as GameVoiceApp
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var pending: Job? = null
    private var pendingSince = 0L
    private val ocrBusy = AtomicBoolean(false)
    private var ocrEngine: OcrEngine? = null
    private var ocrLoop: Job? = null

    // Strong reference: SharedPreferences holds listeners weakly.
    private val packageListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == SettingsStore.KEY_PACKAGE) applyPackageFilter()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        applyPackageFilter()
        app.settings.registerListener(packageListener)
        activeService = this
        ocrLoop?.cancel()
        ocrLoop = scope.launch {
            while (isActive) {
                val c = app.settings.load()
                val ocrOn = c.ocrEnabled && !c.audioMode
                delay(if (ocrOn) c.ocrIntervalMs.coerceIn(2000, 15000) else 1500)
                val now = app.settings.load()
                if (now.ocrEnabled && !now.audioMode && app.pipeline.isEnabled) requestOcr(manual = false)
            }
        }
    }

    /** The system delivers events only from the selected package (privacy + far fewer wake-ups). */
    private fun applyPackageFilter() {
        val info = serviceInfo ?: return
        val selected = app.settings.load().selectedPackage.trim()
        // Nothing selected: listen only to ourselves, which onAccessibilityEvent ignores anyway.
        info.packageNames = arrayOf(selected.ifBlank { packageName })
        serviceInfo = info
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null || !app.pipeline.isEnabled) return
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            event.eventType != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED &&
            event.eventType != AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED) return
        val settings = app.settings.load()
        if (settings.audioMode) return // audio mode translates speech, not screen text
        if (settings.ocrEnabled) return // subtitles are read from screenshots instead
        val allowed = settings.selectedPackage
        if (allowed.isBlank() || allowed == packageName || allowed == "com.android.systemui") return
        if (event.packageName?.toString() != allowed) return

        val now = SystemClock.elapsedRealtime()
        if (pending?.isActive == true) {
            // Already waited long enough: let the scheduled read happen instead of postponing it again.
            if (now - pendingSince >= MAX_WAIT_MS) return
            pending?.cancel()
        } else {
            pendingSince = now
        }
        pending = scope.launch {
            delay(DEBOUNCE_MS)
            if (!app.pipeline.isEnabled || app.settings.load().selectedPackage != allowed) return@launch
            val root = rootInActiveWindow ?: return@launch
            // Events can arrive during a window transition: do not read the next app's UI.
            if (root.packageName?.toString() != allowed) {
                recycle(root)
                return@launch
            }
            val text = extract(root)
            if (text.isNotBlank()) app.pipeline.submit(allowed, text)
        }
    }

    private fun extract(root: AccessibilityNodeInfo): String {
        val queue: ArrayDeque<AccessibilityNodeInfo> = ArrayDeque()
        val visited = ArrayList<AccessibilityNodeInfo>(MAX_NODES)
        val fragments = linkedSetOf<String>()
        queue.add(root)
        var totalChars = 0
        try {
            while (queue.isNotEmpty() && visited.size < MAX_NODES && totalChars < MAX_CHARS) {
                val node = queue.removeFirst()
                visited.add(node)
                if (!node.isVisibleToUser || node.isPassword || node.isEditable ||
                    node.className?.toString()?.endsWith("EditText") == true) continue
                // Only visible text, and not from controls: buttons, tabs and icons ("Поиск", "Подписаться",
                // "0 минут 0 секунд из …") are interface, not content. Their children are still visited.
                val className = node.className?.toString().orEmpty()
                val isControl = node.isClickable || node.isLongClickable || node.isCheckable ||
                    className.endsWith("Button") || className.endsWith("SeekBar") || className.endsWith("Tab")
                val item = if (isControl) "" else node.text?.toString()
                    ?.replace(WHITESPACE, " ")?.trim().orEmpty()
                if (item.length in 2..250 && totalChars + item.length <= MAX_CHARS && fragments.add(item)) {
                    totalChars += item.length
                }
                for (i in 0 until node.childCount) {
                    node.getChild(i)?.let { queue.addLast(it) }
                }
            }
        } finally {
            // Android 10-12 keep a native pool of node objects; return them (no-op on 13+).
            visited.forEach { recycle(it) }
            queue.forEach { recycle(it) }
        }
        return fragments.joinToString("\n")
    }

    @Suppress("DEPRECATION")
    private fun recycle(node: AccessibilityNodeInfo) {
        try { node.recycle() } catch (_: IllegalStateException) { }
    }

    /** Never capture the screen outside the package explicitly chosen by the user. */
    private fun isSelectedAppForeground(): Boolean {
        val target = app.settings.load().selectedPackage.trim()
        if (target.isBlank() || target == packageName || target == "com.android.systemui") return false
        val root = rootInActiveWindow ?: return false
        return try { root.packageName?.toString() == target } finally { recycle(root) }
    }

    /** Drops obvious player controls and timecodes recognised by OCR. */
    private fun filterCaptionNoise(text: String): String =
        text.lines().map { it.trim() }.filter { it.isNotBlank() }
            .filterNot { NOISE_WORDS.matches(it) || TIMECODE.matches(it) }
            .joinToString("\n").take(1400)

    private fun reportOcr(message: String, manual: Boolean) {
        // Automatic OCR runs every few seconds: do not cover a translation with repetitive messages.
        if (manual || message.startsWith("OCR: ошибка")) app.pipeline.postStatus(message)
    }

    /** OCR of the bottom part of the screen (subtitles), ported from 0.2.2. Android 11+. */
    private fun requestOcr(manual: Boolean) {
        if (!app.pipeline.isEnabled) {
            reportOcr("OCR: сначала нажмите «Запустить»", manual); return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            reportOcr("OCR работает на Android 11 и новее", manual); return
        }
        if (!isSelectedAppForeground()) {
            reportOcr("OCR: откройте выбранное приложение", manual); return
        }
        if (!ocrBusy.compareAndSet(false, true)) {
            reportOcr("OCR: предыдущий снимок ещё обрабатывается", manual); return
        }
        // Our own window must not get into the screenshot.
        OverlayService.setCaptureHidden(true)
        scope.launch {
            delay(200)
            if (!app.pipeline.isEnabled || !isSelectedAppForeground()) {
                OverlayService.setCaptureHidden(false)
                ocrBusy.set(false)
                return@launch
            }
            try {
                takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                    override fun onFailure(errorCode: Int) {
                        OverlayService.setCaptureHidden(false)
                        ocrBusy.set(false)
                        reportOcr("OCR: ошибка снимка ($errorCode) — возможно, экран защищён", manual)
                    }

                    override fun onSuccess(screenshot: ScreenshotResult) {
                        OverlayService.setCaptureHidden(false)
                        var whole: Bitmap? = null
                        var part: Bitmap? = null
                        try {
                            val hw = screenshot.hardwareBuffer
                            try {
                                val space = screenshot.colorSpace ?: ColorSpace.get(ColorSpace.Named.SRGB)
                                whole = Bitmap.wrapHardwareBuffer(hw, space)
                                    ?.copy(Bitmap.Config.ARGB_8888, false)
                                    ?: throw IllegalStateException("снимок недоступен")
                            } finally { hw.close() }
                            val image = whole!!
                            val c = app.settings.load()
                            val top = image.height * (100 - c.ocrBottomPercent.coerceIn(15, 100)) / 100
                            part = if (top > 0) Bitmap.createBitmap(image, 0, top, image.width, image.height - top) else image
                            val crop = part!!
                            val engine = ocrEngine ?: OcrEngine().also { ocrEngine = it }
                            engine.recognize(crop) { result ->
                                try {
                                    if (!app.pipeline.isEnabled) return@recognize
                                    result.onSuccess { recognized ->
                                        val clean = recognized.trim().take(1400)
                                        val s2 = app.settings.load()
                                        val text = if (s2.subtitleNoiseFilter) filterCaptionNoise(clean) else clean
                                        if (text.isNotBlank()) app.pipeline.submit(s2.selectedPackage, text)
                                        else reportOcr("OCR: текст не найден", manual)
                                    }.onFailure {
                                        reportOcr("OCR: ошибка распознавания: ${it.message.orEmpty().take(70)}", manual)
                                    }
                                } finally {
                                    if (crop !== image) crop.recycle()
                                    image.recycle()
                                    ocrBusy.set(false)
                                }
                            }
                        } catch (e: Exception) {
                            if (part !== whole) part?.recycle()
                            whole?.recycle()
                            ocrBusy.set(false)
                            reportOcr("OCR: ошибка обработки: ${e.message.orEmpty().take(70)}", manual)
                        }
                    }
                })
            } catch (e: Exception) {
                OverlayService.setCaptureHidden(false)
                ocrBusy.set(false)
                reportOcr("OCR: ошибка снимка: ${e.message.orEmpty().take(70)}", manual)
            }
        }
    }

    override fun onInterrupt() { pending?.cancel() }
    override fun onDestroy() {
        app.settings.unregisterListener(packageListener)
        if (activeService === this) activeService = null
        ocrLoop?.cancel()
        ocrEngine?.close()
        pending?.cancel()
        scope.cancel()
        super.onDestroy()
    }
}
