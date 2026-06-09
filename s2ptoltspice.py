"""
@author: https://mdiea.github.io/

Unified tool for NanoVNA S2P measurements → LTspice model generation.

Subcommands:
  convert       Convert a full S2P file into LTspice .sub / .asy / .asc files.
  merge         Merge two half-measurements (forward + reverse) into a full S2P.
  merge-convert Merge two half-measurements and immediately convert to LTspice.
"""

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter, FileType
from pathlib import Path
from skrf import Network
from re import match
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def convert_frequency(value):
    """Convert a frequency string like '425MHz' or '1GHz' to Hz (float)."""
    m = match(r'(\d+\.?\d*)([a-zA-Z]+)', value.lower())
    if not m:
        raise ValueError(f"Invalid frequency: {value}")
    number, unit = m.groups()
    unit_map = {'hz': 1, 'khz': 1e3, 'mhz': 1e6, 'ghz': 1e9}
    if unit not in unit_map:
        raise ValueError(f"Unsupported frequency unit: {unit}")
    return float(number) * unit_map[unit]


def merge_networks(forward_path, reverse_path, silent=False):
    """
    Merge two NanoVNA half-measurements into a combined 2-port Network.

    forward_path  – S2P with S11 and S21 (port1→port2)
    reverse_path  – S2P with S22 and S12 (port2→port1, DUT flipped)
    Returns a skrf.Network with all four S-parameters filled in.
    """
    fwd = Network(forward_path)
    rev = Network(reverse_path)

    if not np.allclose(fwd.f, rev.f, rtol=1e-6):
        if not silent:
            print("Warning: frequency grids differ — interpolating reverse onto forward grid.")
        rev = rev.interpolate(fwd.frequency)

    combined = fwd.copy()
    combined.s[:, 1, 1] = rev.s[:, 0, 0]   # S22 of DUT = S11 of reversed meas.
    combined.s[:, 0, 1] = rev.s[:, 1, 0]   # S12 of DUT = S21 of reversed meas.
    return combined


