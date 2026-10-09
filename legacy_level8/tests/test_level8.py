"""pytest: строгие проверки поведения для безопасной QA-модели."""
import json
from datetime import datetime,timezone
import pytest
from mobile_core.contracts import Decision,Observation
from mobile_core.security import EmergencyStop
from stealth.human import HumanMimicry
from stealth.safe import SafeMode
from stealth.session import SessionSimulator
from stealth.detection import AntiCheatDetector
from stealth.surveillance import CounterSurveillance
from testing.versioning import VersionManager
from testing.replay import ReplayBuffer
from testing.shadow import ShadowMode
from testing.ab import ABTester
from testing.regression import RegressionTracker,AutoRollback
from testing.policy import RolloutPolicy
from testing.orchestrator import TestOrchestrator as Orchestrator,StageEvidence


def valid_tap():
    return Decision('tap','Тестовый элемент',skill_id='test',x=50,y=50,confidence=.99)

def test_delay_range_and_variation():
    mimic=HumanMimicry(seed=42)
    samples=[mimic.delay() for _ in range(1000)]
    assert min(samples)>=.0349
    assert max(samples)<=.665
    assert len(set(round(v,3) for v in samples))>150
    assert .30 < sum(samples)/len(samples) < .40


def test_offline_miss_double_rates():
    mimic=HumanMimicry(seed=123)
    samples=[mimic.preview_tap((0,0,100,100),offline_test=True) for _ in range(10000)]
    misses=sum(v.missed_center for v in samples)/len(samples)
    doubles=sum(v.double_tap for v in samples)/len(samples)
    assert .025 <= misses <= .055
    assert .012 <= doubles <= .028
    assert all(0<=p.x<100 and 0<=p.y<100 for p in samples)


def test_no_injected_double_tap_in_default():
    mimic=HumanMimicry(seed=7)
    previews=[mimic.preview_tap((10,20,60,80)) for _ in range(300)]
    assert all(not x.double_tap and not x.missed_center for x in previews)
    assert all((x.x,x.y)==(35,50) for x in previews)


def test_bezier_endpoints_and_timing():
    g=HumanMimicry(seed=4).swipe_preview((0,10),(250,10),points=24)
    assert g[0][:2]==(0,10)
    assert g[-1][:2]==(250,10)
    assert 200 <= g[-1][2] <= 800
    assert all(b[2]>a[2] for a,b in zip(g,g[1:]))


def test_safe_mode_online_observation_only():
    safe=SafeMode(online=True)
    assert safe.filter(valid_tap(),approved=True,scene='pve').kind=='wait'


def test_safe_mode_offline_needs_approval_and_rate_limit():
    safe=SafeMode(online=False,max_actions_per_sec=3)
    d=valid_tap()
    assert safe.filter(d,approved=False,now=0).kind=='wait'
    assert safe.filter(d,approved=True,now=1).kind=='tap'
    assert safe.filter(d,approved=True,now=1.1).kind=='wait'
    assert safe.filter(d,approved=True,now=1.4).kind=='tap'


def test_safe_mode_pvp_rejected():
    safe=SafeMode(online=False)
    assert safe.filter(valid_tap(),approved=True,now=1,scene='pvp').kind=='wait'


def test_captcha_forces_warning():
    signal=AntiCheatDetector().inspect(['Verify you are human'],scene='quest')
    assert signal.critical and signal.kind=='captcha'


def test_environment_online_not_approved():
    env=CounterSurveillance().evaluate(online=True,rooted=None)
    assert not env.permitted


def test_version_snapshot_and_rollback(tmp_path):
    v=VersionManager(tmp_path)
    v.snapshot('v0.8.3-prod',{'config.json':b'{}','profiles/human.json':b'[]'})
    v.snapshot('v0.8.4-replay',{'config.json':b'{"new":true}'})
    assert v.verify('v0.8.3-prod')
    with pytest.raises(PermissionError):v.activate('v0.8.4-replay')
    v.activate('v0.8.4-replay',operator_approved=True)
    assert v.active()=='v0.8.4-replay'
    assert v.rollback('v0.8.3-prod')=='v0.8.3-prod'
    assert v.active()=='v0.8.3-prod'


def test_version_tamper_detected(tmp_path):
    v=VersionManager(tmp_path)
    v.snapshot('v0.8.3-prod',{'a.txt':b'1'})
    (tmp_path/'v0.8.3-prod'/'a.txt').write_text('2')
    assert not v.verify('v0.8.3-prod')


def test_replay_interval_and_rotation(tmp_path):
    replay=ReplayBuffer(tmp_path,max_bytes=9,interval=.5)
    for i in range(4):
        replay.append(state={'hp':.4},action={'kind':'wait'},outcome='unknown',
                      frame_jpeg=b'\xff\xd8payload',ts=i)
    assert len(replay.events())==0 or sum(row['frame']!='' for row in replay.events())<=1
    replay.close()


