# This is the config file from my shack, which controls various hardware.
# The files to control my 2010 transceiver and for the improved version HiQSDR
# are in the package directory HiQSDR.

import sys
from n2adr import quisk_hardware
from n2adr import quisk_widgets

if sys.platform == "win32":
  name_of_sound_play = 'Primary'
  microphone_name    = "Microphone"
  latency_millisecs = 150
  data_poll_usec = 20000
elif 0:		# portaudio devices
  name_of_sound_play = 'portaudio:hw:0'
  microphone_name = "portaudio:AK5370"
  latency_millisecs = 150
  data_poll_usec = 5000
  digital_input_name = 'portaudio:hw:2,0'
  digital_output_name = digital_input_name
else:		# alsa devices
  name_of_sound_play = 'hw:0'
  microphone_name = "alsa:AK5370"
  latency_millisecs = 150
  data_poll_usec = 5000
  digital_input_name =  'hw:Loopback,0'
  digital_output_name = 'hw:Loopback,0'

mic_clip = 2.0			# 3.0
mic_preemphasis = 0.6		# 0.6
mic_sample_rate = 48000
playback_rate = 48000
agc_off_gain = 80

default_screen = 'WFall'
waterfall_y_scale = 80
waterfall_y_zero  = 40
waterfall_graph_y_scale = 40
waterfall_graph_y_zero = 90
waterfall_graph_size = 160

add_imd_button = 1
add_fdx_button = 1

use_rx_udp = 1				# Get ADC samples from UDP
rx_udp_ip = "192.168.2.196"		# Sample source IP address
rx_udp_port = 0xBC77			# Sample source UDP port
rx_udp_clock = 122880000  		# ADC sample rate in Hertz
rx_udp_decimation = 8 * 8 * 8		# Decimation from clock to UDP sample rate
sample_rate = int(float(rx_udp_clock) / rx_udp_decimation + 0.5)	# Don't change this
name_of_sound_capt = ""			# We do not capture from the soundcard
data_poll_usec = 10000
playback_rate = 48000
display_fraction = 1.00
tx_ip = "192.168.2.196"
tx_audio_port = 0xBC79
mic_out_volume = 1.0

mixer_settings = [
    (microphone_name, 2, 0.80),		# numid of microphone volume control, volume 0.0 to 1.0;
    (microphone_name, 1, 1.0)		# numid of capture on/off control, turn on with 1.0;
  ]
