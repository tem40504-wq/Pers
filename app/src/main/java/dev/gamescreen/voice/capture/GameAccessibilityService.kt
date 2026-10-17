package dev.gamescreen.voice.capture

import android.accessibilityservice.AccessibilityService
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

    // Strong reference: SharedPreferences holds listeners weakly.
    private val packageListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == SettingsStore.KEY_PACKAGE) applyPackageFilter()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        applyPackageFilter()
        app.settings.registerListener(packageListener)
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

    override fun onInterrupt() { pending?.cancel() }
    override fun onDestroy() {
        app.settings.unregisterListener(packageListener)
        pending?.cancel()
        scope.cancel()
        super.onDestroy()
    }
}
