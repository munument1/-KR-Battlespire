"""Verify the compiled Preview 2 migration and complete clean-original restore."""
import argparse,json,subprocess
from pathlib import Path
from patcher import Bundle,Installer,sha,safe_path

def verify(original,previous,exe,output):
    assert not output.exists();game=output/'이전 패치에서 갱신';game.mkdir(parents=True)
    bundle=Bundle();entries=bundle.manifest['files'];originals={}
    for entry in entries:
        if entry['source_sha256'] is None:continue
        value=safe_path(original,entry['path']).read_bytes();assert sha(value)==entry['source_sha256']
        target=safe_path(game,entry['path']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        originals[entry['path']]=value
    Installer(game,Bundle(previous)).apply()
    assert Installer(game,bundle).check()=='upgrade_available'
    def run(action):
        process=subprocess.run([str(exe.resolve()),'--game',str(game.resolve()),'--'+action],capture_output=True,timeout=180)
        assert process.returncode==0,(action,process.returncode)
    run('apply')
    for entry in entries:assert sha(safe_path(game,entry['path']).read_bytes())==entry['target_sha256'],entry['path']
    config=(game/'DOSBox-0.73/bs.conf').read_bytes()
    assert b'output=surface' in config and b'core=dynamic' in config and b'cycles=max' in config
    assert (game/'_Battlespire_Korean_Backup/0.1.0-preview2/original/GAME.EXE').read_bytes()==originals['GAME.EXE']
    run('restore')
    for entry in entries:
        path=safe_path(game,entry['path'])
        if entry['source_sha256'] is None:assert not path.exists()
        else:assert path.read_bytes()==originals[entry['path']],entry['path']
    report=dict(compiled_upgrade_from_preview1=True,all_40_targets_match=True,original_backup_migrated=True,
        full_original_restore=True,steam_shared_configuration_updated=True,steam_ui_execution_verified=False)
    (output/'upgrade_verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original-game',type=Path,required=True);p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--exe',type=Path,default=Path('dist/BattlespireKoreanPatcher.exe'));p.add_argument('--output',type=Path,default=Path('local-test/upgrade-02'))
    a=p.parse_args();verify(a.original_game,a.previous,a.exe,a.output)
