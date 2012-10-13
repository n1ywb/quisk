# This is a config file to test the microphone by sending filtered
# microphone sound to the FFT.  The PTT button and the FDX button must be pressed.
# Set mic_sample_rate to 8000 or 48000.
# To test mic filtering and UDP, set DEBUG_MIC to one in sound.c, and sample_rate to 48000.
# To test mic playback, set DEBUG_MIC to two in sound.c, and sample_rate to 48k, 96k or 192k.

import sys
from quisk_hardware_model import Hardware as BaseHardware
import _quisk as QS

if sys.platform == "win32":
  name_of_sound_capt = "Primary"
  name_of_sound_play = ''
  microphone_name    = "Microphone"
  name_of_mic_play = 'Primary'
  latency_millisecs = 150
  data_poll_usec = 10000
else:
  name_of_sound_capt = 'hw:0'
  name_of_sound_play = ''
  microphone_name = "alsa:AK5370"
  name_of_mic_play = 'hw:0'
  latency_millisecs = 50
  data_poll_usec = 5000

graph_y_scale = 160

sample_rate = 192000
mic_sample_rate = 48000
mic_playback_rate = sample_rate
mic_out_volume = 0.6

mic_clip = 2.0
mic_preemphasis = 1.0
add_fdx_button = 1

if microphone_name:
  mixer_settings = [
    (microphone_name, 2, 0.80),		# numid of microphone volume control, volume 0.0 to 1.0;
    (microphone_name, 1, 1.0)		# numid of capture on/off control, turn on with 1.0;
  ]

class Hardware(BaseHardware):
  def __init__(self, app, conf):
    BaseHardware.__init__(self, app, conf)
    self.use_sidetone = 1
  def OnButtonPTT(self, event):
    if event.GetEventObject().GetValue():
      QS.set_key_down(1)
    else:
      QS.set_key_down(0)
