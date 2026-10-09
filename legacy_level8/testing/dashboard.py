"""Опциональная Streamlit-панель QA. Импорт Streamlit только при запуске.

Кнопки теста и отката НЕ выполняют ввод в Android и НЕ обходят PermissionGate.
"""
from __future__ import annotations
from pathlib import Path
import json

def main(report_dir='test_reports'):
    try:import streamlit as st
    except ImportError as ex:raise RuntimeError('Streamlit отсутствует: установка только с Y/N оператора') from ex
    st.title('Level 8 · Staged Rollout / Safety QA')
    st.info('Online Stealth отключён. Тестовые ворота не гарантируют отсутствие блокировки аккаунта.')
    folder=Path(report_dir)
    reports=sorted(folder.glob('*.json')) if folder.exists() else []
    if not reports:
        st.warning('Пока нет отчётов. Сначала запустите офлайн-проверку.')
        return
    chosen=st.selectbox('Отчёт тестирования',[p.name for p in reports])
    data=json.loads((folder/chosen).read_text(encoding='utf-8'))
    st.metric('Результат',data.get('verdict','unknown'))
    st.table(data.get('stages',[]))
    st.caption('Rollback проводится локально с подтверждением владельца, не кнопкой удалённого выполнения.')

if __name__=='__main__':main()