def test_replay_blackbox(tmp_path):
    rep=ReplayBuffer(tmp_path/'store',max_bytes=10000)
    row=rep.append(state={},action={'kind':'wait'},outcome='no_change',
                   frame_jpeg=b'\xff\xd8some',ts=1)
    out=rep.freeze_blackbox(tmp_path/'incident')
    assert (out/'blackbox.json').exists()
    assert (out/row['frame']).exists()
    rep.close()


def test_shadow_only_comparison():
    s=ShadowMode(min_samples=2,min_hours=0,threshold=.8)
    s.record('heal','heal','battle',ts=1)
    s.record('tap','tap','battle',ts=2)
    report=s.report()
    assert report.agreement==1 and report.eligible


def test_ab_requires_sufficient_sessions():
    r=ABTester().compare([{'score':10}]*4,[{'score':12}]*4)
    assert not r.eligible and r.p_value is None


def test_ab_significant_and_safe():
    a=[{'score':1.0} for _ in range(30)]
    b=[{'score':10.0} for _ in range(30)]
    assert ABTester(permutations=500).compare(a,b).eligible
    b[0]['security_errors']=1
    assert not ABTester().compare(a,b).eligible


def test_regression_threshold():
    hits=RegressionTracker().check({'win_rate':.8,'security_errors':0},
                                   {'win_rate':.68,'security_errors':1})
    assert {r.metric for r in hits}=={'win_rate','security_errors'}


def test_rollback_panic_first(tmp_path):
    versions=VersionManager(tmp_path/'versions')
    versions.snapshot('v0.8.3-prod',{'x.txt':b'stable'})
    emergency=EmergencyStop();emergency.arm(True)
    rollback=AutoRollback(versions,'v0.8.3-prod',tmp_path/'regressions.jsonl',emergency=emergency)
    rollback.trigger('captcha')
    assert emergency.stopped and versions.active()=='v0.8.3-prod'


def test_critical_gate_missing_fails(tmp_path):
    org=Orchestrator(report_dir=tmp_path)
    receipts={'unit':StageEvidence(True,{'coverage':.90}),
              'integration':StageEvidence(True)}
    r=org.run('HumanMimicry','v0.8.3-unit',receipts)
    assert r['verdict']=='BLOCK' and r['stages'][-1]['stage']=='replay'


def test_critical_coverage_fails(tmp_path):
    org=Orchestrator(report_dir=tmp_path)
    r=org.run('HumanMimicry','v0.8.3-unit',{'unit':StageEvidence(True,{'coverage':.79})})
    assert r['verdict']=='BLOCK'


def test_all_seven_gate_approval_for_offline(tmp_path):
    rec={
       'unit':StageEvidence(True,{'coverage':.93}),
       'integration':StageEvidence(True),
       'replay':StageEvidence(True),
       'sandbox':StageEvidence(True,{'minutes':20,'offline':True}),
       'shadow':StageEvidence(True,{'minutes':62,'agreement':.82}),
       'ab':StageEvidence(True,{'sessions_each':40,'statistically_better':True}),
       'production':StageEvidence(True,{'offline_or_authorized_environment':True})}
    org=Orchestrator(report_dir=tmp_path)
    assert org.run('HumanMimicry','v0.8.3-prod',rec,operator_approved=True)['verdict']=='PASS'
    assert org.run('HumanMimicry','v0.8.4-prod',rec,operator_approved=False)['verdict']=='BLOCK'


def test_policy_cannot_skip_critical():
    with pytest.raises(PermissionError):
        RolloutPolicy().authorize_skip('SafeMode','shadow',operator_approved=True)


def test_session_night_quiet_hours():
    simulator=SessionSimulator(seed=1)
    local=datetime(2026,10,10,3,tzinfo=timezone.utc)
    state=simulator.check(monotonic_now=10,local_dt=local)
    assert not state.allowed and state.reason=='quiet_hours'


def test_session_time_limit_and_break():
    simulator=SessionSimulator(seed=1,session_minutes=(1,1),break_minutes=(1,1))
    local=datetime(2026,10,10,12,tzinfo=timezone.utc)
    assert simulator.check(monotonic_now=1,local_dt=local).allowed
    st=simulator.check(monotonic_now=70,local_dt=local)
    assert not st.allowed and st.reason=='session_limit'
    assert simulator.check(monotonic_now=71,local_dt=local).reason=='rest_break'
    assert simulator.check(monotonic_now=131,local_dt=local).allowed


def _make_l8_agent(tmp_path=None, online=True, offline_qa=False, shadow=None):
    from stealth.integration import Stage8Agent
    from mobile_core.security import SecurityCore
    emergency=EmergencyStop();emergency.arm(True)
    security=SecurityCore(emergency)
    if offline_qa:security.approvals['level8_offline_qa']=True  # явно смоделированное согласие оператора
    replay=ReplayBuffer(tmp_path/'rec',max_bytes=2000) if tmp_path else None
    ag=Stage8Agent(controller=None,perception=None,tactician=None,security=security,memory=None,
                   online=online,offline_qa=offline_qa,shadow=shadow,replay=replay)
    return ag


