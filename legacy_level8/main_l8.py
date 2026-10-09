"""Level 8: запуск только диагностики и тестового конвейера, без новых установок."""
from __future__ import annotations
import argparse,json
from testing.qa_runner import demo
from testing.policy import RolloutPolicy
from testing.orchestrator import TestOrchestrator

def main():
    p=argparse.ArgumentParser(description='Level 8: безопасный тестовый конвейер')
    p.add_argument('--qa-demo',action='store_true',help='Демонстрация блокировки, если недостаточно тестов')
    p.add_argument('--show-policy',action='store_true',help='Показать семь этапов')
    args=p.parse_args()
    if args.show_policy:print(json.dumps(RolloutPolicy().config,ensure_ascii=False,indent=2))
    if args.qa_demo:print(json.dumps(demo(),ensure_ascii=False,indent=2))
    if not (args.qa_demo or args.show_policy):p.print_help()

if __name__=='__main__':main()
