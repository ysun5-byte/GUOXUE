"""One fixed registered native call per isolated process."""
from pathlib import Path
from hashlib import sha256
import sys,types,json,tempfile
ROOT=Path(__file__).resolve().parent
COMMON_SHA='66164f9408e39c112cacf40040d003b4e5e8229b6942abcde9c945b2d3442fa0'
raw=(ROOT/'delivery_common.py').read_bytes()
if sha256(raw).hexdigest()!=COMMON_SHA:raise ValueError('fixed_transport_common_required')
C=types.ModuleType('_c08_common');C.__file__=str(ROOT/'delivery_common.py');exec(compile(raw,C.__file__,'exec'),C.__dict__)

def dispatch(request,catalog,manifest):
    component=request['component'];provider_count=0;base=None
    def audit(event,args):
        nonlocal provider_count
        if event=='exec'and base is not None:
            name=args[0].co_filename
            if not str(name).startswith('<')and Path(name).absolute().is_relative_to(base):provider_count+=1
    sys.addaudithook(audit)
    try:
        base=C.component_guard(catalog,component)
        if request['kind']=='legacy':
            module=C.native_module(base/'v1_entry.py');payload=dict(request['native_request']);payload['schema_version']=module.VERSION
            result=module.execute(payload)
        else:
            route=next(r for r in manifest['routes']if r['route_id']==request['route_id'])
            if route['component']!=component:raise ValueError('fixed_component_route_binding_required')
            module=C.native_module(base/route['public_entry_file']);payload=request['native_request']
            if route['native_call_style']=='fixed_region_request_path':
                with tempfile.TemporaryDirectory(prefix='C08 original native JSON transport ')as folder:
                    p=Path(folder)/'request.json';p.write_text(C.canonical(payload),encoding='utf8');result=getattr(module,route['public_API'])(route['fixed_operation'],str(p))
            else:result=getattr(module,route['public_API'])(payload)
        C.canonical(result).encode('utf8')
        return dict(ok=True,native_report=result,native_provider_exec=provider_count,provider_counter_scope="this isolated worker only; unchanged legacy may spawn its native child")
    except Exception as error:
        return dict(ok=False,status='native_rejected',error=dict(type=type(error).__name__,message=str(error)),native_report=None,native_provider_exec=provider_count,provider_counter_scope="this isolated worker only; unchanged legacy may spawn its native child")

def main():
    request=C.strict_load(sys.stdin.buffer.read().decode('utf8','strict'))
    catalog=C.strict_load((ROOT/'runtime_catalog.json').read_text());manifest=C.strict_load((ROOT/'route_manifest.json').read_text())
    result=dispatch(request,catalog,manifest);print(C.canonical(result))
    return 0
if __name__=='__main__':sys.dont_write_bytecode=True;raise SystemExit(main())
