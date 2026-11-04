"""Transport integrity only; no new BaZi or display rules."""
from pathlib import Path
from hashlib import sha256
import json, os, types, sys
ROOT=Path(__file__).resolve().parent

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def strict_load(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('duplicate_JSON_key')
            out[key]=value
        return out
    def constant(value):raise ValueError('nonfinite_JSON_constant')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)

def exact_JSON_tree(value):
    """Reject Python-only types before JSON transport can silently coerce them."""
    pending=[value]
    while pending:
        node=pending.pop()
        if type(node)is dict:
            if any(type(k)is not str for k in node):raise ValueError('JSON_string_keys_required_before_transport')
            pending.extend(node.values())
        elif type(node)is list:pending.extend(node)
        elif node is None or type(node)in(str,bool,int,float):pass
        else:raise ValueError('JSON_tree_types_required_before_transport')

def safe_path(base,relative):
    rel=Path(relative)
    if rel.is_absolute()or'..'in rel.parts:raise ValueError('relative_package_path_required')
    try:parts=Path(base).relative_to(ROOT).parts+rel.parts
    except ValueError:raise ValueError('ROOT_anchored_package_base_required')
    path=ROOT
    for part in parts:
        path=path/part
        if path.is_symlink():raise ValueError('regular_inpackage_ancestors_required')
    if not path.resolve().is_relative_to(ROOT):raise ValueError('regular_inpackage_path_required')
    return path

def matched(path,meta,cache=None):
    if not path.is_file()or path.is_symlink():raise ValueError('regular_package_file_required:'+str(path))
    st=path.stat();key=(st.st_dev,st.st_ino)
    if cache is not None and key in cache:actual=cache[key]
    else:
        raw=path.read_bytes();actual=(len(raw),sha256(raw).hexdigest())
        if cache is not None:cache[key]=actual
    if actual!=(meta['bytes'],meta['sha256']):raise ValueError('package_source_changed_before_provider:'+str(path))

def component_guard(catalog,component):
    spec=catalog['components'][component];base=safe_path(ROOT/'prepared_runtime',spec['relative_runtime_path'])
    if not base.is_dir():raise ValueError('prepare_runtime_required:'+component)
    actual={str(p.relative_to(base))for p in base.rglob('*')if p.is_file()}
    if actual!=set(spec['files']):raise ValueError('exact_component_inventory_required:'+component)
    cache={}
    for rel,meta in spec['files'].items():matched(safe_path(base,rel),meta,cache)
    if spec.get('policy_file'):matched(safe_path(ROOT,spec['policy_file']),spec['policy_pin'])
    return base

def native_module(path):
    module=types.ModuleType('_c08_fixed_native');module.__file__=str(path)
    sys.path.insert(0,str(path.parent))
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module
