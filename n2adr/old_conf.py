# This is the config file from my shack, which controls various hardware.  It is
# a complicated file.  The files to control my 2010 transceiver
# and for the improved version HiQSDR are in the package directory HiQSDR.

import sys

#dev	= 'SoftRock'
#dev	= 'SoftRockTx'
dev	= 'Transceiver'
#dev	= 'SDR-IQ'
#dev	= 'SoundCard'

if sys.platform == "win32":
  name_of_sound_capt = "Primary"
  name_of_sound_play = 'Primary'
  microphone_name    = "AK5370"
  latency_millisecs = 150
  data_poll_usec = 20000
else:
  name_of_sound_capt = 'hw:0'  #'alsa:Audiophile'
  name_of_sound_play = 'hw:0'    #"alsa:USB Audio CODEC"
  microphone_name = "alsa:AK5370"
  latency_millisecs = 50
  data_poll_usec = 5000

mic_clip = 3.0				# 3.0
mic_preemphasis = 0.6		# 0.6
playback_rate = 48000

default_screen = 'WFall'
waterfall_y_scale = 80
waterfall_y_zero  = 40
waterfall_graph_y_scale = 40
waterfall_graph_y_zero = 90
waterfall_graph_size = 160

add_imd_button = 1
add_fdx_button = 1

if dev[0:8] == 'SoftRock':
  from softrock import hardware_usb as quisk_hardware
  usb_vendor_id = 0x16c0
  usb_product_id = 0x05dc
  softrock_model = "RxEnsemble2"
  sample_rate = 48000			# ADC hardware sample rate in Hertz
  if dev == 'SoftRockTx':
    from softrock import widgets_tx as quisk_widgets
    softrock_model = "RxTxEnsemble"
    name_of_mic_play = name_of_sound_capt
    mic_playback_rate = sample_rate
    mic_out_volume = 0.6
    # Test transmit audio
    # name_of_mic_play = name_of_sound_play
    # mic_playback_rate = playback_rate
    # name_of_sound_play = ""
  else:
    microphone_name = ""

if dev == 'Transceiver':
  from n2adr import quisk_hardware
  from n2adr import quisk_widgets
  use_rx_udp = 1			# Get ADC samples from UDP
  rx_udp_ip = "192.168.2.196"		# Sample source IP address
  rx_udp_port = 0xBC77			# Sample source UDP port
  rx_udp_clock = 122880000  		# ADC sample rate in Hertz
  rx_udp_decimation = 8 * 8 * 8		# Decimation from clock to UDP sample rate
  sample_rate = int(float(rx_udp_clock) / rx_udp_decimation + 0.5)	# Don't change this
  name_of_sound_capt = ""		# We do not capture from the soundcard
  data_poll_usec = 10000
  playback_rate = 48000
  display_fraction = 0.96
  tx_ip = "192.168.2.196"
  tx_audio_port = 0xBC79
  mic_out_volume = 1.0

if dev == 'SDR-IQ':
  use_sdriq = 1				# Use the SDR-IQ
  sdriq_name = "/dev/ft2450"		# Name of the SDR-IQ device to open
  sdriq_clock = 66666667.0		# actual sample rate (66666667 nominal)
  sdriq_decimation = 600		# Must be 360, 500, 600, or 1250
  sample_rate = int(float(sdriq_clock) / sdriq_decimation + 0.5)	# Don't change this
  name_of_sound_capt = ""		# We do not capture from the soundcard
  display_fraction = 0.85
  microphone_name = ""

if dev == 'SoundCard':
  from n2adr import quisk_hardware
  from n2adr import quisk_widgets
  sample_rate = 48000
  playback_rate = 48000
  microphone_name = ""

## SSB exciter
#  tx_ip = "192.168.2.195"
#  key_method = "192.168.2.195"		# Use UDP from this address
#  tx_audio_port = 0x553B
#  mic_out_volume = 0.6772

if microphone_name:
  mixer_settings = [
    (microphone_name, 2, 0.80),		# numid of microphone volume control, volume 0.0 to 1.0;
    (microphone_name, 1, 1.0)		# numid of capture on/off control, turn on with 1.0;
  ]
