"""
@author: https://mdiea.github.io/

"""
#import argparse
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter, FileType
from pathlib import Path
from skrf import Network
from re import match

# Function to prompt the user for confirmation to overwrite a file
def ask_overwrite(file_path):
    response = input(f"File {file_path} already exists. Do you want to overwrite it? (y/n): ")
    return response.lower() == 'y'

# Function to convert frequency units to Hz
def convert_frequency(value):
    """
    Converts a frequency value in string format to a numeric value in Hz.
    Example input: '425MHz', '1GHz', etc.
    """
    m = match(r'(\d+\.?\d*)([a-zA-Z]+)', value.lower())
    if not m:
        raise ValueError(f"Invalid frequency: {value}")
    
    number, unit = m.groups()
    number = float(number)
    
    unit_map = {
        'hz': 1,
        'khz': 1e3,
        'mhz': 1e6,
        'ghz': 1e9
    }
    
    if unit not in unit_map:
        raise ValueError(f"Unsupported frequency unit: {unit}")
    
    return number * unit_map[unit]




# Define the main function
def main():
    # Initialize the parser
    parser = ArgumentParser(
        description="This program processes a S2P Touchstone file, and generate a LTspice model",
        formatter_class=ArgumentDefaultsHelpFormatter
    )

    # Add a version argument
    parser.add_argument(
        '--version', 
        action='version', 
        version='%(prog)s x.x',  # Replace with your program's version
        help="Show program's version number and exit"
    )

    # Add a flag to skip confirmation (overwrite files)
    parser.add_argument(
        '--overwrite', 
        action='store_true', 
        help="If specified, will overwrite existing files without asking"
    )
    # Add a flag for silent mode
    parser.add_argument(
        '--silent', 
        action='store_true', 
        help="If specified, suppress all output messages"
    )

    # Add frequency range arguments
    parser.add_argument(
        '--fmin', 
        type=str, 
        default=None, 
        help="Minimum frequency in Hz, kHz, MHz or GHz (optional)"
    )
    parser.add_argument(
        '--fmax', 
        type=str, 
        default=None, 
        help="Maximum frequency in Hz, kHz, MHz or GHz (optional)"
    )

    # Add a file argument for the text file
    parser.add_argument(
        's2p_file', 
        type=FileType('r'), 
        help="The S2P Touchstone file to be processed"
    )

    # Parse the arguments
    args = parser.parse_args()

    # Helper function to print messages only if not in silent mode
    def print_if_not_silent(message):
        if not args.silent:
            print(message)

    # Read and process the file
    with args.s2p_file as file:
        content = file.read()
        print_if_not_silent(f"Processing file: {args.s2p_file.name}")
        #print("File Content:")
        #print(content)

    # Define input and output names
    name = Path(args.s2p_file.name).stem
    sub_file = name + '.sub'
    asy_file = name + '.asy'
    asc_file = 'test-' + name + '.asc'
    touchstone_file = args.s2p_file.name

    try:
        # Attempt to load the Touchstone file
        touchstone = Network(touchstone_file)
    except Exception as e:
        # If an error occurs, print the message and terminate the program
        print(f"Error loading Touchstone file: {e}")
        exit(1)  # Exit the program with an error code

    # Convert the minimum and maximum frequencies if specified
    fmin = convert_frequency(args.fmin) if args.fmin else touchstone.f[0]
    fmax = convert_frequency(args.fmax) if args.fmax else touchstone.f[-1]

    # Filter the network to only include frequencies within the selected range
    touchstone_filtered = touchstone[f'{fmin}Hz-{fmax}Hz']
    print_if_not_silent(f"Filtered frequencies: from {touchstone_filtered.f[0]}Hz to {touchstone_filtered.f[-1]}Hz")

    frequencies = touchstone_filtered.f.squeeze()
    Z01=touchstone.z0[0].real[0]
    print_if_not_silent(f"Z0 port 1 example only: {Z01}")
    Z02=touchstone.z0[0].real[1]
    print_if_not_silent(f"Z0 port 2 example only: {Z02}")

    # Create the dictionary of S parameters
    s_parameters = {
        'B11 11 12 V={V(10,3)}': (touchstone_filtered.s11.s_re.squeeze(), touchstone_filtered.s11.s_im.squeeze()),
        'B22 22 3  V={V(20,3)}': (touchstone_filtered.s22.s_re.squeeze(), touchstone_filtered.s22.s_im.squeeze()),
        'B12 12 3  V={V(20,3)}': (touchstone_filtered.s12.s_re.squeeze(), touchstone_filtered.s12.s_im.squeeze()),
        'B21 21 22 V={V(10,3)}': (touchstone_filtered.s21.s_re.squeeze(), touchstone_filtered.s21.s_im.squeeze())
    }

    # Helper function to format the parameters
    def format_s_parameter(name, re, im, freqs):
        data = [f'({freq},{r:.12e},{i:.12e})' for freq, r, i in zip(freqs, re, im)]
        lines = [f'{name} R_I FREQ {data[0]}'] + [f'+{d}' for d in data[1:]]
        return '\n'.join(lines) + '\n'


    # Check if any files exist and ask whether to overwrite (unless --overwrite is specified)
    files_to_check = [sub_file, asy_file, asc_file]
    for file in files_to_check:
        if Path(file).exists() and not args.overwrite:
            response = input(f"Warning: {file} already exists. Do you want to overwrite it? (y/n): ")
            if response.lower() != 'y':
                print(f"Error: {file} will not be overwritten. Exiting the program.")
                exit(1)  # Quit the program if the user chooses not to overwrite


    # Write .sub file
    with open(sub_file, mode='w') as archivo:
        # Write the subcircuit definition and S parameters in a single write block
        archivo.write(f'.subckt {name} 1 2 3\n')
        archivo.write('R1N 10 1 -50\n')
        archivo.write('R2P 21 20 100\n')
        archivo.write('R1P 11 10 100\n')
        archivo.write('R4 20 2 -50\n')
        
        # Collect the S parameter data and write it all at once
        for nombre, (re, im) in s_parameters.items():
            archivo.write(format_s_parameter(nombre, re, im, frequencies))
        archivo.write('.ends s_block')

    print_if_not_silent(f"Write {sub_file}")

    # Write .asy file
    asy_content = [
        'Version 4\n',
        'SymbolType CELL\n',
        'LINE Normal 0 26 34 26\n',
        'LINE Normal 0 -15 34 -15\n',
        'LINE Normal 31 23 31 7\n',
        'LINE Normal 3 4 3 -12\n',
        'LINE Normal 34 -15 34 -12\n',
        'LINE Normal 0 -15 34 -15\n',
        'LINE Normal 0 7 0 -15\n',
        'LINE Normal 31 7 0 7\n',
        'LINE Normal 31 23 31 7\n',
        'LINE Normal 0 23 31 23\n',
        'LINE Normal 0 26 0 23\n',
        'LINE Normal 34 26 0 26\n',
        'LINE Normal 34 4 34 26\n',
        'LINE Normal 3 4 34 4\n',
        'LINE Normal 3 -12 3 4\n',
        'LINE Normal 34 -12 3 -12\n',
        'RECTANGLE Normal -48 -32 80 80\n',
        'TEXT 17 34 Center 0 PARAMS\n',
        'TEXT -33 38 VCenter 0 mdiea.github.io\n',
        'WINDOW 0 -49 -58 Left 2\n',
        'WINDOW 38 17 -39 Center 0\n',
        f'SYMATTR SpiceModel {name}\n',
        'SYMATTR Prefix X\n',
        f'SYMATTR ModelFile {sub_file}\n',
        'SYMATTR Description S parameters\n',
        'PIN -48 -16 LEFT 8\n',
        'PINATTR PinName 1\n',
        'PINATTR SpiceOrder 1\n',
        'PIN 80 -16 RIGHT 8\n',
        'PINATTR PinName 2\n',
        'PINATTR SpiceOrder 2\n',
        'PIN 16 80 BOTTOM 8\n',
        'PINATTR PinName gnd\n',
        'PINATTR SpiceOrder 3\n'
    ]

    # Write the .asy file in one go
    with open(asy_file, mode='w') as archivo:
        archivo.writelines(asy_content)

    print_if_not_silent(f"Write {asy_file}")


    # Write .asc file
    asc_content = [
        'Version 4\n',
        'SHEET 1 880 680\n',
        'WIRE 144 112 32 112\n',
        'WIRE 352 112 272 112\n',
        'WIRE 32 160 32 112\n',
        'WIRE 352 176 352 112\n',
        'WIRE 208 256 208 208\n',
        'WIRE 32 272 32 240\n',
        'WIRE 352 272 352 256\n',
        'FLAG 208 256 0\n',
        'FLAG 32 272 0\n',
        'FLAG 352 272 0\n',
        'SYMBOL voltage 32 144 R0\n',
        'WINDOW 123 24 124 Left 2\n',
        'WINDOW 39 24 152 Left 2\n',
        'SYMATTR Value2 AC 1\n',
        f'SYMATTR SpiceLine Rser={Z01}\n',
        'SYMATTR InstName V1\n',
        'SYMATTR Value ""\n',
        'SYMBOL res 336 160 R0\n',
        'SYMATTR InstName RL\n',
        f'SYMATTR Value {Z02}\n',
        f'SYMBOL {name} 192 128 R0\n',
        'SYMATTR InstName U1\n',
        f'TEXT 40 0 Left 2 !.ac lin {len(frequencies)} {frequencies[0]} {frequencies[-1]}\n',
        'TEXT 40 32 Left 2 !.net I(RL) V1\n'
    ]

    # Write the .asy file in one go
    with open(asc_file, mode='w') as archivo:
        archivo.writelines(asc_content)

    print_if_not_silent(f"Write {asc_file}")


# Run the main function when the script is executed
if __name__ == '__main__':
    main()


