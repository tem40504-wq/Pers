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
        try {
            startForegroundService(Intent(this, OverlayService::class.java))
            if (!GameAccessibilityService.isEnabled(this)) {
                Toast.makeText(this, "Окно запущено, но Accessibility выключен — текст читаться не будет",
                    Toast.LENGTH_LONG).show()
            }
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
            Text("GameScreen Voice 0.1.2", style = MaterialTheme.typography.headlineSmall)
            Text("MVP: Accessibility → DeepL → плавающее окно → TTS")
            Card { Column(Modifier.padding(12.dp)) {
                Text("Согласие на обработку текста", style = MaterialTheme.typography.titleMedium)
                Text("Сервис читает доступный для Accessibility текст только из указанного приложения. " +
                    "Текст отправляется выбранному провайдеру перевода DeepL. " +
                    "История сохраняется локально только по выбору. " +
                    "Не используйте с банковскими приложениями, чатами и конфиденциальной информацией.")
                Row { Checkbox(checked = s.consent, onCheckedChange = { vm.setConsent(it) })
                    Text("Согласен включить сервис с указанной обработкой данных", Modifier.padding(top = 12.dp)) }
            } }
            Text("Accessibility: ${if (accessibilityOn) "✓ включено" else "✗ выключено"}   •   " +
                "Окно поверх: ${if (overlayAllowed) "✓ разрешено" else "✗ не разрешено"}",
                style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onOpenAccessibility, modifier = Modifier.weight(1f)) { Text("Accessibility") }
                Button(onClick = onOpenOverlay, modifier = Modifier.weight(1f)) { Text("Окно поверх") }
            }
            OutlinedTextField(
                s.selectedPackage,
                { vm.edit(s.copy(selectedPackage = it)) },
                label = { Text("Пакет приложения (например, com.example.app)") },
                modifier = Modifier.fillMaxWidth(), singleLine = true
            )
            OutlinedButton(onClick = { vm.loadInstalledApps(); showPicker = true },
                modifier = Modifier.fillMaxWidth()) { Text("Выбрать из установленных приложений") }
            Text("Для игр с графическими субтитрами потребуется отдельный OCR-модуль. " +
                "Без указанного пакета автоматическое чтение отключено.",
                style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(
                secret, { secret = it }, modifier = Modifier.fillMaxWidth(),
                label = { Text(if (apiKeySaved) "DeepL API key (уже сохранён)" else "DeepL API key") },
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
            Text("Скорость речи: ${"%.2f".format(s.speechSpeed)}×")
            Slider(s.speechSpeed, { vm.edit(s.copy(speechSpeed = it)) }, valueRange = .5f..1.7f)
            Text("Задержка обработки: ${s.delayMs} мс")
            Slider(s.delayMs.toFloat(), { vm.edit(s.copy(delayMs = it.toLong())) }, valueRange = 200f..2500f)
            Text("Прозрачность: ${(s.overlayAlpha * 100).toInt()}%")
            Slider(s.overlayAlpha, { vm.edit(s.copy(overlayAlpha = it)) }, valueRange = .6f..1f)
            Text("Масштаб окна: ${"%.2f".format(s.sizeScale)}×")
            Slider(s.sizeScale, { vm.edit(s.copy(sizeScale = it)) }, valueRange = .7f..1.2f)
            Row { Switch(s.darkTheme, { vm.edit(s.copy(darkTheme = it)) });
                Text("Тёмная тема", Modifier.padding(12.dp)) }
            Row { Switch(s.keepHistory, { vm.edit(s.copy(keepHistory = it)) });
                Text("Сохранять историю локально", Modifier.padding(12.dp)) }
            Button(onClick = { vm.save(secret); secret = ""; apiKeySaved = vm.hasApiKey(); savedMessage = "Настройки сохранены" },
                modifier = Modifier.fillMaxWidth()) { Text("Сохранить настройки") }
            if (savedMessage.isNotEmpty()) Text(savedMessage)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    when {
                        !apiKeySaved && secret.isBlank() ->
                            savedMessage = "Сначала укажите API-ключ DeepL и проверьте перевод кнопкой «Тест»"
                        s.selectedPackage.trim().isBlank() ->
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
                Text("Тест: перевести Hello world (без Accessibility)")
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
