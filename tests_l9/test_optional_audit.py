from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pytest
from bootstrap.manifest import DependencyManifest
from bootstrap.model_registry import PCModelRegistry
from bootstrap.orchestrator import BootstrapOrchestrator
from bootstrap.permissions import BatchPermissionGate, PermissionDenied

ROOT=Path(__file__).resolve().parent.parent

def test_optional_audit_covers_original_unverified_components_and_pins():
    manifest=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml')
    base=json.loads((ROOT/'bootstrap/verification_windows.json').read_text())
    audit=json.loads((ROOT/'bootstrap/verification_optional_windows.json').read_text())
    normalize=lambda name:name.lower().replace('_','-')
    optional={normalize(r['id']) for r in audit['components']}
    assert len(optional)==44
    assert optional.isdisjoint({normalize(r['id']) for r in base['artifacts']})
    assert optional|{normalize(r['id']) for r in base['artifacts']}=={normalize(i) for i in manifest.by_id}
    for row in audit['components']:
        spec=manifest.by_id[row['id']]
        assert spec.audit_status==row['status']
        if row.get('sha256'):
            assert (spec.url,spec.sha256)==(row['url'],row['sha256'])
        if row.get('files'):
            assert spec.bundle_files and all(f['download_verified'] for f in row['files'])
    qwen=manifest.by_id['qwen2-vl-7b-awq']
    assert len([f for f in qwen.bundle_files if f['path'].endswith('.safetensors')])==2

def test_bundle_requires_every_companion_and_valid_hash(tmp_path):
    spec=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml').by_id['smolvlm-256m']
    digest=lambda b:hashlib.sha256(b).hexdigest()
    spec=replace(spec,target='models/sample/model.safetensors',sha256=digest(b'weight'),bundle_files=[
        {'path':'model.safetensors','sha256':digest(b'weight'),'url':spec.url},
        {'path':'config.json','sha256':digest(b'config'),'url':spec.url}])
    p=tmp_path/spec.target;p.parent.mkdir(parents=True);p.write_bytes(b'weight')
    registry=PCModelRegistry(tmp_path)
    assert registry.status(spec)=='missing_bundle_file'
    p.with_name('config.json').write_bytes(b'wrong')
    assert registry.status(spec)=='hash_mismatch'
    p.with_name('config.json').write_bytes(b'config')
    assert registry.status(spec)=='verified'

def test_model_bundle_single_file_install_refused_before_network(tmp_path):
    spec=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml').by_id['smolvlm-256m']
    orchestrator=BootstrapOrchestrator(ROOT)
    with pytest.raises(PermissionDenied,match='всех'):
        orchestrator._install_verified(spec,offline_dir=tmp_path)

@pytest.mark.parametrize('component',['autoawq','pybullet','temporal-lstm','dreamerv3'])
def test_blocked_component_not_offered_for_automatic_install(component):
    orchestrator=BootstrapOrchestrator(ROOT,gate=BatchPermissionGate(ask=lambda _:pytest.fail('Blocked before approval'),output=lambda _:None))
    assert not orchestrator.manifest.by_id[component].downloadable
    with pytest.raises(PermissionDenied):orchestrator.apply([component])
