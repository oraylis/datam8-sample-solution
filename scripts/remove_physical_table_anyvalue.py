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
BACKUP_DIR = Path(__file__).resolve().parents[1] / 'scripts' / 'tpcds_backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def normalize(s: str) -> str:
    return s.strip().lower()


def remove_property_entries(data):
    """Recursively remove list items where dict contains 'property' == TARGET_PROPERTY (value ignored).
    Also remove dict keys that are named like TARGET_PROPERTY.
    Returns (new_data, changed_bool)."""
    changed = False
    if isinstance(data, dict):
        new = {}
        for k, v in data.items():
            # remove dict keys named physical_table
            if normalize(k) == normalize(TARGET_PROPERTY):
                changed = True
                continue
            nv, ch = remove_property_entries(v)
            if ch:
                changed = True
            new[k] = nv
        return new, changed
    elif isinstance(data, list):
        new_list = []
        for item in data:
            # if this is a dict with a property entry equal to TARGET_PROPERTY, skip it
            if isinstance(item, dict):
                prop = None
                for kk, vv in item.items():
                    if kk.lower() == 'property' and isinstance(vv, str):
                        prop = vv
                        break
                if prop is not None and normalize(prop) == normalize(TARGET_PROPERTY):
                    changed = True
                    continue
            ni, ch = remove_property_entries(item)
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
            # read tolerant of BOM/encodings
            try:
                text = p.read_text(encoding='utf-8')
            except Exception:
                try:
                    text = p.read_text(encoding='utf-8-sig')
                except Exception:
                    text = p.read_text(encoding='cp1252')
        except Exception as e:
            print(f"Skipping (read error): {p} -> {e}")
            continue
        try:
            data = json.loads(text)
        except Exception as e:
            print(f"Skipping (parse error): {p} -> {e}")
            continue
        newdata, changed = remove_property_entries(data)
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
    print(f"Backups are in: {BACKUP_DIR}")
