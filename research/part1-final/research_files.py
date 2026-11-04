"""Read exact original research/reading files from relative immutable volumes."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile,types,stat
ROOT=Path(__file__).resolve().parent
COMMON_SHA='66164f9408e39c112cacf40040d003b4e5e8229b6942abcde9c945b2d3442fa0'
CATALOG_SHA='a73e49225a1c030d537243e7b9b215034e8b68d2b8702186a3acf7216d0dba53'
raw=(ROOT/'delivery_common.py').read_bytes()
if sha256(raw).hexdigest()!=COMMON_SHA:raise ValueError('fixed_transport_common_required')
C=types.ModuleType('_c08_research_common');C.__file__=str(ROOT/'delivery_common.py');exec(compile(raw,C.__file__,'exec'),C.__dict__)

def fetch(key):
    raw=(ROOT/'research_catalog.json').read_bytes()
    if sha256(raw).hexdigest()!=CATALOG_SHA:raise ValueError('fixed_research_catalog_required')
    catalog=C.strict_load(raw.decode('utf8','strict'))
    if type(key)is not str:raise ValueError('relative_research_key_required')
    if key in catalog.get('unavailable_historical_SHA_keys',{}):raise ValueError('historical_navigation_snapshot_bytes_unavailable:'+key)
    if key in catalog.get('ambiguous_reference_keys',{}):raise ValueError('exact_reference_version_SHA_required:'+key)
    if key=='work/来源索引_current.json':raise ValueError('mutable_source_index_requires_explicit_snapshot_version_or_SHA')
    if key.startswith('reading:'):key=catalog['current_reading_layout'][key[8:]]
    elif key.startswith('original501:'):key=catalog['entire_original501_layout'][key[12:]]
    meta=catalog['files'][key];source=catalog['objects'][meta['sha256']];archive=C.safe_path(ROOT,source['volume_relative_path'])
    with zipfile.ZipFile(archive)as z:
        info=z.getinfo(source['member'])
        if info.is_dir()or stat.S_ISLNK(info.external_attr>>16):raise ValueError('regular_research_member_required')
        raw=z.read(info)
    if(len(raw),sha256(raw).hexdigest())!=(meta['bytes'],meta['sha256']):raise ValueError('exact_research_file_required')
    return raw

def main(argv):
    if len(argv)==2 and argv[0]=='show':sys.stdout.buffer.write(fetch(argv[1]));return 0
    if len(argv)==3 and argv[0]=='extract':
        destination=Path(argv[2]).absolute()
        if destination.resolve().is_relative_to(ROOT):raise ValueError('extract_outside_frozen_package_required')
        destination.write_bytes(fetch(argv[1]));return 0
    if argv==['list-reading']:
        raw=(ROOT/'research_catalog.json').read_bytes()
        if sha256(raw).hexdigest()!=CATALOG_SHA:raise ValueError('fixed_research_catalog_required')
        data=C.strict_load(raw.decode('utf8','strict'));print('\n'.join(sorted(data['current_reading_layout'])));return 0
    raise ValueError('usage: research_files.py list-reading | show key | extract key outside_destination; key reading:path or original501:path or project-relative source key')
if __name__=='__main__':sys.dont_write_bytecode=True;raise SystemExit(main(sys.argv[1:]))
