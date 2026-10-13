"""Round-trip the compiled installer against a disposable legitimate game copy."""
import argparse,json,shutil,subprocess,time
from pathlib import Path
from patcher import Bundle,sha,safe_path

def verify(original,exe,output):
    assert not output.exists();output.mkdir(parents=True)
    game=output/'게임 원본 복사본';game.mkdir();bundle=Bundle();entries=bundle.manifest['files']
    source_hashes={}
    for entry in entries:
        if entry['source_sha256'] is None:continue
        path=safe_path(original,entry['path']);value=path.read_bytes()
        assert sha(value)==entry['source_sha256'],entry['path']
        source_hashes[entry['path']]=sha(value)
        target=safe_path(game,entry['path']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
    runs=[]
    def run(action):
        start=time.monotonic()
        result=subprocess.run([str(exe.resolve()),'--game',str(game.resolve()),'--'+action],capture_output=True,timeout=180)
        assert result.returncode==0,(action,result.returncode,result.stdout,result.stderr)
        runs.append(dict(action=action,exit_code=result.returncode,seconds=round(time.monotonic()-start,2)))
    run('check');run('apply')
    for entry in entries:assert sha(safe_path(game,entry['path']).read_bytes())==entry['target_sha256'],entry['path']
    run('check');run('apply')
    for entry in entries:assert sha(safe_path(game,entry['path']).read_bytes())==entry['target_sha256']
    run('restore')
    for entry in entries:
        path=safe_path(game,entry['path'])
        if entry['source_sha256'] is None:assert not path.exists(),entry['path']
        else:assert sha(path.read_bytes())==entry['source_sha256'],entry['path']
    run('check')
    for name,digest in source_hashes.items():assert sha(safe_path(original,name).read_bytes())==digest
    report=dict(version=bundle.manifest['version'],bundle_id=bundle.manifest['bundle_id'],
        patcher_exe_sha256=sha(exe.read_bytes()),payload_sha256=sha(bundle.path.read_bytes()),
        file_targets_verified=len(entries),original_files_restored=len(source_hashes),
        created_files_removed=len(entries)-len(source_hashes),
        compiled_installer=True,unicode_space_game_path=True,install_exact=True,reinstall_idempotent=True,
        restore_byte_exact=True,source_installation_unchanged=True,runs=runs,
        full_game_runtime_verified=False)
    (output/'release_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original-game',type=Path,required=True)
    p.add_argument('--exe',type=Path,default=Path('dist/BattlespireKoreanPatcher.exe'))
    p.add_argument('--output',type=Path,default=Path('local-test/release-01'))
    a=p.parse_args();verify(a.original_game,a.exe,a.output)