def do_convert(touchstone_path, overwrite=False, silent=False, fmin_str=None, fmax_str=None):
    """Generate LTspice .sub / .asy / .asc files from a Touchstone S2P file."""

    def log(msg):
        if not silent:
            print(msg)

    name = Path(touchstone_path).stem
    sub_file = name + '.sub'
    asy_file = name + '.asy'
    asc_file = 'test-' + name + '.asc'

    try:
        touchstone = Network(touchstone_path)
    except Exception as e:
        print(f"Error loading Touchstone file: {e}")
        raise SystemExit(1)

    fmin = convert_frequency(fmin_str) if fmin_str else touchstone.f[0]
    fmax = convert_frequency(fmax_str) if fmax_str else touchstone.f[-1]

    touchstone_filtered = touchstone[f'{fmin}Hz-{fmax}Hz']
    log(f"Filtered frequencies: from {touchstone_filtered.f[0]}Hz to {touchstone_filtered.f[-1]}Hz")

    frequencies = touchstone_filtered.f.squeeze()
    Z01 = touchstone.z0[0].real[0]
    Z02 = touchstone.z0[0].real[1]
    log(f"Z0 port 1: {Z01}   Z0 port 2: {Z02}")

    s_parameters = {
        'B11 11 12 V={V(10,3)}': (touchstone_filtered.s11.s_re.squeeze(), touchstone_filtered.s11.s_im.squeeze()),
        'B22 22 3  V={V(20,3)}': (touchstone_filtered.s22.s_re.squeeze(), touchstone_filtered.s22.s_im.squeeze()),
        'B12 12 3  V={V(20,3)}': (touchstone_filtered.s12.s_re.squeeze(), touchstone_filtered.s12.s_im.squeeze()),
        'B21 21 22 V={V(10,3)}': (touchstone_filtered.s21.s_re.squeeze(), touchstone_filtered.s21.s_im.squeeze()),
    }

    def format_s_parameter(bname, re, im, freqs):
        data = [f'({freq},{r:.12e},{i:.12e})' for freq, r, i in zip(freqs, re, im)]
        lines = [f'{bname} R_I FREQ {data[0]}'] + [f'+{d}' for d in data[1:]]
        return '\n'.join(lines) + '\n'

    # Overwrite check
    for fpath in [sub_file, asy_file, asc_file]:
        if Path(fpath).exists() and not overwrite:
            response = input(f"Warning: {fpath} already exists. Overwrite? (y/n): ")
            if response.lower() != 'y':
                print(f"Aborted: {fpath} will not be overwritten.")
                raise SystemExit(1)

    # --- .sub ---
    with open(sub_file, mode='w') as f:
        f.write(f'.subckt {name} 1 2 3\n')
        f.write('R1N 10 1 -50\n')
        f.write('R2P 21 20 100\n')
        f.write('R1P 11 10 100\n')
        f.write('R4 20 2 -50\n')
        for bname, (re, im) in s_parameters.items():
            f.write(format_s_parameter(bname, re, im, frequencies))
        f.write('.ends s_block')
    log(f"Write {sub_file}")

    # --- .asy ---
    asy_content = [
        'Version 4\n', 'SymbolType CELL\n',
        'LINE Normal 0 26 34 26\n', 'LINE Normal 0 -15 34 -15\n',
        'LINE Normal 31 23 31 7\n', 'LINE Normal 3 4 3 -12\n',
        'LINE Normal 34 -15 34 -12\n', 'LINE Normal 0 -15 34 -15\n',
        'LINE Normal 0 7 0 -15\n', 'LINE Normal 31 7 0 7\n',
        'LINE Normal 31 23 31 7\n', 'LINE Normal 0 23 31 23\n',
        'LINE Normal 0 26 0 23\n', 'LINE Normal 34 26 0 26\n',
        'LINE Normal 34 4 34 26\n', 'LINE Normal 3 4 34 4\n',
        'LINE Normal 3 -12 3 4\n', 'LINE Normal 34 -12 3 -12\n',
        'RECTANGLE Normal -48 -32 80 80\n',
        'TEXT 17 34 Center 0 PARAMS\n',
        'TEXT -33 38 VCenter 0 mdiea.github.io\n',
        'WINDOW 0 -49 -58 Left 2\n', 'WINDOW 38 17 -39 Center 0\n',
        f'SYMATTR SpiceModel {name}\n', 'SYMATTR Prefix X\n',
        f'SYMATTR ModelFile {sub_file}\n',
        'SYMATTR Description S parameters\n',
        'PIN -48 -16 LEFT 8\n', 'PINATTR PinName 1\n', 'PINATTR SpiceOrder 1\n',
        'PIN 80 -16 RIGHT 8\n', 'PINATTR PinName 2\n', 'PINATTR SpiceOrder 2\n',
        'PIN 16 80 BOTTOM 8\n', 'PINATTR PinName gnd\n', 'PINATTR SpiceOrder 3\n',
    ]
    with open(asy_file, mode='w') as f:
        f.writelines(asy_content)
    log(f"Write {asy_file}")

    # --- .asc ---
    asc_content = [
        'Version 4\n', 'SHEET 1 880 680\n',
        'WIRE 144 112 32 112\n', 'WIRE 352 112 272 112\n',
        'WIRE 32 160 32 112\n', 'WIRE 352 176 352 112\n',
        'WIRE 208 256 208 208\n', 'WIRE 32 272 32 240\n',
        'WIRE 352 272 352 256\n',
        'FLAG 208 256 0\n', 'FLAG 32 272 0\n', 'FLAG 352 272 0\n',
        'SYMBOL voltage 32 144 R0\n',
        'WINDOW 123 24 124 Left 2\n', 'WINDOW 39 24 152 Left 2\n',
        'SYMATTR Value2 AC 1\n',
        f'SYMATTR SpiceLine Rser={Z01}\n',
        'SYMATTR InstName V1\n', 'SYMATTR Value ""\n',
        'SYMBOL res 336 160 R0\n', 'SYMATTR InstName RL\n',
        f'SYMATTR Value {Z02}\n',
        f'SYMBOL {name} 192 128 R0\n', 'SYMATTR InstName U1\n',
        f'TEXT 40 0 Left 2 !.ac lin {len(frequencies)} {frequencies[0]} {frequencies[-1]}\n',
        'TEXT 40 32 Left 2 !.net I(RL) V1\n',
    ]
    with open(asc_file, mode='w') as f:
        f.writelines(asc_content)
    log(f"Write {asc_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = ArgumentParser(
        description="NanoVNA S2P → LTspice model toolkit",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--version', action='version', version='%(prog)s 2.0')

    subparsers = parser.add_subparsers(dest='command', metavar='COMMAND')
    subparsers.required = True

    # --- convert ---
    p_conv = subparsers.add_parser(
        'convert',
        help="Convert a full S2P file to LTspice .sub / .asy / .asc",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    p_conv.add_argument('s2p_file', help="Full S2P Touchstone file to convert")
    p_conv.add_argument('--fmin', type=str, default=None, help="Min frequency (e.g. 1MHz)")
    p_conv.add_argument('--fmax', type=str, default=None, help="Max frequency (e.g. 500MHz)")
    p_conv.add_argument('--overwrite', action='store_true', help="Overwrite existing files without asking")
    p_conv.add_argument('--silent', action='store_true', help="Suppress output messages")

    # --- merge ---
    p_merge = subparsers.add_parser(
        'merge',
        help="Merge two NanoVNA half-measurements into a full S2P",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    p_merge.add_argument('forward', help="S2P with S11 and S21 (port1→port2)")
    p_merge.add_argument('reverse', help="S2P with S22 and S12 (port2→port1, DUT flipped)")
    p_merge.add_argument('-o', '--output', default=None,
                         help="Output file (default: <forward_stem>_full.s2p)")
    p_merge.add_argument('--silent', action='store_true', help="Suppress output messages")

    # --- merge-convert ---
    p_mc = subparsers.add_parser(
        'merge-convert',
        help="Merge two half-measurements and convert the result to LTspice",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    p_mc.add_argument('forward', help="S2P with S11 and S21 (port1→port2)")
    p_mc.add_argument('reverse', help="S2P with S22 and S12 (port2→port1, DUT flipped)")
    p_mc.add_argument('-o', '--output', default=None,
                      help="Intermediate merged S2P file (default: <forward_stem>_full.s2p)")
    p_mc.add_argument('--fmin', type=str, default=None, help="Min frequency (e.g. 1MHz)")
    p_mc.add_argument('--fmax', type=str, default=None, help="Max frequency (e.g. 500MHz)")
    p_mc.add_argument('--overwrite', action='store_true', help="Overwrite existing files without asking")
    p_mc.add_argument('--silent', action='store_true', help="Suppress output messages")

    args = parser.parse_args()

    def log(msg):
        if not args.silent:
            print(msg)

    # ---- dispatch ----

    if args.command == 'convert':
        log(f"Processing file: {args.s2p_file}")
        do_convert(args.s2p_file, overwrite=args.overwrite, silent=args.silent,
                   fmin_str=args.fmin, fmax_str=args.fmax)

    elif args.command == 'merge':
        combined = merge_networks(args.forward, args.reverse, silent=args.silent)
        out_path = args.output or (Path(args.forward).stem + '_full.s2p')
        if not out_path.lower().endswith('.s2p'):
            out_path += '.s2p'
        combined.write_touchstone(out_path)
        log(f"Written: {out_path}")
        log(f"  Frequencies : {combined.f[0]:.0f} Hz  →  {combined.f[-1]:.0f} Hz  ({len(combined.f)} points)")
        log(f"  S11 |avg|   : {np.abs(combined.s[:, 0, 0]).mean():.4f}")
        log(f"  S21 |avg|   : {np.abs(combined.s[:, 1, 0]).mean():.4f}")
        log(f"  S12 |avg|   : {np.abs(combined.s[:, 0, 1]).mean():.4f}")
        log(f"  S22 |avg|   : {np.abs(combined.s[:, 1, 1]).mean():.4f}")

    elif args.command == 'merge-convert':
        out_path = args.output or (Path(args.forward).stem + '_full.s2p')
        if not out_path.lower().endswith('.s2p'):
            out_path += '.s2p'
        combined = merge_networks(args.forward, args.reverse, silent=args.silent)
        combined.write_touchstone(out_path)
        log(f"Merged S2P written: {out_path}")
        do_convert(out_path, overwrite=args.overwrite, silent=args.silent,
                   fmin_str=args.fmin, fmax_str=args.fmax)


# Run the main function when the script is executed
if __name__ == '__main__':
    main()


