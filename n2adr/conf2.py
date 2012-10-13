# This is a second config file that I use to test various hardware configurations.

import sys

if sys.platform == "win32":
  name_of_sound_capt = "Primary"
  name_of_sound_play = 'Primary'
  latency_millisecs = 150
  data_poll_usec = 20000
else:
  name_of_sound_capt = 'hw:0'  #'alsa:Audiophile'
  name_of_sound_play = 'hw:0'    #"alsa:USB Audio CODEC"
  latency_millisecs = 150
  data_poll_usec = 5000

sdriq_name = "/dev/ttyUSB0"		# Name of the SDR-IQ device to open
mic_clip = 3.0
mic_preemphasis = 0.6

default_screen = 'WFall'
waterfall_y_scale = 80
waterfall_y_zero  = 40
waterfall_graph_y_scale = 40
waterfall_graph_y_zero = 90
waterfall_graph_size = 160
display_fraction = 1.00			# The edges of the full bandwidth are not valid

if microphone_name:
  mixer_settings = [
    (microphone_name, 2, 0.80),		# numid of microphone volume control, volume 0.0 to 1.0;
    (microphone_name, 1, 1.0)		# numid of capture on/off control, turn on with 1.0;
  ]
