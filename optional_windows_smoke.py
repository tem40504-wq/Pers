"""Exercise optional native wheels on real Windows, without phone/GPU access."""
import asyncio
import io
import json
import numpy as np
import scipy.linalg
import yaml
import networkx as nx
import pytest_asyncio
import pytesseract
import av
import faiss
from PIL import Image

matrix = np.array([[3., 1.], [1., 2.]])
assert np.allclose(matrix @ scipy.linalg.solve(matrix, [9., 8.]), [9., 8.])
assert yaml.safe_load('steps: [observe, act]')['steps'] == ['observe', 'act']
assert nx.shortest_path(nx.path_graph(4), 0, 3) == [0, 1, 2, 3]
assert asyncio.run(asyncio.sleep(0, result='ready')) == 'ready'
assert pytest_asyncio.__version__
assert len(pytesseract.pytesseract.prepare(Image.new('RGB', (3, 3)))) == 2
audio = av.AudioFrame.from_ndarray(np.zeros((1, 160), dtype=np.int16), format='s16', layout='mono')
audio.sample_rate = 16000
assert audio.samples == 160
assert av.AudioResampler(format='flt', layout='mono', rate=16000).resample(audio)
buffer = io.BytesIO()
with av.open(buffer, mode='w', format='wav') as container:
    stream = container.add_stream('pcm_s16le', rate=16000)
    for packet in stream.encode(audio):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
buffer.seek(0)
with av.open(buffer) as container:
    assert sum(frame.samples for frame in container.decode(audio=0)) == 160
index = faiss.IndexFlatL2(2)
index.add(np.array([[0., 0.], [2., 2.]], dtype=np.float32))
distance, neighbor = index.search(np.array([[1.9, 2.]], dtype=np.float32), 1)
assert neighbor[0, 0] == 1 and distance[0, 0] < 0.02
print(json.dumps({'status': 'PASS', 'components': ['scipy', 'PyYAML', 'networkx', 'pytest-asyncio', 'pytesseract', 'av', 'faiss-cpu'],
                  'scope': 'CPU operations/imports; pytesseract image preprocessing, OCR engine not executed; pytest-asyncio import, plugin suite not executed'}))
