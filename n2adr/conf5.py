import sys

if sys.platform != "win32":
  digital_input_name = 'hw:Loopback,0'
  digital_output_name = digital_input_name

