"""Build the heritage main building of a station as a low-poly glTF (Blender Python; this script is the source).

    blender --background --python scripts/build_station_model.py -- \
        --footprint data/stations/chennai_central/osm.json --out data/stations/chennai_central/heritage.glb \
        [--blend heritage.blend] [--preview preview.png]

The footprint is the heritage feature (`heritage_way`) of osm.json: [east, north] metres. The model is a maroon
two-storey arcaded frontage on that ring, a tower at each end of the building, and a central four-faced clock tower.
Nothing here depends on an OSM height: wall height is WALL_H, the clock tower is TOWER_H.

Frames: Blender X = east, Blender Y = north, Z up, metres, origin at the footprint's area centroid. The glTF
exporter converts to +Y up, so in the .glb: +X = east, -Z = north (the frontend's x = east, z = -north), +Y = up.
Colours: walls #7a1f1f, trim #f3efe6. Plain glTF 2.0, no Draco, no textures.
"""

import json
import math
import sys
from pathlib import Path

import bpy
import mathutils
from mathutils import Vector

WALL_H = 9.0          # eaves: two storeys of 4.5 m (the footprint has no OSM height and the model does not use one)
TOWER_H = 41.0        # the clock tower, as the brief states
END_TOWER_H = 16.0    # corner towers at the two ends
BAY_M = 4.0           # target arcade bay width

CLOCK = {}  # filled by build(): clock tower centre, for the preview cameras

COLOURS = {"wall": "#7a1f1f", "trim": "#f3efe6", "dark": "#2a1717", "roof": "#6b6258", "slate": "#4b4f57"}


def hex_to_linear(h: str) -> tuple[float, float, float, float]:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return lin(r), lin(g), lin(b), 1.0


def hex_to_srgb(h: str) -> tuple[float, float, float, float]:
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return r, g, b, 1.0


def material(name: str, hex_colour: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = hex_to_linear(hex_colour)
    bsdf.inputs["Roughness"].default_value = 0.9
    mat.diffuse_color = hex_to_srgb(hex_colour)  # viewport / Workbench preview
    return mat


class Builder:
    """Collects faces per material; each material becomes one mesh object."""

    def __init__(self) -> None:
        self.parts: dict[str, tuple[list, list]] = {k: ([], []) for k in COLOURS}

    def face(self, mat: str, pts: list[Vector]) -> None:
        verts, faces = self.parts[mat]
        base = len(verts)
        verts.extend(pts)
        faces.append(tuple(range(base, base + len(pts))))

    def solid(self, mat: str, pts: list[Vector], faces: list[tuple[int, ...]]) -> None:
        """A closed convex solid; each face is wound to point away from the centre."""
        centre = sum(pts, Vector()) / len(pts)
        for f in faces:
            fp = [pts[i] for i in f]
            normal = (fp[1] - fp[0]).cross(fp[2] - fp[0])
            if normal.dot(sum(fp, Vector()) / len(fp) - centre) < 0:
                fp.reverse()
            self.face(mat, fp)

    def box(self, mat: str, o: Vector, t: Vector, n: Vector, u0, u1, o0, o1, v0, v1) -> None:
        """Box in the frame (origin o, along t, outward n, up Z): u in [u0,u1], offset in [o0,o1], height [v0,v1]."""
        def p(u, off, v):
            return o + t * u + n * off + Vector((0, 0, v))
        pts = [p(u, off, v) for u in (u0, u1) for off in (o0, o1) for v in (v0, v1)]
        self.solid(mat, pts, [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)])

    def pyramid(self, mat: str, c: Vector, th: float, half: float, z0: float, z1: float, apex_half: float = 0.0) -> None:
        """Pyramid (frustum when apex_half > 0) on a square of half-side `half` rotated by th."""
        def sq(h, z):
            return [c + Vector((h * math.cos(th + a), h * math.sin(th + a), 0)) + Vector((0, 0, z))
                    for a in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4)]
        base = [p for p in sq(half * math.sqrt(2), z0)]
        top = sq(apex_half * math.sqrt(2), z1) if apex_half > 0 else [c + Vector((0, 0, z1))] * 4
        pts = base + (top if apex_half > 0 else [top[0]])
        faces = [(0, 1, 2, 3)]
        if apex_half > 0:
            faces += [(4, 5, 6, 7)] + [(i, (i + 1) % 4, 4 + (i + 1) % 4, 4 + i) for i in range(4)]
        else:
            faces += [(i, (i + 1) % 4, 4) for i in range(4)]
        self.solid(mat, pts, faces)

    def decal(self, mat: str, o: Vector, t: Vector, n: Vector, off: float, poly_uv: list[tuple[float, float]]) -> None:
        """A flat polygon given in (u, v) of the frame (o, t, n), facing n, lifted by `off`."""
        self.face(mat, [o + t * u + n * off + Vector((0, 0, v)) for u, v in poly_uv])

    def objects(self, mats: dict):
        out = []
        for key, (verts, faces) in self.parts.items():
            if not faces:
                continue
            mesh = bpy.data.meshes.new(f"heritage_{key}")
            mesh.from_pydata([tuple(v) for v in verts], [], faces)
            mesh.update()
            mesh.materials.append(mats[key])
            obj = bpy.data.objects.new(f"heritage_{key}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            out.append(obj)
        return out


def arch_uv(u_mid: float, width: float, v0: float, v1: float) -> list[tuple[float, float]]:
    """A round-headed opening: straight sides to the spring, a half circle over (CCW seen from outside)."""
    r = width / 2
    spring = max(v0, v1 - r)
    r = min(r, v1 - v0)
    pts = [(u_mid - width / 2, v0), (u_mid + width / 2, v0), (u_mid + width / 2, spring)]
    pts += [(u_mid + r * math.cos(a), spring + r * math.sin(a)) for a in
            (math.pi * i / 6 for i in range(1, 6))]
    pts += [(u_mid - width / 2, spring)]
    return pts


def area_signed(pts: list[Vector]) -> float:
    return sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def centroid(pts: list[Vector]) -> Vector:
    a = area_signed(pts)
    cx = sum((p.x + q.x) * (p.x * q.y - q.x * p.y) for p, q in zip(pts, pts[1:] + pts[:1])) / (6 * a)
    cy = sum((p.y + q.y) * (p.x * q.y - q.x * p.y) for p, q in zip(pts, pts[1:] + pts[:1])) / (6 * a)
    return Vector((cx, cy, 0))


def inside(ring: list[Vector], p: Vector) -> bool:
    hit = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a.y > p.y) != (b.y > p.y) and p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x:
            hit = not hit
    return hit


