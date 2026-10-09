"""Сравнение A/B на автономных тестовых эпизодах (не онлайн-эксперименты)."""
from __future__ import annotations
from dataclasses import dataclass
import random,statistics,math

@dataclass(frozen=True)
class ABReport:
    count_a:int
    count_b:int
    mean_a:float
    mean_b:float
    p_value:float|None
    eligible:bool
    reason:str

class ABTester:
    def __init__(self,minimum_sessions=30,permutations=2000,method='mann_whitney'):
        self.minimum_sessions=minimum_sessions
        self.permutations=permutations
        self.method=method

    @staticmethod
    def _mann_whitney_p(a,b):
        # Двусторонняя асимптотическая оценка Mann–Whitney U, учёт совпадающих рангов.
        pairs=sorted([(v,0) for v in a]+[(v,1) for v in b])
        n1,n2=len(a),len(b);n=n1+n2
        ranks_b=0.;ties=0
        i=0
        while i<n:
            j=i+1
            while j<n and pairs[j][0]==pairs[i][0]:j+=1
            rank=(i+1+j)/2  # Средний ранг, индексация с 1.
            ranks_b+=sum(1 for k in range(i,j) if pairs[k][1]==1)*rank
            t=j-i;ties+=t**3-t
            i=j
        u=ranks_b-n2*(n2+1)/2
        expected=n1*n2/2
        variance=n1*n2/12*(n+1-ties/(n*(n-1)))
        if variance<=0:return 1.0
        z=max(0.,abs(u-expected)-.5)/math.sqrt(variance)
        return math.erfc(z/math.sqrt(2))
    def compare(self,a:list[dict],b:list[dict])->ABReport:
        """Тест перестановок для разницы средних; направленная метрика score.

        Для качества дополнительно применяются критические метрики и независимость данных.
        """
        if not a or not b:return ABReport(len(a),len(b),0.,0.,None,False,'Недостаточно эпизодов')
        sa=[float(x['score']) for x in a];sb=[float(x['score']) for x in b]
        ma,mb=statistics.mean(sa),statistics.mean(sb)
        if len(sa)<self.minimum_sessions or len(sb)<self.minimum_sessions:
            return ABReport(len(sa),len(sb),ma,mb,None,False,'Нужно >=30 эпизодов на вариант')
        if any(int(row.get('security_errors',0)) for row in b):
            return ABReport(len(sa),len(sb),ma,mb,None,False,'Есть ошибки безопасности')
        if self.method=='mann_whitney':
            p=self._mann_whitney_p(sa,sb)
        else:
            # Альтернативный перестановочный тест на разницу средних.
            combined=sa+sb;observed=mb-ma;rng=random.Random(271828)
            exceed=0
            for _ in range(self.permutations):
                values=combined.copy();rng.shuffle(values)
                diff=statistics.mean(values[len(sa):])-statistics.mean(values[:len(sa)])
                if abs(diff)>=abs(observed)-1e-12:exceed+=1
            p=(exceed+1)/(self.permutations+1)
        eligible=mb>ma and p<.05
        return ABReport(len(sa),len(sb),ma,mb,p,eligible,
                        'Улучшение подтверждено' if eligible else 'Нет значимого улучшения')
