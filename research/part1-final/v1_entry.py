"""Original V1 three-field routing extended to adopted research native APIs."""
from pathlib import Path
from hashlib import sha256
import json,sys,subprocess,types
ROOT=Path(__file__).resolve().parent
VERSION='v1-capability-entry-research-0.8'
PINS_SHA='48d4764bdf74803c32e38f729a18eb92ea574202e39d47d9b7f9947352f16aac'
COMMON_SHA='66164f9408e39c112cacf40040d003b4e5e8229b6942abcde9c945b2d3442fa0'
PREPARE_SHA='d2e9af67d842fc64ffcb53cbd7acca2634d7eeb63f1e25a4367e20010431b840'
raw=(ROOT/'delivery_common.py').read_bytes()
if sha256(raw).hexdigest()!=COMMON_SHA:raise ValueError('fixed_transport_common_required')
C=types.ModuleType('_c08_common');C.__file__=str(ROOT/'delivery_common.py');exec(compile(raw,C.__file__,'exec'),C.__dict__)

def verify_registration():
    raw=(ROOT/'package_pins.json').read_bytes()
    if sha256(raw).hexdigest()!=PINS_SHA:raise ValueError('fixed_delivery_registration_required')
    pins=C.strict_load(raw.decode('utf8'))
    for rel,meta in pins['files'].items():C.matched(C.safe_path(ROOT,rel),meta)
    return C.strict_load((ROOT/'route_manifest.json').read_text())

def execute(request):
    output=dict(version=VERSION,entry_status='rejected',route_id=None,native_report=None,issues=[],new_B_or_display_adapter=False,real_prediction_validated=False)
    try:
        C.canonical(request).encode('utf8')
        C.exact_JSON_tree(request)
        if type(request)is not dict or set(request)!={'schema_version','route_id','native_request'}:raise ValueError('exact_original_threefield_entry_required')
        if type(request['route_id'])is not str:raise ValueError('string_route_required')
        if request['schema_version']!=VERSION:raise ValueError('registered_delivery_schema_required')
        output['route_id']=request['route_id'];manifest=verify_registration();routes=[r for r in manifest['routes']if r['route_id']==request['route_id']]
        if len(routes)>1:raise ValueError('unique_fixed_route_required')
        route=routes[0]if routes else None
        legacy=route is None or route['transport_kind']=='legacy31'
        component='__legacy_v1_entry071__'if legacy else route['component']
        catalog=C.strict_load((ROOT/'runtime_catalog.json').read_text());base=C.safe_path(ROOT/'prepared_runtime',catalog['components'][component]['relative_runtime_path'])
        if not base.exists():
            script=ROOT/'prepare_runtime.py'
            if sha256(script.read_bytes()).hexdigest()!=PREPARE_SHA:raise ValueError('fixed_lazy_preparation_script_required')
            prepared=subprocess.run([sys.executable,'-I','-B',str(script),'--component',component],capture_output=True,timeout=1200,check=False)
            if prepared.returncode:raise ValueError('selected_runtime_preparation_failed_before_native:'+prepared.stderr.decode('utf8','replace')[-1000:])
            receipt=C.strict_load(prepared.stdout.decode('utf8','strict'))
            if receipt.get('status')!='exact_runtime_prepared'or receipt.get('components')!=1:raise ValueError('exact_selected_component_preparation_required')
        call=dict(kind='legacy'if legacy else'current',component=component,route_id=request['route_id'],native_request=request if legacy else request['native_request'])
        result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'native_worker.py')],input=C.canonical(call).encode('utf8'),capture_output=True,timeout=1200,check=False)
        if result.returncode:raise ValueError('isolated_native_process_failed:'+result.stderr.decode('utf8','replace')[:1000])
        response=C.strict_load(result.stdout.decode('utf8','strict'));output.update(response)
        if response['ok']:
            report=response['native_report'];hard=report.get('entry_status')=='rejected'if legacy else report.get('status')in {'rejected','invalid_input','binding_mismatch','dependency_mismatch','dependency_unavailable','incompatible_schema','export_contract_mismatch'}
            output['entry_status']='rejected'if hard else'executed';output['native_request_unmodified']=not legacy
            output['transport_mapping']='new outer entry schema -> exact old0.7.1 schema only; original native_request unchanged'if legacy else'complete raw native_request unchanged -> fixed adopted native public API'
            output['native_scope_kind']='original31_contract'if legacy else route['native_scope_kind']
            output['adoption_policy_sha256']=None if legacy else route['policy_pin']['sha256']
        return output
    except (ValueError,TypeError,KeyError,RecursionError,UnicodeError,OSError,subprocess.SubprocessError)as error:
        output['issues']=[dict(type=type(error).__name__,message=str(error))];return output

def main(argv):
    try:
        if len(argv)!=1:raise ValueError('usage: python3 v1_entry.py request.json')
        request=C.strict_load(Path(argv[0]).read_bytes().decode('utf8','strict'));result=execute(request)
    except (ValueError,TypeError,UnicodeError,OSError,RecursionError)as error:result=dict(version=VERSION,entry_status='rejected',issues=[dict(type=type(error).__name__,message=str(error))],native_report=None)
    print(C.canonical(result));return 0 if result['entry_status']=='executed'else 2
if __name__=='__main__':sys.dont_write_bytecode=True;raise SystemExit(main(sys.argv[1:]))
