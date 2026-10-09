# Universal Game Agent Level 8+ — Safety & Staged Rollout

**Это QA-надстройка и конвейер проверки, а не средство обхода античита.**

- Не удаляет код мобильного Level 7 и настольного legacy Level 6.
- `stealth/` содержит OFFLINE тестовую вариативность жестов и условия остановки, **а не способ спрятать бота**.
- `testing/` содержит семь обязательных ворот, реплеи, Shadow, A/B и откат.
- `online=True` — только наблюдение, без касаний.
- `offline_qa=False` по умолчанию. Его активация требует отдельного SecurityCore Y/N.
- Не скачивает модели/пакеты, не включает сетевые сервисы без разрешения пользователя.

## Проверка на ПК (без телефона)

```powershell
py -m pytest -q tests/test_level8.py tests/test_mobile.py
py main_l8.py --qa-demo
```

Демонстрация `--qa-demo` преднамеренно завершится `BLOCK`: этапы Sandbox, Shadow, A/B и Production не проводились. Для реального тестирования в офлайн-игре следуй [docs/INSTALL_L8_RU.md](docs/INSTALL_L8_RU.md).

## Файловая структура

Новые каталоги: `stealth/`, `testing/`, `docs/ARCHITECTURE_L8_RU.md`, `docs/INSTALL_L8_RU.md`, `docs/TEST_REPORT_EXAMPLE.md`, `main_l8.py`, `START_L8_SAFE.cmd`.

**Единственная правка исходного Level 7:** в `mobile_core/agent.py` добавлены необязательные методы `postprocess_decision()` и `on_cycle_complete()`. Старый `MobileAgent` ведёт себя как прежде; `Stage8Agent` наследуется от него.

Важно: APK Android Companion не пересобран и на телефоне не проверен. Последующие тесты Stage 4–7 требуют настоящих длительных испытаний и проверки ToS. Покрытие Python не доказывает отсутствие игровых рисков.

## Мобильный тестовый запуск

`python main_mobile_l8.py --steps 5` — наблюдение; `python main_mobile_l8.py --offline-qa --steps 30` — офлайн QA после Y/N; только отдельно одобренный `--execute --safe-box ...` допускает реальные жесты. В онлайн-играх режим остаётся только наблюдательным.
