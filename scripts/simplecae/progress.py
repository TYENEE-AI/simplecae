"""Optional observable analysis stages; library calls remain silent by default."""
def emit(callback,stage,**details):
    if callback is not None:callback({'stage':stage,**details})

def cli_progress(event):
    import json,sys
    print(json.dumps({'simplecae_progress':event},ensure_ascii=False),file=sys.stderr,flush=True)
