package dev.gamescreen.voice.data

import android.content.Context
import android.content.SharedPreferences

data class VoiceSettings(
    /** Empty = DeepL auto-detects the source language. */
    val sourceLang: String = "EN",
    val targetLang: String = "RU",
    val speechSpeed: Float = 1f,
    val overlayAlpha: Float = 0.95f,
    val delayMs: Long = 600L,
    val sizeScale: Float = 1f,
    val voiceName: String = "",
    val selectedPackage: String = "",
    val darkTheme: Boolean = true,
    val keepHistory: Boolean = false,
    val consent: Boolean = false,
    /** Always use on-device ML Kit, even if a DeepL key is saved. */
    val offlineOnly: Boolean = false
)

class SettingsStore(context: Context) {
    companion object {
        const val KEY_PACKAGE = "package"
    }
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    fun load(): VoiceSettings = VoiceSettings(
        sourceLang = prefs.getString("source", "EN") ?: "EN",
        targetLang = prefs.getString("target", "RU") ?: "RU",
        speechSpeed = prefs.getFloat("speed", 1f),
        overlayAlpha = prefs.getFloat("alpha", .95f),
        delayMs = prefs.getLong("delay", 600L),
        sizeScale = prefs.getFloat("size", 1f),
        voiceName = prefs.getString("voice", "") ?: "",
        selectedPackage = prefs.getString(KEY_PACKAGE, "") ?: "",
        darkTheme = prefs.getBoolean("dark", true),
        keepHistory = prefs.getBoolean("history", false),
        consent = prefs.getBoolean("consent", false),
        offlineOnly = prefs.getBoolean("offline", false)
    )
    fun save(s: VoiceSettings) {
        prefs.edit()
            .putString("source", s.sourceLang.trim().uppercase())
            .putString("target", s.targetLang.trim().uppercase().ifEmpty { "RU" })
            .putFloat("speed", s.speechSpeed)
            .putFloat("alpha", s.overlayAlpha)
            .putLong("delay", s.delayMs)
            .putFloat("size", s.sizeScale)
            .putString("voice", s.voiceName.trim())
            .putString(KEY_PACKAGE, s.selectedPackage.trim())
            .putBoolean("dark", s.darkTheme)
            .putBoolean("history", s.keepHistory)
            .putBoolean("consent", s.consent)
            .putBoolean("offline", s.offlineOnly)
            .apply()
    }
    /** Consent is stored immediately, independent of the «Save» button. */
    fun saveConsent(value: Boolean) { prefs.edit().putBoolean("consent", value).apply() }

    /** SharedPreferences keeps listeners in a WeakHashMap: callers must hold a strong reference. */
    fun registerListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.registerOnSharedPreferenceChangeListener(listener)
    fun unregisterListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.unregisterOnSharedPreferenceChangeListener(listener)
}
