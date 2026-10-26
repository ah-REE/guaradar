"""Feasibility probe: does 30 m SRTM actually work for Guayaquil, and is it better than the 90 m DSM?

NOT application code. Answers three questions with measurement:
  1. Can SRTM 1-arcsec (30 m) tiles be fetched and decoded without third-party packages?
  2. What does Guayaquil's terrain look like at 30 m, versus the 90 m DSM numbers we already have?
  3. Is 30 m SRTM meaningfully different from 90 m Copernicus DSM for a city that spans 3-10 m?

Usage: python3 research/terraincheck.py
Needs: curl on PATH, Python stdlib only (decodes PNG via zlib, no Pillow).
"""
import math
import struct
import subprocess
import sys
import zlib

LAT, LON = -2.19, -79.88          # central Guayaquil
UA = 'GuaRadar-research/0.1 (hackathon feasibility check)'


def deg2num(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def fetch(url):
    r = subprocess.run(['curl', '-s', '--max-time', '120', '-A', UA, url],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"fetch failed: {url}")
    return r.stdout


def decode_png_rgb(data):
    """Minimal PNG decoder for 8-bit RGB/RGBA, non-interlaced. Returns (w, h, rows)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n', "not a PNG"
    pos = 8
    w = h = bit_depth = color_type = None
    idat = b''
    while pos < len(data):
        (length,) = struct.unpack('>I', data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b'IHDR':
            w, h, bit_depth, color_type = struct.unpack('>IIBB', chunk[:10])
        elif ctype == b'IDAT':
            idat += chunk
        elif ctype == b'IEND':
            break
    assert bit_depth == 8, f"unexpected bit depth {bit_depth}"
    channels = {2: 3, 6: 4, 0: 1}[color_type]
    raw = zlib.decompress(idat)
    stride = w * channels
    out = bytearray(stride * h)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, channels, out


def terrarium_elev(r, g, b):
    """Mapzen/AWS terrarium encoding: elevation in metres."""
    return (r * 256 + g + b / 256.0) - 32768.0


print("=" * 68)
print("1. SRTM 1-arcsec (30 m) via AWS skadi, direct HGT")
print("=" * 68)
# Guayaquil sits in 1-degree tile S03W080 (lat -3..-2, lon -80..-79).
# SRTM tiles are named by their SOUTH-WEST corner, so S02W080 would be lat -2..-1: wrong city.
hgt_gz = fetch('https://s3.amazonaws.com/elevation-tiles-prod/skadi/S03/S03W080.hgt.gz')
try:
    hgt = zlib.decompress(hgt_gz, 16 + zlib.MAX_WBITS)   # gzip stream
    src = "skadi .hgt.gz"
except Exception:
    hgt = hgt_gz
    src = "raw"

n = int(math.sqrt(len(hgt) / 2))
print(f"decompressed {len(hgt):,} bytes -> grid {n} x {n}  (source: {src})")
print(f"expected 3601x3601 for SRTM1, or 1201x1201 for SRTM3")

samples = {
    "Cerro Santa Ana (Centro)": (-2.1962, -79.8865),
    "Norte / Sauces":           (-2.1420, -79.9050),
    "Sur / Cisne II":           (-2.2200, -79.9100),
    "Martha de Roldos":         (-2.1580, -79.8900),
    "NW outskirts":             (-2.3050, -79.9000),
    "Guayas estuary edge":      (-2.2400, -79.9400),
}

print(f"\n{'location':28} {'30 m SRTM':>10} {'90 m DSM':>10}  {'delta':>7}")
print("-" * 68)
dsm90 = [10.0, 7.0, 7.0, 6.0, 3.0, None]  # measured earlier via Open-Meteo, last not sampled
vals30 = []
rows_out = []
for i, (name, (la, lo)) in enumerate(samples.items()):
    # tile S03W080 covers lat -3..-2, lon -80..-79
    # row 0 = northernmost (-2.0), col 0 = westernmost (-80.0)
    row = int(round((-2.0 - la) * (n - 1)))
    col = int(round((lo - (-80.0)) * (n - 1)))
    if not (0 <= row < n and 0 <= col < n):
        print(f"{name:28} {'out of tile':>10}")
        continue
    off = (row * n + col) * 2
    (h,) = struct.unpack('>h', hgt[off:off + 2])
    vals30.append(h)
    d = dsm90[i]
    delta = '' if d is None else f"{h - d:+.0f} m"
    print(f"{name:28} {h:>10} m {('-' if d is None else int(d)):>10} {'':>3} {delta:>7}")
    rows_out.append((name, h, d))

print(f"\n30 m SRTM across the city: min {min(vals30)} m, max {max(vals30)} m, "
      f"range {max(vals30) - min(vals30)} m")
print(f"90 m DSM  across sampled : min {min(d for _, _, d in rows_out if d is not None):.0f} m, "
      f"max {max(d for _, _, d in rows_out if d is not None):.0f} m")

print("\n" + "=" * 68)
print("2. Terrarium tiles (SRTM-derived, 30 m) — cross-check the same points")
print("=" * 68)
for z in (12, 13):
    x, y = deg2num(LAT, LON, z)
    url = f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
    png = fetch(url)
    w, h, ch, px = decode_png_rgb(png)
    # value at tile centre
    cx, cy = w // 2, h // 2
    o = (cy * w + cx) * ch
    elev = terrarium_elev(px[o], px[o + 1], px[o + 2])
    # crude local relief: min/max over the tile
    lo_v, hi_v = 1e9, -1e9
    for yy in range(0, h, 4):
        for xx in range(0, w, 4):
            oo = (yy * w + xx) * ch
            e = terrarium_elev(px[oo], px[oo + 1], px[oo + 2])
            lo_v = min(lo_v, e)
            hi_v = max(hi_v, e)
    print(f"z={z} tile {w}x{h}: centre elevation {elev:.0f} m  "
          f"tile min {lo_v:.0f} m  max {hi_v:.0f} m  relief {hi_v - lo_v:.0f} m")

print("\nInterpretation: if 30 m relief is only a few metres, terrain cannot discriminate")
print("between a street that floods and one that does not. Sensors and reports must lead.")
