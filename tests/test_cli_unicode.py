import json,os,subprocess,sys
from pathlib import Path
from simplecae.benchmarks import bar_case
from simplecae.case import write_json


def test_cli_json_survives_legacy_pipe_encoding_and_unicode_paths(tmp_path):
    root=Path(__file__).resolve().parents[1];folder=tmp_path/'夹爪_🔧';folder.mkdir()
    (folder/'part.step').write_text('case syntax fixture; no numerical claim')
    case=bar_case('part',[1000,0,0],[5,4,3]);write_json(folder/'case.json',case)
    env=dict(os.environ,PYTHONIOENCODING='gbk')
    result=subprocess.run([sys.executable,str(root/'scripts/simplecae_cli.py'),'check',str(folder/'case.json')],capture_output=True,env=env)
    payload=json.loads(result.stdout.decode('utf-8'))
    assert result.returncode==0 and payload['status']=='contract_valid' and '🔧' in payload['file']
