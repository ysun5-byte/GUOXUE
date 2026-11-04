"""Materialize exact frozen layouts from relative immutable volumes once."""
from pathlib import Path
from hashlib import sha256
import json,sys,os,zipfile,stat,errno,shutil,types
ROOT=Path(__file__).resolve().parent
PINS_SHA='48d4764bdf74803c32e38f729a18eb92ea574202e39d47d9b7f9947352f16aac'
COMMON_SHA='66164f9408e39c112cacf40040d003b4e5e8229b6942abcde9c945b2d3442fa0'
raw=(ROOT/'delivery_common.py').read_bytes()
if sha256(raw).hexdigest()!=COMMON_SHA:raise ValueError('fixed_transport_common_required')
C=types.ModuleType('_c08_common');C.__file__=str(ROOT/'delivery_common.py');exec(compile(raw,C.__file__,'exec'),C.__dict__)

def volume_digest(path):
    h=sha256();n=0
    with path.open('rb')as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk);n+=len(chunk)
    return n,h.hexdigest()

def prepare(selected=None):
    raw=(ROOT/'package_pins.json').read_bytes()
    if sha256(raw).hexdigest()!=PINS_SHA:raise ValueError('fixed_delivery_registration_required')
    pins=C.strict_load(raw.decode('utf8'))
    for rel,meta in pins['files'].items():C.matched(C.safe_path(ROOT,rel),meta)
    catalog=C.strict_load((ROOT/'runtime_catalog.json').read_text());components=catalog['components']
    selected=list(components)if selected is None else selected
    if not selected or len(set(selected))!=len(selected)or any(k not in components for k in selected):raise ValueError('registered_component_selection_required')
    hashes={v['sha256']for key in selected for v in components[key]['files'].values()};storage=catalog['objects'];volumes={storage[h]['volume']for h in hashes};zips={}
    try:
        for name in sorted(volumes):
            meta=catalog['volumes'][name];path=C.safe_path(ROOT,meta['relative_path'])
            if volume_digest(path)!=(meta['bytes'],meta['sha256']):raise ValueError('fixed_frozen_volume_required:'+name)
            zips[name]=zipfile.ZipFile(path)
        objects=C.safe_path(ROOT,'prepared_runtime/.objects');objects.mkdir(parents=True,exist_ok=True)
        for index,h in enumerate(sorted(hashes)):
            spec=storage[h];dest=C.safe_path(objects,h)
            if dest.is_file():C.matched(dest,dict(bytes=spec['bytes'],sha256=h));continue
            info=zips[spec['volume']].getinfo(spec['member'])
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('regular_volume_member_required')
            raw=zips[spec['volume']].read(info)
            if(len(raw),sha256(raw).hexdigest())!=(spec['bytes'],h):raise ValueError('exact_volume_object_required:'+h)
            temporary=C.safe_path(objects,h+'.new');temporary.write_bytes(raw);temporary.chmod(0o444);temporary.replace(dest)
            if index%1000==0:print('prepared objects '+str(index+1)+'/'+str(len(hashes)),file=sys.stderr,flush=True)
        files=0
        for key in selected:
            spec=components[key];base=C.safe_path(ROOT/'prepared_runtime',spec['relative_runtime_path']);base.mkdir(parents=True,exist_ok=True)
            for rel,meta in spec['files'].items():
                dest=C.safe_path(base,rel);dest.parent.mkdir(parents=True,exist_ok=True);source=objects/meta['sha256']
                if dest.exists():C.matched(dest,meta)
                else:
                    try:os.link(source,dest)
                    except OSError as error:
                        if error.errno!=errno.EXDEV:raise
                        shutil.copyfile(source,dest);dest.chmod(0o444)
                files+=1
            actual={str(p.relative_to(base))for p in base.rglob('*')if p.is_file()}
            if actual!=set(spec['files']):raise ValueError('exact_component_inventory_required:'+key)
        return dict(status='exact_runtime_prepared',components=len(selected),file_bindings=files,unique_objects=len(hashes),only_new_blob_inodes_linked=True,old_project_paths_used=False,new_B_or_display=False)
    finally:
        for archive in zips.values():archive.close()

def main(argv):
    if not argv:selected=None
    elif len(argv)>=2 and argv[0]=='--component':selected=argv[1:]
    else:raise ValueError('usage: python3 prepare_runtime.py [--component registered_id ...]')
    print(C.canonical(prepare(selected)))
if __name__=='__main__':sys.dont_write_bytecode=True;main(sys.argv[1:])