def fits(ring: list[Vector], c: Vector, th: float, half: float, margin: float = 0.5) -> bool:
    h = half + margin
    corners = [c + Vector((h * math.cos(th + a), h * math.sin(th + a), 0)) * math.sqrt(2)
               for a in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4)]
    return all(inside(ring, p) for p in corners) and inside(ring, c)


def place_on_axis(ring, axis: Vector, mid: Vector, along: float, th: float, half: float) -> tuple[Vector, float]:
    """Tower centre near `along` metres from the axis midpoint: the largest square (<= `half`) that sits inside."""
    perp = Vector((-axis.y, axis.x, 0))
    for h in (half, half * 0.85, half * 0.7, half * 0.55, half * 0.4):
        for d_along in sorted(range(-30, 31, 2), key=abs):
            for d_perp in sorted((x * 0.75 for x in range(-12, 13)), key=abs):
                c = mid + axis * (along + d_along) + perp * d_perp
                if fits(ring, c, th, h, margin=0.3):
                    return c, h
    raise SystemExit(f"no room for a tower of half-side {half} near {along} m")


def build(footprint: list[list[float]], mats: dict) -> list:
    ring = [Vector((x, y, 0)) for x, y in footprint]
    c0 = centroid(ring)
    ring = [p - c0 for p in ring]
    if area_signed(ring) < 0:
        ring.reverse()  # counter-clockwise, so the right-hand side of every edge is outside
    b = Builder()

    # ---- walls, arcades, cornice --------------------------------------------------------------------------
    for a, e in zip(ring, ring[1:] + ring[:1]):
        d = e - a
        length = d.length
        t = d / length
        n = Vector((t.y, -t.x, 0))
        b.decal("wall", a, t, n, 0, [(0, 0), (length, 0), (length, WALL_H), (0, WALL_H)])
        b.box("trim", a, t, n, 0, length, 0, 0.35, WALL_H - 0.5, WALL_H + 0.45)        # cornice and parapet
        if length < 6:
            continue
        b.box("trim", a, t, n, 0, length, 0, 0.18, 4.3, 4.7)                           # string course
        b.box("trim", a, t, n, 0, length, 0, 0.18, 0, 0.5)                             # plinth
        bays = max(1, int((length - 1.0) // BAY_M))
        w = length / bays
        for i in range(bays):
            mid = (i + 0.5) * w
            ow = w * 0.55
            b.decal("trim", a, t, n, 0.06, arch_uv(mid, ow + 0.6, 0.0, 4.0))            # arcade surround
            b.decal("dark", a, t, n, 0.10, arch_uv(mid, ow, 0.0, 3.6))                  # arch opening
            b.decal("trim", a, t, n, 0.06, arch_uv(mid, ow * 0.7 + 0.5, 5.0, 7.9))      # window surround
            b.decal("dark", a, t, n, 0.10, arch_uv(mid, ow * 0.7, 5.2, 7.6))            # upper window

    # flat roof: triangulated ring
    for tri in mathutils.geometry.tessellate_polygon([ring]):
        b.face("roof", [ring[i] + Vector((0, 0, WALL_H)) for i in tri][::1])
    # tessellate_polygon winds triangles consistently; make every roof face point up
    verts, faces = b.parts["roof"]
    for k, f in enumerate(faces):
        pts = [verts[i] for i in f]
        if (pts[1] - pts[0]).cross(pts[2] - pts[0]).z < 0:
            faces[k] = tuple(reversed(f))

    # ---- towers -------------------------------------------------------------------------------------------
    xs = [(p.x, p.y) for p in ring]
    mean = Vector((sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs), 0))
    sxx = sum((x - mean.x) ** 2 for x, _ in xs)
    syy = sum((y - mean.y) ** 2 for _, y in xs)
    sxy = sum((x - mean.x) * (y - mean.y) for x, y in xs)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)                       # long axis of the building
    axis = Vector((math.cos(theta), math.sin(theta), 0))
    proj = [(p - mean).dot(axis) for p in ring]
    lo, hi = min(proj), max(proj)
    mid = mean + axis * ((lo + hi) / 2)

    def tower(c: Vector, half: float, height: float, cap_h: float, bands: list[float]) -> None:
        perp = Vector((-axis.y, axis.x, 0))
        for k in range(4):
            nk = Vector((math.cos(theta + k * math.pi / 2), math.sin(theta + k * math.pi / 2), 0))
            tk = Vector((-nk.y, nk.x, 0))
            o = c + nk * half
            b.decal("wall", o - tk * half, tk, nk, 0, [(0, 0), (2 * half, 0), (2 * half, height), (0, height)])
            for z in bands:
                b.box("trim", o - tk * (half + 0.15), tk, nk, 0, 2 * half + 0.3, 0, 0.15, z, z + 0.5)
        b.pyramid("slate", c, theta, half + 0.4, height + 0.5, height + 0.5 + cap_h)
        b.box("trim", c - axis * (half + 0.2) - perp * (half + 0.2), axis, perp,
              0, 2 * half + 0.4, 0, 2 * half + 0.4, height, height + 0.5)

    half_end = 3.0
    for along in (lo + 6.0, hi - 6.0):
        c, he = place_on_axis(ring, axis, mid, along - (lo + hi) / 2, theta, half_end)
        tower(c, he, END_TOWER_H, 4.5, [5.0, 9.5, END_TOWER_H - 0.9])

    # central clock tower: shaft to 30 m, clock stage to 35 m, slate spire to exactly TOWER_H
    half = 3.6
    c, half = place_on_axis(ring, axis, mid, 0.0, theta, half)
    CLOCK["c"] = c
    shaft_h, clock_top = 30.0, 35.0
    for k in range(4):
        nk = Vector((math.cos(theta + k * math.pi / 2), math.sin(theta + k * math.pi / 2), 0))
        tk = Vector((-nk.y, nk.x, 0))
        o = c + nk * half
        b.decal("wall", o - tk * half, tk, nk, 0, [(0, 0), (2 * half, 0), (2 * half, clock_top), (0, clock_top)])
        for z in (8.0, 16.0, 24.0, shaft_h - 0.5):
            b.box("trim", o - tk * (half + 0.2), tk, nk, 0, 2 * half + 0.4, 0, 0.2, z, z + 0.6)
        for u in (-half + 0.9, half - 0.9):                          # tall slit windows up the shaft
            b.decal("trim", o, tk, nk, 0.05, arch_uv(u, 1.3, 11.0, 14.6))
            b.decal("dark", o, tk, nk, 0.09, arch_uv(u, 0.9, 11.2, 14.4))
            b.decal("trim", o, tk, nk, 0.05, arch_uv(u, 1.3, 19.0, 22.6))
            b.decal("dark", o, tk, nk, 0.09, arch_uv(u, 0.9, 19.2, 22.4))
        # clock face: dark rim, white dial, two hands (hour and minute)
        cz, r = 32.6, 2.1
        ring_uv = [(r * math.cos(2 * math.pi * i / 20), cz + r * math.sin(2 * math.pi * i / 20)) for i in range(20)]
        b.decal("dark", o, tk, nk, 0.07, [(u * 1.12, cz + (v - cz) * 1.12) for u, v in ring_uv])
        b.decal("trim", o, tk, nk, 0.12, ring_uv)
        for ang, ln, wd in ((math.radians(70), 1.5, 0.12), (math.radians(-20), 1.9, 0.08)):
            dx, dy = math.cos(ang), math.sin(ang)
            px, py = -dy * wd, dx * wd
            b.decal("dark", o, tk, nk, 0.17, [(px, cz + py), (dx * ln + px, cz + dy * ln + py),
                                              (dx * ln - px, cz + dy * ln - py), (-px, cz - py)])
        b.box("trim", o - tk * (half + 0.3), tk, nk, 0, 2 * half + 0.6, 0, 0.3, clock_top, clock_top + 0.6)
    b.pyramid("slate", c, theta, half + 0.5, clock_top + 0.6, TOWER_H - 1.5, apex_half=1.0)
    b.pyramid("slate", c, theta, 1.0, TOWER_H - 1.5, TOWER_H)
    return b.objects(mats)


