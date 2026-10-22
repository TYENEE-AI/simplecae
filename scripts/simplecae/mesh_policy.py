"""Expose existing numerical mesh contracts without changing their acceptance."""
def mesh_policy(case):
    version=case.get('schema_version')
    if version in ('thermal-solid-1.0','modal-solid-1.0'):
        count, lower, upper=3, .35, .85
    elif version in ('1.0','2.0','assembly-1.0'):
        count, lower, upper=None, None, .8
    else:
        return {'applicable':False,'meaning':'Use component policies for robot FEM; no structural mesh contract imposed on calculation-only checks.'}
    sizes=case.get('mesh',{}).get('sizes_mm',[])
    factor=.7  # Planning example inside all supported ratio ranges, not a gate.
    proposed=[float(format(sizes[0]*factor**i,'.6g')) for i in range(3)] if sizes else None
    return {'applicable':True,'minimum_levels':3,'exact_levels':count,
            'successive_ratio_minimum':lower,'successive_ratio_maximum':upper,
            'requested_sizes_mm':sizes,'legal_example_sizes_mm':proposed,
            'coarse_only_can_pass':False,
            'accuracy_inputs':{k:v for k,v in case.get('mesh',{}).items() if 'tolerance' in k},
            'stop_policy':'Stop after qualified pass/fail; unresolved evidence needs a located repair and remaining budget. No endless refinement or automatic criterion relaxation.'}
