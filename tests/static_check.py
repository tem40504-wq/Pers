"""Run with python tests/static_check.py from the project root. Static checks only."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

R = Path(__file__).resolve().parents[1]
S = R / 'app/src/main/java/dev/gamescreen/voice'
def src(name):
    return (S / name).read_text(encoding='utf-8')

def check(name, assertion):
    assert assertion, name
    print('PASS', name)

manifest = ET.parse(R / 'app/src/main/AndroidManifest.xml').getroot()
android = '{http://schemas.android.com/apk/res/android}'
perms = {el.get(android+'name') for el in manifest.findall('uses-permission')}
check('Internet/overlay/foreground permissions',
      {'android.permission.INTERNET','android.permission.SYSTEM_ALERT_WINDOW',
       'android.permission.FOREGROUND_SERVICE','android.permission.FOREGROUND_SERVICE_SPECIAL_USE'} <= perms)
check('TTS engine query declared', any(el.get(android+'name') == 'android.intent.action.TTS_SERVICE' for el in manifest.findall('queries/intent/action')))
check('Audio capture permissions declared',
      'android.permission.RECORD_AUDIO' in perms and
      'android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION' in perms)
services = manifest.find('application').findall('service')
check('Overlay FGS special use declaration', any('specialUse' in (s.get(android+'foregroundServiceType') or '') and 'mediaProjection' in (s.get(android+'foregroundServiceType') or '') for s in services))
check('Accessibility protected by BIND_ACCESSIBILITY_SERVICE', any(s.get(android+'permission') == 'android.permission.BIND_ACCESSIBILITY_SERVICE' for s in services))

service = src('capture/GameAccessibilityService.kt')
check('Accessibility selected-package checks', 'root.packageName?.toString() != allowed' in service and 'event.packageName?.toString() != allowed' in service)
check('Accessibility skips editable and password', 'node.isPassword' in service and 'node.isEditable' in service)
check('Accessibility debounce with max wait', 'delay(DEBOUNCE_MS)' in service and 'MAX_WAIT_MS' in service and 'pending?.cancel()' in service)
check('Accessibility system-level package filter', 'info.packageNames' in service and 'registerListener(packageListener)' in service)
check('Accessibility nodes recycled', 'node.recycle()' in service)
check('Test without overlay can call translator', 'fun testTranslation()' in src('domain/TranslationPipeline.kt') and 'preview = scope.launch' in src('domain/TranslationPipeline.kt'))
check('VM uses new translation test', 'app.pipeline.testTranslation()' in src('ui/MainViewModel.kt'))
check('Demo saves typed key', bool(re.search(r'vm\.save\(secret\).*?vm\.sendDemo\(\)', src('ui/MainActivity.kt'), re.S)))
check('Main button saves settings on start', 'onStart()' in src('ui/MainActivity.kt') and 'vm.save(secret)' in src('ui/MainActivity.kt'))
check('Temporary LRU and cache clear', 'removeEldestEntry' in src('domain/TranslationPipeline.kt') and 'clearMemoryCache()' in src('ui/MainViewModel.kt'))
check('DeepL returns readable errors', all(k in src('data/DeepLTranslationRepository.kt') for k in ['401, 403', '429', '456']))
check('Foreground-service API 29-33 compatibility', 'Build.VERSION.SDK_INT >= 34' in src('platform/OverlayService.kt') and 'startForeground(33, createNotification())' in src('platform/OverlayService.kt'))
check('Overlay drag constrained', 'coerceIn(0, maxX)' in src('platform/OverlayService.kt') and 'coerceIn(0, maxY)' in src('platform/OverlayService.kt'))
check('TTS language checked', 'TextToSpeech.LANG_MISSING_DATA' in src('platform/TTSManager.kt'))
check('Android SDK bounds', all(k in (R/'app/build.gradle.kts').read_text() for k in ['minSdk = 29','targetSdk = 35','versionName = "0.2.3"']))
gradle = (R/'app/build.gradle.kts').read_text()
check('No kotlinOptions DSL (compile error since Kotlin 2.2)', not re.search(r'^\s*kotlinOptions\s*\{', gradle, re.M) and 'compilerOptions' in gradle)
overlay = src('platform/OverlayService.kt')
check('startForeground before any stopSelf after canDrawOverlays',
      overlay.index('startForeground(33, createNotification()') < overlay.index('if (!Settings.canDrawOverlays(this))'))
check('Overlay applies options live and on rotation', 'applyOptions()' in overlay and 'onConfigurationChanged' in overlay)
pipe = src('domain/TranslationPipeline.kt')
check('Pipeline: no starvation, retry after error', 'Channel.CONFLATED' in pipe and 'MAX_EXTRA_WAIT_MS' in pipe and 'RETRY_AFTER_ERROR_MS' in pipe)
check('Demo bypasses cache', 'if (demo) null' in pipe)
deepl = src('data/DeepLTranslationRepository.kt')
check('DeepL Free/Pro auto by key suffix', 'endsWith(":fx")' in deepl and 'deepLPro' not in deepl)
check('DeepL source auto-detect / variant stripped', "substringBefore('-')" in deepl)
ui = src('ui/MainActivity.kt')
check('Compose: Surface background and insets', 'Surface(' in ui and 'safeDrawingPadding()' in ui and 'enableEdgeToEdge()' in ui)
check('App picker + launcher queries', 'AppPickerDialog' in ui and any(el.get(android+'name') == 'android.intent.category.LAUNCHER' for el in manifest.findall('queries/intent/category')))
check('Accessibility status shown', 'GameAccessibilityService.isEnabled' in ui)
ps = (R/'BUILD_WINDOWS.ps1').read_text()
check('Build script writes local.properties', 'local.properties' in ps and 'sdk.dir' in ps)
check('Offline ML Kit provider without key', 'TranslateLanguage' in src('data/MlKitTranslationRepository.kt') and 'RoutingTranslationRepository' in src('GameVoiceApp.kt') and 'com.google.mlkit:translate' in gradle)
check('Fixed debug signing key', 'debug.keystore' in gradle and (R/'app/debug.keystore').exists())
check('Audio mode: capture + Vosk + own TTS excluded', 'AudioPlaybackCaptureConfiguration' in (S/'audio/SpeechCaptureEngine.kt').read_text() and 'excludeUid' in (S/'audio/SpeechCaptureEngine.kt').read_text() and 'USAGE_ASSISTANT' in src('platform/TTSManager.kt'))
check('Auto speak + foreign-only filter', 'results.collect' in src('platform/OverlayService.kt') and 'keepForeign' in src('GameVoiceApp.kt'))
check('0.2.2 merge: OCR, pacer, collapse, pause', 'takeScreenshot' in service and 'canTakeScreenshot' in (R/'app/src/main/res/xml/accessibility_service_config.xml').read_text() and 'SpeechPacer' in src('platform/TTSManager.kt') and 'setCompact' in src('platform/OverlayService.kt') and 'pausedSpeech' in src('platform/OverlayService.kt'))
check('ARM64 only, same package and signing', 'listOf("arm64-v8a")' in gradle and 'applicationId = "dev.gamescreen.voice"' in gradle)
ET.parse(R/'app/src/main/res/xml/accessibility_service_config.xml')
print('Static checks completed; actual APK build NOT verified.')
