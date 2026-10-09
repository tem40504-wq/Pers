# Запускатор Windows — v9.4

Пользователь получил PASS / Exit code 0 при установке и тестах, но start_agent.bat из v9.3 выдавал обрывки строк как команды («YCMD is not recognized»). На целевом ПК BAT с UTF-8 и LF оказался ненадёжным. Ранее CI выполнял Python-испытания, но не сам BAT.

start_agent.bat теперь содержит только ASCII, без BOM, с окончаниями строк CRLF. Он вызывает Python из уже установленной локальной .venv; диагностика, добавление ADB в PATH, запуск двадцати циклов без касаний и русский текст перенесены в launch_agent.py. Код ошибки Python сохраняется в Exit code BAT; отсутствие .venv даёт код 2. При обновлении не меняются версии Python, wheel или ADB.

В CI добавлен реальный вызов cmd.exe /d /c start_agent.bat --check-launcher. Он проверяет запуск BAT, выбор локального Python, импорт базовых библиотек и возврат кода 0, без подключения телефона. Отдельные regression-тесты проверяют прекращение запуска при неуспешной диагностике, передачу ошибки агента и режим без касаний.

Обновление: закрыть окно агента, заменить содержимым папки UniversalGameAgent_v9_PC_Brain из нового ZIP исходники в существующей папке, где находится start_agent.bat. Существующие .venv, tools, downloads и память агента не удаляются. Затем снова открыть start_agent.bat. Ожидается «Наблюдение завершено: 20 успешных циклов» и Exit code 0. Проверку Samsung после обновления выполняет владелец.

Локальные тесты: 100 PASS; Linux / Python 3.12 / OpenCV headless 4.12. Windows Server 2022 / Python 3.13.14: 100 PASS, отдельный вызов BAT через cmd.exe — PASS / Exit code 0.

CI: https://github.com/tem40504-wq/Pers/actions/runs/37988248606 . Отчёт: WINDOWS_LAUNCHER_REPORT.json.
