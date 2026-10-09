import io
from pathlib import Path
import subprocess
import pytest
from PIL import Image
from pc_core.adb_bridge import ADBBridge, ADBError
from pc_core.png_capture import PNGError, validate_png


def png():
    buffer=io.BytesIO()
    Image.new('RGB',(17,29),(4,97,201)).save(buffer,'PNG')
    return buffer.getvalue()


def result(data=b'', code=0):
    return subprocess.CompletedProcess([],code,stdout=data,stderr=b'failed' if code else b'')


@pytest.mark.parametrize('bad',[b'',b'not png',png()[:24],png()[:-12],png()[:-1]])
def test_truncated_capture_retried_without_changing_good_binary(bad):
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd)
        assert not kwargs.get('text') and not kwargs.get('shell')
        return result(bad if len(calls)==1 else png())
    assert ADBBridge('PHONE',runner=run).screenshot_png()==png()
    assert len(calls)==2 and all(cmd[3:]==['exec-out','screencap','-p'] for cmd in calls)


def test_crc_damage_rejected_before_perception():
    data=bytearray(png());data[45]^=1
    with pytest.raises(PNGError):validate_png(bytes(data))


def test_pull_fallback_and_cleanup_of_only_own_temporary_file():
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd)
        if cmd[3]=='exec-out':return result(png()[:-12])
        if cmd[3]=='pull':Path(cmd[-1]).write_bytes(png())
        return result()
    assert ADBBridge('PHONE',runner=run).screenshot_png()==png()
    assert [cmd[3] for cmd in calls]==['exec-out','exec-out','shell','pull','shell']
    capture=calls[2][-1]
    assert capture.startswith('/data/local/tmp/uga_capture_')
    assert calls[-1][3:]==['shell','rm',capture]
    assert not Path(calls[3][-1]).exists()


def test_all_transfers_incomplete_are_failure_not_a_frame():
    def run(cmd,**kwargs):
        if cmd[3]=='pull':Path(cmd[-1]).write_bytes(png()[:-12])
        return result(png()[:-12])
    with pytest.raises(ADBError,match='полный PNG'):
        ADBBridge('PHONE',runner=run).screenshot_png()


def test_missing_pull_file_is_capture_failure():
    with pytest.raises(ADBError,match='полный PNG'):
        ADBBridge('PHONE',runner=lambda cmd,**kwargs:result(png()[:20])).screenshot_png()


def test_valid_png_reaches_real_opencv_perception():
    from game_agent.perception import Perception
    data=ADBBridge('PHONE',runner=lambda cmd,**kwargs:result(png())).screenshot_png()
    assert validate_png(data)==(17,29)
    frame=Perception.from_png(data)
    assert frame.shape==(29,17,3)
    assert tuple(frame[0,0])==(201,97,4)


def test_agent_run_propagates_capture_failure_instead_of_success():
    from game_agent.agent import GameAgent
    class Broken:
        cfg=type('Config',(),{'max_steps':20})()
        def clock(self):return 0
        def step(self):raise ADBError('capture failed')
    with pytest.raises(ADBError):GameAgent.run(Broken())