def test_stage8_layer_does_not_modify_online_action(tmp_path):
    ag=_make_l8_agent(tmp_path,online=True)
    obs=Observation(scene='combat')
    filtered=ag.postprocess_decision(obs,valid_tap())
    assert filtered.kind=='wait'
    assert not ag.security.emergency.stopped
    ag.replay.close()


def test_stage8_captcha_panic_and_blackbox(tmp_path):
    ag=_make_l8_agent(tmp_path,online=False)
    obs=Observation(scene='combat',texts=['Verify you are human'])
    assert ag.postprocess_decision(obs,valid_tap()).kind=='wait'
    assert ag.security.emergency.stopped
    ag.on_cycle_complete(obs,valid_tap(),'blocked',b'\xff\xd8screen')
    incidents=list((ag.replay.root/'incidents').glob('*'))
    assert incidents and (incidents[0]/'blackbox.json').exists()
    ag.replay.close()


def test_stage8_shadow_does_not_execute(tmp_path):
    shadow=ShadowMode(min_samples=1,min_hours=0)
    ag=_make_l8_agent(tmp_path,online=False,offline_qa=False,shadow=shadow)
    assert ag.postprocess_decision(Observation(scene='combat'),valid_tap()).kind=='wait'
    assert len(shadow.records)==1
    ag.replay.close()


def test_stage8_offline_qa_allows_only_known_base_decisions():
    ag=_make_l8_agent(online=False,offline_qa=True)
    from types import SimpleNamespace
    ag.session=SimpleNamespace(check=lambda:SimpleNamespace(allowed=True))
    result=ag.postprocess_decision(Observation(scene='pve'),valid_tap())
    assert result.kind=='tap'  # Дополнительно SecurityCore.validate всё ещё обязателен.


def test_coverage_report_missing(tmp_path):
    from testing.coverage_report import summarize
    report=summarize(tmp_path/'missing.json')
    assert report['status']=='MISSING'


def test_coverage_report_pass_and_fail(tmp_path):
    from testing.coverage_report import summarize
    path=tmp_path/'coverage.json'
    path.write_text(json.dumps({'files':{'stealth/human.py':{'summary':{'covered_lines':9,'num_statements':10},'missing_lines':[13]}}}))
    assert summarize(path)['status']=='PASS'
    path.write_text(json.dumps({'files':{'stealth/human.py':{'summary':{'covered_lines':7,'num_statements':10},'missing_lines':[13,14,15]}}}))
    assert summarize(path)['status']=='FAIL'


def test_stage8_requires_explicit_permission_for_qa():
    from stealth.integration import Stage8Agent
    from mobile_core.security import SecurityCore,PermissionRequired
    security=SecurityCore(EmergencyStop())
    with pytest.raises(PermissionRequired):
        Stage8Agent(controller=None,perception=None,tactician=None,security=security,
                    memory=None,offline_qa=True,online=False)


def test_stage8_asks_permission_and_rejects_n():
    ag=_make_l8_agent(online=False)
    assert ag.enable_offline_qa(callback=lambda _: 'N') is False
    assert not ag.offline_qa


def test_replay_blackbox_keeps_rotated_frames(tmp_path):
    rep=ReplayBuffer(tmp_path/'store',max_bytes=1)
    row=rep.append(state={},action={'kind':'wait'},outcome='x',frame_jpeg=b'\xff\xd8payload',ts=2)
    assert not (rep.frames/row['frame']).exists()
    out=rep.freeze_blackbox(tmp_path/'inc')
    assert (out/row['frame']).exists()
    rep.close()


def test_skipped_gate_lab_only(tmp_path):
    org=Orchestrator(report_dir=tmp_path)
    r=org.run('Logging','v0.8.3-unit',{'integration':StageEvidence(True)},
              skipped_stages={'unit'},operator_approved=True)
    assert r['verdict']=='LAB_ONLY'


def test_risk_journal_time_is_not_probability():
    from stealth.warnings import RiskJournal
    journal=RiskJournal()
    assert journal.record('session',44)['risk_level']=='baseline'
    assert journal.record('session',50)['risk_level']=='caution'
    assert journal.record('session',100)['risk_level']=='elevated'
    assert 'ban_probability' not in journal.entries[-1]


def test_microgestures_only_exist_in_offline_preview():
    mimic=HumanMimicry(seed=6)
    assert mimic.microgesture_preview((100,100))==[]
    g=mimic.microgesture_preview((100,100),offline_test=True)
    assert len(g) in (2,3)
    assert all(1<=abs(b[0]-a[0])<=2 and 1<=abs(b[1]-a[1])<=2 for a,b in g)
