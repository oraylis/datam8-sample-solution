#!/usr/bin/env python3
from pathlib import Path
import json
import shutil
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1] / 'Model' / '050-AtScale' / 'TPCDS'
if not ROOT.exists():
    print(f"ERROR: root path does not exist: {ROOT}")
    sys.exit(1)

TARGET_PROPERTY = 'physical_table'
TARGET_VALUE = 'innolab_atscale.tpcds_sf10000.call_center'

BACKUP_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'tpcds_backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def normalize(s: str) -> str:
    return s.strip().lower()


def remove_target_property(data):
    """Recursively scan data structures. If encountering a list, remove any dict items
    where 'property' equals TARGET_PROPERTY and 'value' equals TARGET_VALUE (case-insensitive).
    Returns (new_data, changed_bool)."""
    changed = False
    if isinstance(data, dict):
        new = {}
        for k, v in data.items():
            nv, ch = remove_target_property(v)
            if ch:
                changed = True
            new[k] = nv
        return new, changed
    elif isinstance(data, list):
        new_list = []
        for item in data:
            if isinstance(item, dict):
                prop = None
                val = None
                for kk, vv in item.items():
                    if kk.lower() == 'property' and isinstance(vv, str):
                        prop = vv
                    if kk.lower() == 'value' and isinstance(vv, str):
                        val = vv
                if prop is not None and val is not None:
                    if normalize(prop) == TARGET_PROPERTY and normalize(val) == normalize(TARGET_VALUE):
                        changed = True
                        continue
            ni, ch = remove_target_property(item)
            if ch:
                changed = True
            new_list.append(ni)
        return new_list, changed
    else:
        return data, False


if __name__ == '__main__':
    files = list(ROOT.rglob('*.json'))
    print(f"Scanning {len(files)} .json files under: {ROOT}")
    modified = []
    for p in files:
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            try:
                text = p.read_text(encoding='utf-8-sig')
            except Exception:
                text = p.read_text(encoding='cp1252')
        try:
            data = json.loads(text)
        except Exception as e:
            print(f"Skipping (parse error): {p} -> {e}")
            continue
        newdata, changed = remove_target_property(data)
        if changed:
            # backup
            stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup_path = BACKUP_DIR / f"{p.name}.{stamp}.bak"
            shutil.copy2(p, backup_path)
            # write back as utf-8 without BOM
            p.write_text(json.dumps(newdata, ensure_ascii=False, indent=2), encoding='utf-8')
            modified.append(str(p))
            print(f"Modified: {p} (backup: {backup_path.name})")
    print('\nSummary:')
    print(f"  Scanned: {len(files)}")
    print(f"  Modified: {len(modified)}")
    if modified:
        for m in modified:
            print('   -', m)
