"""Останавливает агента при CAPTCHA, предупреждениях и дисконнектах.

Не определяет серверное наблюдение и не вмешивается в средства защиты игр.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class SafetySignal:
    detected: bool
    kind: str = ''
    reason: str = ''
    critical: bool = False

class AntiCheatDetector:
    MARKERS={
        'captcha':('captcha','verify you are human','подтвердите, что вы человек'),
        'security_warning':('unusual activity detected','suspicious activity','подозрительная активность'),
        'disconnect':('connection lost','disconnected','соединение разорвано'),
    }
    def inspect(self,texts: list[str], scene: str='')->SafetySignal:
        haystack=(' '.join(texts)+' '+scene).casefold()
        for kind,phrases in self.MARKERS.items():
            if any(s in haystack for s in phrases):
                return SafetySignal(True,kind,'Пауза и передача решения оператору',True)
        return SafetySignal(False)
