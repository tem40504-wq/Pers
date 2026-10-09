"""Streamlit мониторинг. ПК никогда не отправляет координаты/жесты."""
from __future__ import annotations
import os,urllib.request,json,hashlib

def main():
    import streamlit as st
    st.set_page_config(page_title='Game Agent Hub',layout='wide')
    st.title('Universal Game Agent — мониторинг')
    url=os.getenv('PHONE_MONITOR_URL','http://127.0.0.1:8765').rstrip('/')
    token=os.getenv('GAME_REMOTE_TOKEN','')
    if not token:st.error('GAME_REMOTE_TOKEN не задан');return
    def req(path,post=False):
        r=urllib.request.Request(url+path,data=b'{}' if post else None,
              headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
              method='POST' if post else 'GET')
        with urllib.request.urlopen(r,timeout=2) as res:return res.read()
    try:
        state=json.loads(req('/status'))
        st.json(state)
        left,right=st.columns(2)
        if left.button('PAUSE'):req('/pause',True);st.success('Пауза отправлена')
        if right.button('PANIC STOP',type='primary'):req('/panic',True);st.warning('STOP отправлен')
        if st.button('RESUME (требует локального разрешения на телефоне)'):
            try:req('/resume',True);st.success('Resume запрошен')
            except Exception:st.error('Отказ: на телефоне не выдано разрешение / истёк ARM')
        target=st.selectbox('Цель',('explore','quest','farm','combat'))
        if st.button('SET TARGET (требует разрешения)'):
            payload=json.dumps({'name':target}).encode()
            request=urllib.request.Request(url+'/set_target',data=payload,method='POST',headers={
                'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request,timeout=3) as res:st.json(json.loads(res.read()))
            except Exception as exc:st.error(str(exc))
        # Изображение доступно только по отдельно включённому разрешению.
        if st.checkbox('Показать текущий кадр (нужно разрешение на телефоне)'):
            try:st.image(req('/frame'))
            except Exception:st.info('Передача кадров отключена')
        with st.expander('Push Code — только передача в карантин'):
            bundle=st.file_uploader('Выберите ZIP для отдельной проверки на телефоне',type=['zip'])
            if bundle and st.button('Передать ZIP в карантин (не выполнять)'):
                raw=bundle.getvalue()
                digest=hashlib.sha256(raw).hexdigest()
                r=urllib.request.Request(url+'/stage_update',data=raw,method='POST',
                  headers={'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream','X-SHA256':digest})
                try:
                    with urllib.request.urlopen(r,timeout=6) as res:
                        st.json(json.loads(res.read()))
                except Exception as exc:st.error('Телефон не разрешил передачу: '+str(exc))
    except Exception as ex:st.error(f'Нет соединения с телефоном: {ex}')
    st.caption('Для обновления используйте R; ПК не отправляет игровые клики')

if __name__=='__main__':main()
