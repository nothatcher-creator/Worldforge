#!/usr/bin/env python3
"""Generate tiny original RoomForge GLB test assets from box primitives.

No third-party model geometry is used. The models intentionally stay simple so
Milestone 8 keeps replacement assets real while adding editor-selectable variants.
"""
from __future__ import annotations
import json, math, os, struct, sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "app/src/main/assets/models")
OUT.mkdir(parents=True, exist_ok=True)

# category, id, dimensions xyz metres, tint RGB, boxes [(cx,cy,cz,sx,sy,sz), ...]
ASSETS = [
    ("Couch", "cartoon_couch_01", (2.10,0.88,0.92), (0.30,0.56,0.72), [
        (0,-0.14,0,1.80,0.36,0.78), (0,0.18,0.29,1.86,0.58,0.22),
        (-0.96,0.00,0,0.20,0.58,0.86), (0.96,0.00,0,0.20,0.58,0.86),
        (0,-0.36,0,1.94,0.14,0.82)
    ]),
    ("Chair", "cartoon_chair_01", (0.62,0.92,0.66), (0.82,0.55,0.26), [
        (0,-0.08,0,0.58,0.12,0.58), (0,0.24,0.25,0.58,0.58,0.12),
        (-0.23,-0.39,-0.23,0.10,0.52,0.10), (0.23,-0.39,-0.23,0.10,0.52,0.10),
        (-0.23,-0.39,0.23,0.10,0.52,0.10), (0.23,-0.39,0.23,0.10,0.52,0.10)
    ]),
    ("Table", "cartoon_table_01", (1.40,0.78,0.82), (0.55,0.36,0.20), [
        (0,0.28,0,1.40,0.12,0.82),
        (-0.56,-0.10,-0.27,0.12,0.64,0.12), (0.56,-0.10,-0.27,0.12,0.64,0.12),
        (-0.56,-0.10,0.27,0.12,0.64,0.12), (0.56,-0.10,0.27,0.12,0.64,0.12)
    ]),
    ("TV", "cartoon_tv_01", (1.20,0.74,0.18), (0.14,0.18,0.22), [
        (0,0.05,0,1.20,0.66,0.10), (0,-0.32,0,0.12,0.18,0.12), (0,-0.41,0,0.48,0.08,0.18)
    ]),
    ("Bed", "cartoon_bed_01", (2.05,0.72,1.55), (0.68,0.47,0.74), [
        (0,-0.12,0,2.00,0.34,1.48), (0,0.09,-0.67,2.02,0.66,0.12),
        (0,-0.34,0,2.05,0.10,1.55)
    ]),
    ("Refrigerator", "cartoon_fridge_01", (0.84,1.85,0.78), (0.78,0.84,0.88), [
        (0,0,0,0.84,1.85,0.78), (0.31,0.28,0.40,0.04,0.44,0.04), (0.31,-0.34,0.40,0.04,0.36,0.04)
    ]),
    ("Toilet", "cartoon_toilet_01", (0.72,0.82,0.82), (0.88,0.90,0.86), [
        (0,-0.22,0.10,0.48,0.38,0.62), (0,0.22,-0.20,0.62,0.54,0.30), (0,-0.42,0.14,0.34,0.18,0.38)
    ]),
    ("Sink", "cartoon_sink_01", (0.82,0.88,0.58), (0.67,0.76,0.80), [
        (0,-0.16,0,0.64,0.60,0.46), (0,0.20,0,0.82,0.18,0.58), (0,0.40,-0.06,0.06,0.22,0.06)
    ]),
    ("Plant", "cartoon_plant_01", (0.70,1.10,0.70), (0.30,0.64,0.32), [
        (0,-0.34,0,0.38,0.34,0.38), (0,0.02,0,0.09,0.62,0.09),
        (-0.16,0.24,0,0.34,0.34,0.22), (0.17,0.38,0.04,0.36,0.34,0.24),
        (0.02,0.55,-0.08,0.34,0.32,0.22)
    ]),
    ("Microwave", "cartoon_microwave_01", (0.60,0.38,0.42), (0.26,0.29,0.32), [
        (0,0,0,0.60,0.38,0.42), (-0.16,0,0.22,0.30,0.23,0.03), (0.22,0.02,0.22,0.05,0.20,0.03)
    ]),
    ("Oven", "cartoon_oven_01", (0.68,0.92,0.66), (0.35,0.37,0.40), [
        (0,0,0,0.68,0.92,0.66), (0,-0.08,0.34,0.46,0.42,0.03), (0,0.35,0.34,0.50,0.10,0.03)
    ]),
]

