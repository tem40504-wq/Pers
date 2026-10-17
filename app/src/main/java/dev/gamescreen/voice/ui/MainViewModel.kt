package dev.gamescreen.voice.ui

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.gamescreen.voice.GameVoiceApp
import dev.gamescreen.voice.data.VoiceSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AppEntry(val label: String, val packageName: String)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as GameVoiceApp
    private val mutableSettings = MutableStateFlow(app.settings.load())
    val settings = mutableSettings.asStateFlow()
    val currentTranslation = app.pipeline.state
    val history = app.database.translations().latest()

    private val mutableApps = MutableStateFlow<List<AppEntry>?>(null)
    /** null = not loaded yet. */
    val installedApps = mutableApps.asStateFlow()

    /** Every change is stored at once, so a running service sees it immediately (no «Save» needed). */
    fun edit(value: VoiceSettings) {
        mutableSettings.value = value
        app.settings.save(value)
    }
    fun save(key: String) {
        app.settings.save(mutableSettings.value)
        if (key.isNotBlank()) app.secrets.writeApiKey(key)
    }
    fun setConsent(value: Boolean) {
        mutableSettings.value = mutableSettings.value.copy(consent = value)
        app.settings.saveConsent(value)
    }
    fun hasApiKey(): Boolean = !app.secrets.readApiKey().isNullOrBlank()
    fun clearApiKey() { app.secrets.writeApiKey("") }
    fun clearHistory() = viewModelScope.launch {
        app.database.translations().clear()
        app.pipeline.clearMemoryCache()
    }
    fun sendDemo() { app.pipeline.testTranslation() }

    /** Launcher apps only; visible on Android 11+ thanks to the <queries> LAUNCHER declaration. */
    fun loadInstalledApps() {
        if (mutableApps.value != null) return
        viewModelScope.launch(Dispatchers.IO) {
            val pm = app.packageManager
            val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            @Suppress("DEPRECATION")
            val list = pm.queryIntentActivities(launcher, 0)
                .map { AppEntry(it.loadLabel(pm).toString(), it.activityInfo.packageName) }
                .filter { it.packageName != app.packageName }
                .distinctBy { it.packageName }
                .sortedBy { it.label.lowercase() }
            mutableApps.value = list
        }
    }
}