def preview(path: Path, objs: list) -> None:
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 800, 450
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light, shading.color_type, shading.show_cavity = "STUDIO", "MATERIAL", False
    scene.view_settings.view_transform = "Standard"
    scene.world = scene.world or bpy.data.worlds.new("w")
    scene.world.color = (0.62, 0.72, 0.85)
    ground_mesh = bpy.data.meshes.new("ground")
    ground_mesh.from_pydata([(-200, -200, -0.05), (200, -200, -0.05), (200, 200, -0.05), (-200, 200, -0.05)], [], [(0, 1, 2, 3)])
    ground = bpy.data.objects.new("ground", ground_mesh)
    gm = bpy.data.materials.new("ground")
    gm.diffuse_color = (0.55, 0.55, 0.5, 1)
    ground_mesh.materials.append(gm)
    scene.collection.objects.link(ground)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.clip_end = 1000

    def shot(out: Path, eye: Vector, target: Vector, lens: float) -> None:
        cam.location = eye
        cam.data.lens = lens
        cam.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)

    pts = [v.co for o in objs for v in o.data.vertices]
    centre = Vector(((min(p.x for p in pts) + max(p.x for p in pts)) / 2, (min(p.y for p in pts) + max(p.y for p in pts)) / 2, 0))
    shot(path, centre + Vector((-15, -115, 42)), centre + Vector((0, 0, 9)), 24)
    clock = CLOCK["c"]
    shot(path.with_name(path.stem + "_tower" + path.suffix), clock + Vector((-14, -50, 30)), clock + Vector((0, 0, 27)), 40)
    bpy.data.objects.remove(ground)


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opt = {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2)}
    world = json.loads(Path(opt["--footprint"]).read_text(encoding="utf-8"))
    feature = next(f for f in world["features"] if f["id"] == world.get("heritage_way") or f["kind"] == "heritage")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = {k: material(f"heritage_{k}", v) for k, v in COLOURS.items()}
    objs = build(feature["points"], mats)

    lo = Vector((min(v.co.x for o in objs for v in o.data.vertices), min(v.co.y for o in objs for v in o.data.vertices),
                 min(v.co.z for o in objs for v in o.data.vertices)))
    hi = Vector((max(v.co.x for o in objs for v in o.data.vertices), max(v.co.y for o in objs for v in o.data.vertices),
                 max(v.co.z for o in objs for v in o.data.vertices)))
    tris = sum(len(p.vertices) - 2 for o in objs for p in o.data.polygons)
    print(f"model {feature['id']}: bbox east {lo.x:.1f}..{hi.x:.1f} north {lo.y:.1f}..{hi.y:.1f} up {lo.z:.1f}..{hi.z:.1f}"
          f" m, {tris} triangles")

    out = Path(opt["--out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=str(out), export_format="GLB", use_selection=True, export_yup=True,
                              export_apply=True, export_materials="EXPORT", export_cameras=False,
                              export_lights=False, export_draco_mesh_compression_enable=False)
    if "--blend" in opt:
        bpy.ops.wm.save_as_mainfile(filepath=opt["--blend"], compress=True)
    if "--preview" in opt:
        preview(Path(opt["--preview"]), objs)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


main()