# M8 adds a genuinely different second replacement per semantic category so the
# editor's Replace action can switch geometry rather than cycling a fake label.
# The variants remain original box-primitive models generated entirely on device/CI.
BASE_ASSETS = list(ASSETS)
for variant_index, (category, asset_id, dims, tint, boxes) in enumerate(BASE_ASSETS):
    # Alternate between slightly wider/deeper silhouettes to keep deformation modest.
    sx = 1.08 if variant_index % 2 == 0 else 0.92
    sy = 0.96 if variant_index % 3 == 0 else 1.04
    sz = 0.94 if variant_index % 2 == 0 else 1.07
    dims2 = (dims[0] * sx, dims[1] * sy, dims[2] * sz)
    boxes2 = [
        (cx * sx, cy * sy, cz * sz, bx * sx, by * sy, bz * sz)
        for (cx, cy, cz, bx, by, bz) in boxes
    ]
    tint2 = tuple(min(0.95, max(0.08, c * 0.82 + 0.12)) for c in tint)
    alt_id = asset_id.rsplit('_', 1)[0] + '_02'
    ASSETS.append((category, alt_id, dims2, tint2, boxes2))

FACES = [
    (( 1, 0, 0), ((1,-1,-1),(1,-1,1),(1,1,1),(1,1,-1))),
    ((-1, 0, 0), ((-1,-1,1),(-1,-1,-1),(-1,1,-1),(-1,1,1))),
    (( 0, 1, 0), ((-1,1,-1),(1,1,-1),(1,1,1),(-1,1,1))),
    (( 0,-1, 0), ((-1,-1,1),(1,-1,1),(1,-1,-1),(-1,-1,-1))),
    (( 0, 0, 1), ((1,-1,1),(-1,-1,1),(-1,1,1),(1,1,1))),
    (( 0, 0,-1), ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1))),
]

def add_box(pos, normal, indices, box):
    cx,cy,cz,sx,sy,sz = box
    base = len(pos)//3
    for n, corners in FACES:
        fbase = len(pos)//3
        for x,y,z in corners:
            pos += [cx + x*sx/2, cy + y*sy/2, cz + z*sz/2]
            normal += list(n)
        indices += [fbase, fbase+1, fbase+2, fbase, fbase+2, fbase+3]

def pad4(b: bytearray, fill=b'\x00'):
    while len(b) % 4: b.extend(fill)

def make_glb(path: Path, boxes):
    pos=[]; normal=[]; indices=[]
    for b in boxes: add_box(pos, normal, indices, b)
    assert max(indices) < 65535
    pbytes = struct.pack('<%sf' % len(pos), *pos)
    nbytes = struct.pack('<%sf' % len(normal), *normal)
    ibytes = struct.pack('<%sH' % len(indices), *indices)
    blob = bytearray()
    off_pos=len(blob); blob.extend(pbytes); pad4(blob)
    off_norm=len(blob); blob.extend(nbytes); pad4(blob)
    off_idx=len(blob); blob.extend(ibytes); pad4(blob)
    xs=pos[0::3]; ys=pos[1::3]; zs=pos[2::3]
    gltf = {
      "asset":{"version":"2.0","generator":"RoomForge procedural low-poly generator"},
      "buffers":[{"byteLength":len(blob)}],
      "bufferViews":[
        {"buffer":0,"byteOffset":off_pos,"byteLength":len(pbytes),"target":34962},
        {"buffer":0,"byteOffset":off_norm,"byteLength":len(nbytes),"target":34962},
        {"buffer":0,"byteOffset":off_idx,"byteLength":len(ibytes),"target":34963}],
      "accessors":[
        {"bufferView":0,"componentType":5126,"count":len(pos)//3,"type":"VEC3","min":[min(xs),min(ys),min(zs)],"max":[max(xs),max(ys),max(zs)]},
        {"bufferView":1,"componentType":5126,"count":len(normal)//3,"type":"VEC3"},
        {"bufferView":2,"componentType":5123,"count":len(indices),"type":"SCALAR"}],
      "meshes":[{"primitives":[{"attributes":{"POSITION":0,"NORMAL":1},"indices":2,"mode":4}]}],
      "nodes":[{"mesh":0}],"scenes":[{"nodes":[0]}],"scene":0
    }
    js = bytearray(json.dumps(gltf,separators=(',',':')).encode('utf-8')); pad4(js,b' ')
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = bytearray(struct.pack('<III',0x46546C67,2,total))
    out += struct.pack('<II',len(js),0x4E4F534A) + js
    out += struct.pack('<II',len(blob),0x004E4942) + blob
    path.write_bytes(out)

manifest={"pack":"roomforge_cartoon_home_m8","version":2,"license":"Original RoomForge procedural test assets; no third-party model geometry.","assets":[]}
for cat, aid, dims, tint, boxes in ASSETS:
    fn=f"{aid}.glb"
    make_glb(OUT/fn, boxes)
    manifest["assets"].append({
        "id":aid,"category":cat,"file":f"models/{fn}","dimensions":list(dims),
        "tint":list(tint),"stretchable":[True,True,True],"tags":["cartoon","low-poly","m8"]
    })
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(OUT/'LICENSE.txt').write_text(
    'RoomForge Milestone 8 test models are original procedural box-primitive assets generated for this project.\n'
    'No third-party model geometry or textures are included.\n', encoding='utf-8')
print(f"Generated {len(ASSETS)} GLB assets in {OUT}")
