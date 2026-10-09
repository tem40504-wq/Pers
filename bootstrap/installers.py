"""Системные компоненты ставятся вручную; нет тихого запуска неподтверждённых EXE."""
import platform


class WindowsInstaller:
    name = 'windows'
    @staticmethod
    def guidance() -> tuple[str, ...]:
        return ('Python: https://www.python.org/downloads/windows/',
                'ADB: https://developer.android.com/tools/releases/platform-tools',
                'scrcpy: https://github.com/Genymobile/scrcpy/releases',
                'NVIDIA: https://www.nvidia.com/Download/index.aspx',
                'После установки вернитесь к bootstrap.bat.')


class LinuxInstaller:
    name = 'linux'
    @staticmethod
    def guidance() -> tuple[str, ...]:
        return ('Установите Python 3.11+, adb, ffmpeg из штатных репозиториев дистрибутива.',
                'Установка CUDA/драйвера зависит от версии дистрибутива и GPU.',
                'Не подключайте сторонние PPA без отдельного ручного решения.')


def installer_for_system():
    return WindowsInstaller() if platform.system() == 'Windows' else LinuxInstaller()
