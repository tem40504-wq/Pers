package dev.gamescreen.voice.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import android.media.projection.MediaProjectionManager
import dev.gamescreen.voice.GameVoiceApp
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.gamescreen.voice.capture.GameAccessibilityService
import dev.gamescreen.voice.platform.OverlayService

class MainActivity : ComponentActivity() {
    // Refreshed in onResume: the user returns here from the system settings screens.
    private var accessibilityOn by mutableStateOf(false)
    private var overlayAllowed by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        // targetSdk 35 forces edge-to-edge on Android 15; insets are handled in Screen().
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent { Screen(
            accessibilityOn = accessibilityOn,
            overlayAllowed = overlayAllowed,
            onOpenAccessibility = { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
            onOpenOverlay = { startActivity(Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )) },
            onStart = { startOverlay() },
            onStop = { stopService(Intent(this, OverlayService::class.java)) }
        ) }
    }

    override fun onResume() {
        super.onResume()
        accessibilityOn = GameAccessibilityService.isEnabled(this)
        overlayAllowed = Settings.canDrawOverlays(this)
    }

    // Audio mode: RECORD_AUDIO -> screen-capture consent (Android requires it for capturing other apps' sound).
    private val audioPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) requestProjection()
        else Toast.makeText(this, "Без разрешения «Микрофон» звук приложений захватить нельзя", Toast.LENGTH_LONG).show()
    }
    private val projectionConsent = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val data = res.data
        if (res.resultCode == RESULT_OK && data != null) {
            launchService(Intent(this, OverlayService::class.java)
                .putExtra(OverlayService.EXTRA_RESULT_CODE, res.resultCode)
                .putExtra(OverlayService.EXTRA_RESULT_DATA, data))
        } else {
            Toast.makeText(this, "Захват звука отклонён. Нажмите «Запустить» ещё раз и выберите «Начать».",
                Toast.LENGTH_LONG).show()
        }
    }

    private fun requestProjection() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        projectionConsent.launch(manager.createScreenCaptureIntent())
    }

    private fun startOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "Сначала разрешите отображение поверх окон", Toast.LENGTH_LONG).show()
            return
        }
        // Ask before the service posts its notification, otherwise it stays hidden on Android 13+.
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
        }
        if ((application as GameVoiceApp).settings.load().audioMode) {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                requestProjection()
            } else {
                audioPermission.launch(Manifest.permission.RECORD_AUDIO)
            }
            return
        }
        launchService(Intent(this, OverlayService::class.java))
        if (!GameAccessibilityService.isEnabled(this)) {
            Toast.makeText(this, "Окно запущено, но Accessibility выключен — текст читаться не будет",
                Toast.LENGTH_LONG).show()
        }
    }

    private fun launchService(intent: Intent) {
        try {
            startForegroundService(intent)
        } catch (e: RuntimeException) {
            Toast.makeText(this, "Не удалось запустить сервис: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }
}

@Composable
private fun Screen(
    accessibilityOn: Boolean,
    overlayAllowed: Boolean,
    onOpenAccessibility: () -> Unit,
    onOpenOverlay: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    vm: MainViewModel = viewModel()
) {
    val s by vm.settings.collectAsStateWithLifecycle()
    val translation by vm.currentTranslation.collectAsStateWithLifecycle()
    val history by vm.history.collectAsStateWithLifecycle(emptyList())
    val apps by vm.installedApps.collectAsStateWithLifecycle()
    var secret by remember { mutableStateOf("") }
    var apiKeySaved by remember { mutableStateOf(vm.hasApiKey()) }
    var savedMessage by remember { mutableStateOf("") }
    var showPicker by remember { mutableStateOf(false) }
    MaterialTheme(colorScheme = if (s.darkTheme) darkColorScheme() else lightColorScheme()) {
        // Surface paints the theme background and sets content colors; without it the dark
        // theme drew light text on the light window background of the activity theme.
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(9.dp)) {
            Text("GameScreen Voice 0.2.3", style = MaterialTheme.typography.headlineSmall)
            Text(if (s.audioMode) "Звук приложения → распознавание речи → перевод → озвучка"
                else "Текст на экране → перевод → окно → озвучка")
            Text("Режим", style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (s.audioMode) Button(onClick = {}, modifier = Modifier.weight(1f)) { Text("Звук (речь)") }
                else OutlinedButton(onClick = { vm.edit(s.copy(audioMode = true)) }, modifier = Modifier.weight(1f)) { Text("Звук (речь)") }
                if (!s.audioMode) Button(onClick = {}, modifier = Modifier.weight(1f)) { Text("Текст на экране") }
                else OutlinedButton(onClick = { vm.edit(s.copy(audioMode = false)) }, modifier = Modifier.weight(1f)) { Text("Текст на экране") }
            }
            if (s.audioMode) {
                Text("Переводит речь из видео и игр. Язык речи — поле «Из» (EN по умолчанию). При первом запуске " +
                    "скачивается модель распознавания ~40 МБ, затем всё работает офлайн. Android попросит разрешения " +
                    "«Микрофон» и «Запись/трансляция экрана» — это стандартный способ получить звук других приложений; " +
                    "изображение не записывается. Некоторые приложения запрещают захват своего звука.",
                    style = MaterialTheme.typography.bodySmall)
            }
            Card { Column(Modifier.padding(12.dp)) {
                Text("Согласие на обработку текста", style = MaterialTheme.typography.titleMedium)
                Text("Сервис читает доступный для Accessibility текст только из указанного приложения. " +
                    "Без ключа DeepL текст переводится на телефоне (Google ML Kit); с ключом — отправляется в DeepL. " +
                    "История сохраняется локально только по выбору. " +
                    "Не используйте с банковскими приложениями, чатами и конфиденциальной информацией.")
                Row { Checkbox(checked = s.consent, onCheckedChange = { vm.setConsent(it) })
                    Text("Согласен включить сервис с указанной обработкой данных", Modifier.padding(top = 12.dp)) }
            } }
            Text((if (s.audioMode) "" else "Accessibility: ${if (accessibilityOn) "✓ включено" else "✗ выключено"}   •   ") +
                "Окно поверх: ${if (overlayAllowed) "✓ разрешено" else "✗ не разрешено"}",
                style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!s.audioMode) Button(onClick = onOpenAccessibility, modifier = Modifier.weight(1f)) { Text("Accessibility") }
                Button(onClick = onOpenOverlay, modifier = Modifier.weight(1f)) { Text("Окно поверх") }
            }
            if (!s.audioMode) {
            OutlinedTextField(
                s.selectedPackage,
                { vm.edit(s.copy(selectedPackage = it)) },
                label = { Text("Пакет приложения (например, com.example.app)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true
            )
            OutlinedButton(onClick = { vm.loadInstalledApps(); showPicker = true },
                modifier = Modifier.fillMaxWidth()) { Text("Выбрать из установленных приложений") }
            Text("Без указанного пакета чтение экрана отключено.", style = MaterialTheme.typography.bodySmall)
            Row { Switch(s.ocrEnabled, { vm.edit(s.copy(ocrEnabled = it)) });
                Text("Субтитры с картинки (OCR, Android 11+)", Modifier.padding(12.dp)) }
            if (s.ocrEnabled) {
                Text("Для игр и видео, где текст нарисован, а не доступен как текст. Снимок нижней части экрана " +
                    "распознаётся на телефоне (латиница), картинки никуда не отправляются.",
                    style = MaterialTheme.typography.bodySmall)
                Text("Область: нижние ${s.ocrBottomPercent}% экрана")
                Slider(s.ocrBottomPercent.toFloat(), { vm.edit(s.copy(ocrBottomPercent = it.toInt())) },
                    valueRange = 15f..100f)
                Text("Сканировать каждые ${"%.1f".format(s.ocrIntervalMs / 1000f)} с (чаще — больше расход батареи)")
                Slider(s.ocrIntervalMs.toFloat(), { vm.edit(s.copy(ocrIntervalMs = (it / 500).toLong() * 500)) },
                    valueRange = 2000f..15000f)
                Row { Switch(s.subtitleNoiseFilter, { vm.edit(s.copy(subtitleNoiseFilter = it)) });
                    Text("Пропускать кнопки плеера и таймкоды", Modifier.padding(12.dp)) }
            }
            }
            Text("Перевод: ${if (s.offlineOnly || !apiKeySaved) "офлайн на телефоне (бесплатно, без ключа)" else "DeepL"}",
                style = MaterialTheme.typography.titleSmall)
            Text("Ключ DeepL необязателен. Без него перевод выполняется на телефоне через Google ML Kit; " +
                "при первом переводе загружается языковая модель ~30 МБ (нужен интернет), дальше работает офлайн.",
                style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(
                secret, { secret = it }, modifier = Modifier.fillMaxWidth(),
                label = { Text(if (apiKeySaved) "DeepL API key (уже сохранён)" else "DeepL API key (необязательно)") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true
            )
            Text("Free или Pro определяется по ключу автоматически: ключи DeepL Free оканчиваются на «:fx».",
                style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(s.sourceLang, { vm.edit(s.copy(sourceLang = it)) },
                    label = { Text("Из (пусто = авто)") }, modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(s.targetLang, { vm.edit(s.copy(targetLang = it)) },
                    label = { Text("На (RU)") }, modifier = Modifier.weight(1f), singleLine = true)
            }
            OutlinedTextField(s.voiceName, { vm.edit(s.copy(voiceName = it)) },
                label = { Text("Имя установленного TTS-голоса (необязательно)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Row { Switch(s.autoSpeechSpeed, { vm.edit(s.copy(autoSpeechSpeed = it)) });
                Text("Автоскорость речи (подстраивается под темп фраз)", Modifier.padding(12.dp)) }
            Text(if (s.autoSpeechSpeed) "Поправка к автоскорости: ${"%.2f".format(s.speechSpeed)}×"
                else "Скорость речи: ${"%.2f".format(s.speechSpeed)}×")
            Slider(s.speechSpeed, { vm.edit(s.copy(speechSpeed = it)) }, valueRange = .5f..1.7f)
            Text("Задержка обработки: ${s.delayMs} мс")
            Slider(s.delayMs.toFloat(), { vm.edit(s.copy(delayMs = it.toLong())) }, valueRange = 200f..2500f)
            Text("Прозрачность: ${(s.overlayAlpha * 100).toInt()}%")
            Slider(s.overlayAlpha, { vm.edit(s.copy(overlayAlpha = it)) }, valueRange = .6f..1f)
            Text("Масштаб окна: ${"%.2f".format(s.sizeScale)}×")
            Slider(s.sizeScale, { vm.edit(s.copy(sizeScale = it)) }, valueRange = .7f..1.2f)
            Row { Switch(s.darkTheme, { vm.edit(s.copy(darkTheme = it)) });
                Text("Тёмная тема", Modifier.padding(12.dp)) }
            Row { Switch(s.autoSpeak, { vm.edit(s.copy(autoSpeak = it)) });
                Text("Озвучивать перевод автоматически", Modifier.padding(12.dp)) }
            Row { Switch(s.duckOriginal, { vm.edit(s.copy(duckOriginal = it)) });
                Text("Приглушать оригинал во время озвучки (некоторые плееры ставят паузу)", Modifier.padding(12.dp)) }
            Row { Switch(s.offlineOnly, { vm.edit(s.copy(offlineOnly = it)) });
                Text("Всегда офлайн-перевод, даже если есть ключ DeepL", Modifier.padding(12.dp)) }
            Row { Switch(s.keepHistory, { vm.edit(s.copy(keepHistory = it)) });
                Text("Сохранять историю локально", Modifier.padding(12.dp)) }
            Button(onClick = { vm.save(secret); secret = ""; apiKeySaved = vm.hasApiKey(); savedMessage = "Настройки сохраняются автоматически; ключ сохранён" },
                modifier = Modifier.fillMaxWidth()) { Text("Сохранить API-ключ") }
            if (savedMessage.isNotEmpty()) Text(savedMessage)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    when {
                        !s.audioMode && s.selectedPackage.trim().isBlank() ->
                            savedMessage = "Укажите пакет приложения для чтения текста"
                        else -> {
                            vm.save(secret)
                            secret = ""
                            apiKeySaved = vm.hasApiKey()
                            savedMessage = "Настройки сохранены; сервис запущен. " +
                                "Повторное нажатие применяет размер и прозрачность окна."
                            onStart()
                        }
                    }
                }, enabled = s.consent,
                    modifier = Modifier.weight(1f)) { Text("Запустить") }
                OutlinedButton(onClick = onStop, modifier = Modifier.weight(1f)) { Text("Остановить") }
            }
            OutlinedButton(onClick = {
                vm.save(secret)
                secret = ""
                apiKeySaved = vm.hasApiKey()
                vm.sendDemo()
            }, modifier = Modifier.fillMaxWidth()) {
                Text("Тест: перевести Hello world")
            }
            Text("Состояние: ${translation.status}")
            if (translation.translated.isNotBlank()) Text(translation.translated)
            HorizontalDivider()
            Text("История (${history.size} последних)", style = MaterialTheme.typography.titleMedium)
            history.take(5).forEach { item ->
                Text("${item.original.take(70)} → ${item.translated.take(70)}",
                    style = MaterialTheme.typography.bodySmall)
            }
            TextButton(onClick = { vm.clearHistory() }) { Text("Очистить историю") }
            TextButton(onClick = {
                vm.clearApiKey()
                apiKeySaved = false
                savedMessage = "Ключ удалён"
            }) {
                Text("Удалить API-ключ")
            }
        }
        }
        if (showPicker) {
            AppPickerDialog(
                apps = apps,
                onPick = { vm.edit(s.copy(selectedPackage = it)); showPicker = false },
                onDismiss = { showPicker = false }
            )
        }
    }
}

@Composable
private fun AppPickerDialog(apps: List<AppEntry>?, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    var query by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Закрыть") } },
        title = { Text("Приложение-источник") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(query, { query = it }, label = { Text("Поиск") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())
                if (apps == null) {
                    Text("Загрузка списка…")
                } else {
                    val filtered = apps.filter {
                        query.isBlank() || it.label.contains(query, ignoreCase = true) ||
                            it.packageName.contains(query, ignoreCase = true)
                    }
                    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                        items(filtered, key = { it.packageName }) { entry ->
                            Column(Modifier.fillMaxWidth().clickable { onPick(entry.packageName) }
                                .padding(vertical = 8.dp)) {
                                Text(entry.label)
                                Text(entry.packageName, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }
    )
}
